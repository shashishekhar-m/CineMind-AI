"""Orchestrates the IMDb ETL foundation: Extract -> Validate -> Transform -> Load.

Usage:
    python pipeline.py                          # run all supported datasets
    python pipeline.py --datasets title_basics name_basics
    python pipeline.py --resume                 # skip rows already checkpointed
    python pipeline.py --stop-on-error

Datasets are processed in dependency order: movies (title_basics) and
people (name_basics) must load before anything that references them
(title_ratings, title_principals, title_crew).
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from etl import extract
from etl import load_database
from etl import transform
from etl import validate

from etl.config import settings
from etl.constants import IMDB_DUPLICATE_KEYS, IMDB_REQUIRED_COLUMNS
from etl.logger import get_logger

logger = get_logger(__name__)

PIPELINE_NAME = "cinemind_imdb_etl"

# Dependency order: title_basics/name_basics create movies/people that
# title_ratings/title_principals/title_crew reference via foreign keys.
DATASET_ORDER: List[str] = [
    "title_basics",
    "name_basics",
    "title_ratings",
    "title_principals",
    "title_crew",
]

_DATASET_TYPE_MAP = {
    "title_basics": transform.DatasetType.TITLE_BASICS,
    "title_ratings": transform.DatasetType.TITLE_RATINGS,
    "name_basics": transform.DatasetType.NAME_BASICS,
    "title_principals": transform.DatasetType.TITLE_PRINCIPALS,
    "title_crew": transform.DatasetType.TITLE_CREW,
}


class PipelineError(Exception):
    pass


class CheckpointStore:
    """Tracks per-dataset progress so a restarted run can skip rows that
    were already extracted, validated, transformed and loaded.

    Checkpoints are best-effort: because every load_database.py write is
    an idempotent upsert, re-processing rows after a checkpoint is always
    safe. Skipping is purely a performance optimization on resume.
    """

    def __init__(self, checkpoint_dir: Optional[Path] = None) -> None:
        self.checkpoint_dir = checkpoint_dir or settings.checkpoint_path
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, dataset_name: str) -> Path:
        return self.checkpoint_dir / f"{dataset_name}.json"

    def load(self, dataset_name: str) -> Dict[str, Any]:
        path = self._path(dataset_name)

        if not path.exists() or path.stat().st_size == 0:
            return {"dataset": dataset_name, "rows_processed": 0, "status": "pending"}

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Checkpoint for '%s' is corrupt; starting fresh.", dataset_name)
            return {"dataset": dataset_name, "rows_processed": 0, "status": "pending"}

    def save(self, dataset_name: str, **fields: Any) -> None:
        data = self.load(dataset_name)
        data.update(fields)
        data["dataset"] = dataset_name
        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        self._path(dataset_name).write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )


class ETLPipeline:
    """Runs Extract -> Validate -> Transform -> Load for one or more
    IMDb datasets, in dependency order, with checkpointing and stats.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        resume: bool = False,
        stop_on_error: bool = False,
        checkpoint_store: Optional[CheckpointStore] = None,
        loader: Optional[load_database.DatabaseLoader] = None,
    ) -> None:
        self.chunk_size = chunk_size or settings.batch_size
        self.resume = resume
        self.stop_on_error = stop_on_error
        self.checkpoints = checkpoint_store or CheckpointStore()
        self.loader = loader or load_database.DatabaseLoader(batch_size=self.chunk_size)
        self.transformer = transform.IMDbTransformer()

        self.run_summaries: Dict[str, Dict[str, Any]] = {}

    def run(self, dataset_names: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        datasets = dataset_names or DATASET_ORDER

        # Always respect dependency order, even if the caller passed a
        # subset or an out-of-order list.
        ordered = [name for name in DATASET_ORDER if name in datasets]

        logger.info(
            "Starting pipeline '%s' for datasets: %s (resume=%s)",
            PIPELINE_NAME,
            ordered,
            self.resume,
        )

        for dataset_name in ordered:
            try:
                self.run_summaries[dataset_name] = self._run_dataset(dataset_name)

            except PipelineError as exc:
                logger.error("Dataset '%s' failed: %s", dataset_name, exc)

                self.run_summaries[dataset_name] = {
                    "status": "failed",
                    "error": str(exc),
                }

                if self.stop_on_error:
                    logger.error("stop_on_error=True; halting pipeline.")
                    break

        self.loader.close()

        logger.info(
            "Pipeline finished. Summary: %s",
            json.dumps(self.run_summaries, indent=2, default=str),
        )

        return self.run_summaries

    def _run_dataset(self, dataset_name: str) -> Dict[str, Any]:
        required_columns = IMDB_REQUIRED_COLUMNS.get(dataset_name)

        if required_columns is None:
            raise PipelineError(f"Dataset '{dataset_name}' is out of scope for this pipeline.")

        dataset_type = _DATASET_TYPE_MAP[dataset_name]

        try:
            dataset_info = extract.validate_dataset(dataset_name)
        except extract.ExtractError as exc:
            raise PipelineError(f"Cannot locate/read dataset file: {exc}") from exc

        checkpoint = self.checkpoints.load(dataset_name) if self.resume else {"rows_processed": 0}
        skip_rows = checkpoint.get("rows_processed", 0) if self.resume else 0

        if skip_rows:
            logger.info("Resuming '%s' after %s already-processed rows.", dataset_name, f"{skip_rows:,}")

        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()

        self.checkpoints.save(dataset_name, status="running", started_at=started_at.isoformat())

        # Snapshot loader totals before this stage so we can report a
        # per-stage delta rather than the loader's running cumulative
        # totals (the same DatabaseLoader/session persists across all
        # dataset stages in one pipeline run).
        before_stats = {
            table: dict(stats.summary())
            for table, stats in self.loader.statistics.items()
        }

        row_iterator = extract.iter_dataset(dataset_name, required_columns=required_columns)

        if skip_rows:
            row_iterator = itertools.islice(row_iterator, skip_rows, None)

        chunk_iterator = self._chunk(row_iterator, self.chunk_size)

        validator = validate.create_validator(
            dataset_name=dataset_name,
            required_columns=required_columns,
            duplicate_key=IMDB_DUPLICATE_KEYS.get(dataset_name),
            invalid_rows_path=settings.log_path / f"{dataset_name}_invalid_rows.csv",
        )

        rows_processed = skip_rows
        error_message: Optional[str] = None
        status = "completed"

        try:
            for valid_chunk in validator.validate(chunk_iterator):
                table_records: Dict[str, list] = defaultdict(list)

                for row in valid_chunk:
                    output = self.transformer.transform_to_postgresql(dataset_type, row)

                    for table_name, table_batch in output.items():
                        table_records[table_name].extend(table_batch)

                self.loader.load_chunk(table_records)

                rows_processed += len(valid_chunk)
                self.checkpoints.save(dataset_name, rows_processed=rows_processed, status="running")

                logger.info(
                    "%s: %s rows processed so far.",
                    dataset_name,
                    f"{rows_processed:,}",
                )

        except Exception as exc:  # noqa: BLE001 - pipeline must degrade gracefully
            status = "failed"
            error_message = str(exc)
            logger.exception("Dataset '%s' failed during processing.", dataset_name)

        finally:
            validation_stats = validator.statistics()
            transform_stats = self.transformer.get_statistics(dataset_type)
            elapsed = time.perf_counter() - start_time
            finished_at = datetime.now(timezone.utc)

            after_stats = {
                table: dict(stats.summary())
                for table, stats in self.loader.statistics.items()
            }
            stage_load_summary = self._delta_summary(before_stats, after_stats)

            self.checkpoints.save(
                dataset_name,
                rows_processed=rows_processed,
                status=status,
                finished_at=finished_at.isoformat(),
                execution_time_seconds=round(elapsed, 2),
                error_message=error_message,
            )

            self.loader.record_etl_run(
                pipeline_name=PIPELINE_NAME,
                source_name=dataset_name,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                records_read=validation_stats.rows_processed,
                records_inserted=sum(
                    s["rows_inserted"] for s in stage_load_summary.values()
                ),
                records_updated=sum(
                    s["rows_updated"] for s in stage_load_summary.values()
                ),
                records_failed=validation_stats.invalid_rows + sum(
                    s["rows_failed"] for s in stage_load_summary.values()
                ),
                execution_time_seconds=round(elapsed, 2),
                error_message=error_message,
            )

            logger.info(
                "%s finished in %.2fs | status=%s | dataset_info=%s",
                dataset_name,
                elapsed,
                status,
                dataset_info.name,
            )

        if status == "failed":
            raise PipelineError(error_message or "Unknown failure")

        return {
            "status": status,
            "rows_processed": rows_processed,
            "execution_time_seconds": round(elapsed, 2),
            "validation": {
                "valid_rows": validation_stats.valid_rows,
                "invalid_rows": validation_stats.invalid_rows,
                "duplicate_rows": validation_stats.duplicate_rows,
            },
            "transform": {
                "rows_transformed": transform_stats.rows_transformed,
                "rows_skipped": transform_stats.rows_skipped,
                "rows_failed": transform_stats.rows_failed,
            },
            "load": stage_load_summary,
        }

    @staticmethod
    def _delta_summary(
        before: Dict[str, Dict[str, Any]],
        after: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        numeric_fields = (
            "rows_received",
            "rows_inserted",
            "rows_updated",
            "rows_skipped",
            "rows_failed",
            "batches_committed",
            "batches_rolled_back",
            "retries_attempted",
        )

        delta: Dict[str, Dict[str, Any]] = {}

        for table, after_stats in after.items():
            before_stats = before.get(table)

            if before_stats is None:
                delta[table] = {k: after_stats[k] for k in numeric_fields}
                delta[table]["table"] = table
                continue

            delta[table] = {
                k: after_stats[k] - before_stats[k] for k in numeric_fields
            }
            delta[table]["table"] = table

        return delta

    @staticmethod
    def _chunk(row_iterator, size: int):
        while True:
            batch = list(itertools.islice(row_iterator, size))

            if not batch:
                return

            yield batch


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CineMind AI - IMDb ETL pipeline")

    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=DATASET_ORDER,
        default=None,
        help="Subset of datasets to run (default: all, in dependency order).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip rows already recorded in the dataset's checkpoint file.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Halt the whole pipeline on the first dataset failure.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Override the configured batch/chunk size.",
    )

    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    pipeline = ETLPipeline(
        chunk_size=args.chunk_size,
        resume=args.resume,
        stop_on_error=args.stop_on_error,
    )

    pipeline.run(dataset_names=args.datasets)


if __name__ == "__main__":
    main()
