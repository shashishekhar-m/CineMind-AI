from __future__ import annotations

import csv
import gzip
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, TextIO, TypeAlias
from functools import lru_cache

from config import settings
from constants import (
    CHUNK_SIZE,
    ENCODING_CANDIDATES,
    IMDB_DATASETS,
)
from logger import get_logger

logger = get_logger(__name__)

Row: TypeAlias = Dict[str, Any]
RowBatch: TypeAlias = List[Row]
ChunkIterator: TypeAlias = Iterator[RowBatch]
PathLike: TypeAlias = str | Path


@dataclass(slots=True, frozen=True)
class DatasetInfo:
    name: str
    file_name: str
    path: Path
    delimiter: str = "\t"
    encoding: str = "utf-8"
    compressed: bool = False

    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def size_bytes(self) -> int:
        if not self.exists:
            return 0
        return self.path.stat().st_size

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)


class ExtractError(Exception):
    pass


def resolve_path(path: PathLike) -> Path:
    return Path(path).expanduser().resolve()


def ensure_file_exists(path: PathLike) -> Path:
    file_path = resolve_path(path)

    if not file_path.exists():
        raise ExtractError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise ExtractError(f"Expected a file: {file_path}")

    return file_path


def is_gzip_file(path: PathLike) -> bool:
    return str(path).lower().endswith(".gz")


def get_dataset_info(dataset_name: str) -> DatasetInfo:
    if dataset_name not in IMDB_DATASETS:
        raise ExtractError(f"Unknown dataset: {dataset_name}")

    file_name = IMDB_DATASETS[dataset_name]
    file_path = settings.IMDB_RAW_DIR / file_name

    return DatasetInfo(
        name=dataset_name,
        file_name=file_name,
        path=file_path,
        compressed=is_gzip_file(file_name),
    )

@lru_cache(maxsize=64)
def detect_encoding(path: PathLike) -> str:
    file_path = ensure_file_exists(path)

    for encoding in ENCODING_CANDIDATES:
        try:
            with (
                gzip.open(file_path, "rt", encoding=encoding)
                if is_gzip_file(file_path)
                else open(file_path, "r", encoding=encoding)
            ) as fp:
                fp.readline()
            return encoding
        except (UnicodeDecodeError, OSError):
            continue

    raise ExtractError(f"Unable to detect encoding for: {file_path}")


def validate_dataset_file(path: PathLike) -> DatasetInfo:
    file_path = ensure_file_exists(path)

    return DatasetInfo(
        name=file_path.stem.replace(".tsv", ""),
        file_name=file_path.name,
        path=file_path,
        encoding=detect_encoding(file_path),
        compressed=is_gzip_file(file_path),
    )


def open_dataset(
    path: PathLike,
    encoding: Optional[str] = None,
) -> TextIO:
    file_path = ensure_file_exists(path)

    file_encoding = encoding or detect_encoding(file_path)

    try:
        if is_gzip_file(file_path):
            return gzip.open(
                file_path,
                mode="rt",
                encoding=file_encoding,
                newline="",
            )

        return open(
            file_path,
            mode="r",
            encoding=file_encoding,
            newline="",
        )

    except OSError as exc:
        raise ExtractError(f"Failed to open file: {file_path}") from exc


def count_rows(path: PathLike) -> int:
    total = 0

    with open_dataset(path) as fp:
        next(fp, None)

        for _ in fp:
            total += 1

    return total


def get_file_size(path: PathLike) -> int:
    return ensure_file_exists(path).stat().st_size


def get_file_size_mb(path: PathLike) -> float:
    return round(get_file_size(path) / (1024 * 1024), 2)


def get_file_name(path: PathLike) -> str:
    return ensure_file_exists(path).name


def get_file_extension(path: PathLike) -> str:
    return ensure_file_exists(path).suffix.lower()


def file_exists(path: PathLike) -> bool:
    return resolve_path(path).exists()


def is_empty_file(path: PathLike) -> bool:
    return get_file_size(path) == 0


def get_dataset_statistics(path: PathLike) -> Dict[str, Any]:
    dataset = validate_dataset_file(path)

    return {
        "name": dataset.name,
        "file_name": dataset.file_name,
        "path": str(dataset.path),
        "encoding": dataset.encoding,
        "compressed": dataset.compressed,
        "exists": dataset.exists,
        "rows": count_rows(dataset.path),
        "size_bytes": dataset.size_bytes,
        "size_mb": dataset.size_mb,
    }

class StreamingTSVReader:
    def __init__(
        self,
        dataset: DatasetInfo,
        chunk_size: int = CHUNK_SIZE,
        required_columns: Optional[Iterable[str]] = None,
    ) -> None:
        self.dataset = dataset
        self.chunk_size = chunk_size
        self.required_columns = set(required_columns or [])
        self._validated = False

    def _validate_columns(self, columns: List[str]) -> None:
        if self._validated:
            return

        missing = self.required_columns.difference(columns)
        unexpected = set(columns).difference(self.required_columns)

        messages = []

        if missing:
            messages.append(
                f"Missing columns: {', '.join(sorted(missing))}"
            )

        if unexpected:
            logger.debug(
                "%s: unexpected columns detected: %s",
                self.dataset.name,
                ", ".join(sorted(unexpected)),
            )

        if messages:
            raise ExtractError(
                f"{self.dataset.name}: {' | '.join(messages)}"
            )
        self._validated = True

    def stream_rows(self) -> Iterator[Row]:
        processed = 0

        with open_dataset(
            self.dataset.path,
            self.dataset.encoding,
        ) as fp:
            reader = csv.DictReader(
                fp,
                delimiter=self.dataset.delimiter,
            )

            if reader.fieldnames is None:
                raise ExtractError(
                    f"{self.dataset.name}: no header row found."
                )

            self._validate_columns(reader.fieldnames)

            for row in reader:
                processed += 1

                if processed % 100000 == 0:
                    logger.info(
                        "%s: processed %,d rows",
                        self.dataset.name,
                        processed,
                    )

                yield row

    

    def stream_chunks(self) -> ChunkIterator:
        chunk: RowBatch = []

        for row in self.stream_rows():
            chunk.append(row)

            if len(chunk) >= self.chunk_size:
                yield chunk
                chunk = []

        if chunk:
            yield chunk

    def __iter__(self) -> Iterator[Row]:
        return self.stream_rows()


def stream_dataset(
    dataset: DatasetInfo,
    chunk_size: int = CHUNK_SIZE,
    required_columns: Optional[Iterable[str]] = None,
) -> ChunkIterator:
    reader = StreamingTSVReader(
        dataset=dataset,
        chunk_size=chunk_size,
        required_columns=required_columns,
    )

    yield from reader.stream_chunks()


def stream_rows(
    dataset: DatasetInfo,
    required_columns: Optional[Iterable[str]] = None,
) -> Iterator[Row]:
    reader = StreamingTSVReader(
        dataset=dataset,
        required_columns=required_columns,
    )

    yield from reader.stream_rows()


def stream_dataset_by_name(
    dataset_name: str,
    chunk_size: int = CHUNK_SIZE,
    required_columns: Optional[Iterable[str]] = None,
) -> ChunkIterator:
    dataset = get_dataset_info(dataset_name)

    yield from stream_dataset(
        dataset=dataset,
        chunk_size=chunk_size,
        required_columns=required_columns,
    )


def iter_dataset(
    dataset_name: str,
    required_columns: Optional[Iterable[str]] = None,
) -> Iterator[Row]:
    dataset = get_dataset_info(dataset_name)

    yield from stream_rows(
        dataset=dataset,
        required_columns=required_columns,
    )


from collections import deque
from time import perf_counter
from typing import Deque

try:
    import psutil
except ImportError:
    psutil = None


@dataclass(slots=True)
class ProcessingStatistics:
    dataset_name: str
    start_time: float
    rows_processed: int = 0
    chunks_processed: int = 0
    invalid_rows: int = 0
    bytes_processed: int = 0

    @property
    def elapsed_time(self) -> float:
        return perf_counter() - self.start_time

    @property
    def rows_per_second(self) -> float:
        if self.elapsed_time <= 0:
            return 0.0
        return self.rows_processed / self.elapsed_time


class ProgressTracker:
    def __init__(
        self,
        total_rows: Optional[int] = None,
        log_every: int = 100000,
    ) -> None:
        self.total_rows = total_rows
        self.log_every = log_every
        self.current = 0

    def update(self, rows: int = 1) -> None:
        self.current += rows

        if self.current % self.log_every == 0:
            if self.total_rows:
                percentage = (self.current / self.total_rows) * 100

                logger.info(
                    "[%s/%s] %.2f%% completed",
                    f"{self.current:,}",
                    f"{self.total_rows:,}",
                    percentage,
                )
            else:
                logger.info(
                    "Processed %s rows",
                    f"{self.current:,}",
                )


class PerformanceMonitor:
    def __init__(self) -> None:
        self._start = perf_counter()
        self._lap = self._start

    def checkpoint(self) -> float:
        now = perf_counter()
        elapsed = now - self._lap
        self._lap = now
        return elapsed

    @property
    def total_elapsed(self) -> float:
        return perf_counter() - self._start


class MemoryMonitor:
    def current_mb(self) -> float:
        if psutil is None:
            return 0.0

        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)


class ChunkBuffer:
    def __init__(self, max_size: int = CHUNK_SIZE) -> None:
        self.max_size = max_size
        self.buffer: Deque[Row] = deque()

    def append(self, row: Row) -> Optional[RowBatch]:
        self.buffer.append(row)

        if len(self.buffer) >= self.max_size:
            chunk = list(self.buffer)
            self.buffer.clear()
            return chunk

        return None

    def flush(self) -> RowBatch:
        chunk = list(self.buffer)
        self.buffer.clear()
        return chunk


def safe_process_chunk(
    chunk: RowBatch,
    processor,
) -> Any:
    try:
        return processor(chunk)

    except Exception as exc:
        logger.exception("Chunk processing failed: %s", exc)
        raise ExtractError(str(exc)) from exc


def collect_statistics(
    dataset: DatasetInfo,
    rows_processed: int,
    chunks_processed: int,
    invalid_rows: int = 0,
) -> Dict[str, Any]:
    elapsed = perf_counter()

    return {
        "dataset": dataset.name,
        "rows_processed": rows_processed,
        "chunks_processed": chunks_processed,
        "invalid_rows": invalid_rows,
        "elapsed_seconds": round(elapsed, 2),
        "memory_mb": MemoryMonitor().current_mb(),
    }


def log_dataset_start(dataset: DatasetInfo) -> None:
    logger.info(
        "Starting extraction: %s (%s)",
        dataset.name,
        dataset.file_name,
    )


def log_dataset_finish(
    dataset: DatasetInfo,
    statistics: Dict[str, Any],
) -> None:
    logger.info(
        "Finished extraction: %s | %s rows | %s chunks",
        dataset.name,
        statistics["rows_processed"],
        statistics["chunks_processed"],
    )

class IMDbExtractor:
    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
    ) -> None:
        self.chunk_size = chunk_size
        self.memory_monitor = MemoryMonitor()

    def get_dataset(
        self,
        dataset_name: str,
    ) -> DatasetInfo:
        return get_dataset_info(dataset_name)

    def validate(
        self,
        dataset_name: str,
    ) -> DatasetInfo:
        dataset = self.get_dataset(dataset_name)
        return validate_dataset_file(dataset.path)

    def stream_rows(
        self,
        dataset_name: str,
        required_columns: Optional[Iterable[str]] = None,
    ) -> Iterator[Row]:
        dataset = self.validate(dataset_name)

        yield from stream_rows(
            dataset=dataset,
            required_columns=required_columns,
        )

    def stream_chunks(
        self,
        dataset_name: str,
        required_columns: Optional[Iterable[str]] = None,
    ) -> ChunkIterator:
        dataset = self.validate(dataset_name)

        yield from stream_dataset(
            dataset=dataset,
            chunk_size=self.chunk_size,
            required_columns=required_columns,
        )

    def dataset_statistics(
        self,
        dataset_name: str,
    ) -> Dict[str, Any]:
        dataset = self.validate(dataset_name)
        return get_dataset_statistics(dataset.path)

    def available_datasets(self) -> List[str]:
        return sorted(IMDB_DATASETS.keys())

    def dataset_exists(
        self,
        dataset_name: str,
    ) -> bool:
        try:
            dataset = self.get_dataset(dataset_name)
            return dataset.exists
        except ExtractError:
            return False

    def memory_usage(self) -> float:
        return self.memory_monitor.current_mb()


extractor = IMDbExtractor()


def get_extractor() -> IMDbExtractor:
    return extractor


def get_dataset(dataset_name: str) -> DatasetInfo:
    return extractor.get_dataset(dataset_name)


def validate_dataset(dataset_name: str) -> DatasetInfo:
    return extractor.validate(dataset_name)


def read_rows(
    dataset_name: str,
    required_columns: Optional[Iterable[str]] = None,
) -> Iterator[Row]:
    yield from extractor.stream_rows(
        dataset_name,
        required_columns,
    )


def read_chunks(
    dataset_name: str,
    required_columns: Optional[Iterable[str]] = None,
) -> ChunkIterator:
    yield from extractor.stream_chunks(
        dataset_name,
        required_columns,
    )


def dataset_statistics(
    dataset_name: str,
) -> Dict[str, Any]:
    return extractor.dataset_statistics(dataset_name)


def memory_usage() -> float:
    return extractor.memory_usage()


__all__ = [
    "DatasetInfo",
    "ExtractError",
    "StreamingTSVReader",
    "IMDbExtractor",
    "get_extractor",
    "get_dataset",
    "validate_dataset",
    "read_rows",
    "read_chunks",
    "dataset_statistics",
    "memory_usage",
]