from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TypeAlias

from constants import (
    IMDB_DATASETS,
    NULL_VALUES,
)
from logger import get_logger

logger = get_logger(__name__)

Row: TypeAlias = Dict[str, Any]
RowBatch: TypeAlias = List[Row]
ValidationErrors: TypeAlias = List[str]
ValidationWarnings: TypeAlias = List[str]


class ValidationError(Exception):
    pass


class ValidationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    SKIPPED = "SKIPPED"


class ValidationRule(str, Enum):
    REQUIRED_FIELD = "required_field"
    NULL_VALUE = "null_value"
    EMPTY_VALUE = "empty_value"
    INVALID_TYPE = "invalid_type"
    INVALID_RANGE = "invalid_range"
    INVALID_FORMAT = "invalid_format"
    DUPLICATE = "duplicate"
    UNKNOWN_DATASET = "unknown_dataset"
    MISSING_COLUMN = "missing_column"
    UNEXPECTED_COLUMN = "unexpected_column"


@dataclass(slots=True)
class ValidationIssue:
    rule: ValidationRule
    severity: ValidationSeverity
    field: Optional[str]
    message: str


@dataclass(slots=True)
class ValidationResult:
    status: ValidationStatus = ValidationStatus.VALID
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == ValidationStatus.VALID

    @property
    def has_errors(self) -> bool:
        return any(
            issue.severity == ValidationSeverity.ERROR
            for issue in self.issues
        )

    @property
    def has_warnings(self) -> bool:
        return any(
            issue.severity == ValidationSeverity.WARNING
            for issue in self.issues
        )

    def add_issue(
        self,
        rule: ValidationRule,
        severity: ValidationSeverity,
        message: str,
        field: Optional[str] = None,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                rule=rule,
                severity=severity,
                field=field,
                message=message,
            )
        )

        if severity == ValidationSeverity.ERROR:
            self.status = ValidationStatus.INVALID


@dataclass(slots=True)
class ValidationStatistics:
    dataset_name: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None

    rows_processed: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_rows: int = 0
    warning_rows: int = 0

    missing_field_errors: int = 0
    null_value_errors: int = 0
    type_errors: int = 0
    range_errors: int = 0

    unique_ids: Set[str] = field(default_factory=set)

    @property
    def total_errors(self) -> int:
        return (
            self.missing_field_errors
            + self.null_value_errors
            + self.type_errors
            + self.range_errors
        )

    @property
    def validation_rate(self) -> float:
        if self.rows_processed == 0:
            return 0.0

        return round(
            (self.valid_rows / self.rows_processed) * 100,
            2,
        )

    def finish(self) -> None:
        self.finished_at = datetime.utcnow()

    def validate_required_fields(
        row: Row,
        required_fields: List[str],
    ) -> ValidationResult:
        result = ValidationResult()

        for field in required_fields:
            if field not in row:
                result.add_issue(
                    rule=ValidationRule.REQUIRED_FIELD,
                    severity=ValidationSeverity.ERROR,
                    field=field,
                    message=f"Missing required field '{field}'.",
                )
                continue

            value = row[field]

            if value is None:
                result.add_issue(
                    rule=ValidationRule.REQUIRED_FIELD,
                    severity=ValidationSeverity.ERROR,
                    field=field,
                    message=f"Required field '{field}' is None.",
                )

        return result


    def validate_null_values(
        row: Row,
        fields: Optional[List[str]] = None,
    ) -> ValidationResult:
        result = ValidationResult()

        target_fields = fields or list(row.keys())

        for field in target_fields:
            if field not in row:
                continue

            value = row[field]

            if value is None:
                result.add_issue(
                    rule=ValidationRule.NULL_VALUE,
                    severity=ValidationSeverity.ERROR,
                    field=field,
                    message=f"Field '{field}' contains NULL.",
                )
                continue

            if isinstance(value, str):
                if value.strip() in NULL_VALUES:
                    result.add_issue(
                        rule=ValidationRule.NULL_VALUE,
                        severity=ValidationSeverity.ERROR,
                        field=field,
                        message=f"Field '{field}' contains IMDb null marker.",
                    )

        return result


    def validate_empty_values(
        row: Row,
        fields: Optional[List[str]] = None,
    ) -> ValidationResult:
        result = ValidationResult()

        target_fields = fields or list(row.keys())

        for field in target_fields:
            if field not in row:
                continue

            value = row[field]

            if isinstance(value, str):
                if value.strip() == "":
                    result.add_issue(
                        rule=ValidationRule.EMPTY_VALUE,
                        severity=ValidationSeverity.WARNING,
                        field=field,
                        message=f"Field '{field}' is empty.",
                    )

        return result


    def validate_type(
        value: Any,
        expected_type: type,
        field_name: str,
    ) -> ValidationResult:
        result = ValidationResult()

        if value is None:
            return result

        if isinstance(value, str):
            stripped = value.strip()

            if stripped in NULL_VALUES or stripped == "":
                return result

            try:
                if expected_type is int:
                    int(stripped)

                elif expected_type is float:
                    float(stripped)

                elif expected_type is bool:
                    if stripped.lower() not in {"0", "1", "true", "false"}:
                        raise ValueError

                elif expected_type is str:
                    pass

                else:
                    expected_type(stripped)

            except (TypeError, ValueError):
                result.add_issue(
                    rule=ValidationRule.INVALID_TYPE,
                    severity=ValidationSeverity.ERROR,
                    field=field_name,
                    message=(
                        f"Field '{field_name}' cannot be converted "
                        f"to {expected_type.__name__}."
                    ),
                )

            return result

        if not isinstance(value, expected_type):
            result.add_issue(
                rule=ValidationRule.INVALID_TYPE,
                severity=ValidationSeverity.ERROR,
                field=field_name,
                message=(
                    f"Field '{field_name}' has invalid type "
                    f"'{type(value).__name__}'. "
                    f"Expected '{expected_type.__name__}'."
                ),
            )

        return result


    def validate_range(
        value: Any,
        field_name: str,
        *,
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
    ) -> ValidationResult:
        result = ValidationResult()

        if value is None:
            return result

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            result.add_issue(
                rule=ValidationRule.INVALID_TYPE,
                severity=ValidationSeverity.ERROR,
                field=field_name,
                message=f"Field '{field_name}' is not numeric.",
            )
            return result

        if minimum is not None and numeric_value < minimum:
            result.add_issue(
                rule=ValidationRule.INVALID_RANGE,
                severity=ValidationSeverity.ERROR,
                field=field_name,
                message=(
                    f"Field '{field_name}' is below "
                    f"minimum value {minimum}."
                ),
            )

        if maximum is not None and numeric_value > maximum:
            result.add_issue(
                rule=ValidationRule.INVALID_RANGE,
                severity=ValidationSeverity.ERROR,
                field=field_name,
                message=(
                    f"Field '{field_name}' exceeds "
                    f"maximum value {maximum}."
                ),
            )

        return result
    
    @dataclass(slots=True)
    class DatasetValidator:
        dataset_name: str
        required_columns: List[str]

        statistics: ValidationStatistics = field(init=False)
        seen_keys: Set[str] = field(default_factory=set)

        def __post_init__(self) -> None:
            if self.dataset_name not in IMDB_DATASETS:
                raise ValidationError(
                    f"Unknown dataset '{self.dataset_name}'."
                )

            self.statistics = ValidationStatistics(
                dataset_name=self.dataset_name
            )

        def validate_header(
            self,
            columns: List[str],
        ) -> ValidationResult:
            result = ValidationResult()

            actual = set(columns)
            expected = set(self.required_columns)

            missing = expected - actual
            unexpected = actual - expected

            for column in sorted(missing):
                result.add_issue(
                    rule=ValidationRule.MISSING_COLUMN,
                    severity=ValidationSeverity.ERROR,
                    field=column,
                    message=f"Missing column '{column}'.",
                )

            for column in sorted(unexpected):
                result.add_issue(
                    rule=ValidationRule.UNEXPECTED_COLUMN,
                    severity=ValidationSeverity.WARNING,
                    field=column,
                    message=f"Unexpected column '{column}'.",
                )

            return result

        def validate_duplicate(
            self,
            row: Row,
            key_field: str,
        ) -> ValidationResult:
            result = ValidationResult()

            key = row.get(key_field)

            if key in (None, "", "\\N"):
                return result

            if key in self.seen_keys:
                self.statistics.duplicate_rows += 1

                result.add_issue(
                    rule=ValidationRule.DUPLICATE,
                    severity=ValidationSeverity.ERROR,
                    field=key_field,
                    message=f"Duplicate value '{key}'.",
                )

                return result

            self.seen_keys.add(str(key))

            return result

        def validate_row(
            self,
            row: Row,
        ) -> ValidationResult:
            result = ValidationResult()

            required_result = validate_required_fields(
                row,
                self.required_columns,
            )

            null_result = validate_null_values(
                row,
                self.required_columns,
            )

            empty_result = validate_empty_values(
                row,
                self.required_columns,
            )

            result.issues.extend(required_result.issues)
            result.issues.extend(null_result.issues)
            result.issues.extend(empty_result.issues)

            if any(
                issue.severity == ValidationSeverity.ERROR
                for issue in result.issues
            ):
                result.status = ValidationStatus.INVALID

            return result

        def update_statistics(
            self,
            result: ValidationResult,
        ) -> None:
            self.statistics.rows_processed += 1

            if result.is_valid:
                self.statistics.valid_rows += 1
            else:
                self.statistics.invalid_rows += 1

            for issue in result.issues:
                match issue.rule:
                    case ValidationRule.REQUIRED_FIELD:
                        self.statistics.missing_field_errors += 1

                    case ValidationRule.NULL_VALUE:
                        self.statistics.null_value_errors += 1

                    case ValidationRule.INVALID_TYPE:
                        self.statistics.type_errors += 1

                    case ValidationRule.INVALID_RANGE:
                        self.statistics.range_errors += 1

        def finalize(self) -> ValidationStatistics:
            self.statistics.finish()
            return self.statistics

        def summary(self) -> Dict[str, Any]:
            return {
                "dataset": self.statistics.dataset_name,
                "rows_processed": self.statistics.rows_processed,
                "valid_rows": self.statistics.valid_rows,
                "invalid_rows": self.statistics.invalid_rows,
                "duplicate_rows": self.statistics.duplicate_rows,
                "total_errors": self.statistics.total_errors,
                "validation_rate": self.statistics.validation_rate,
                "started_at": self.statistics.started_at,
                "finished_at": self.statistics.finished_at,
            }
        
class ValidationEngine:
    def __init__(
        self,
        validator: DatasetValidator,
        invalid_rows_path: Optional[Path] = None,
        progress_interval: int = 100_000,
    ) -> None:
        self.validator = validator
        self.invalid_rows_path = invalid_rows_path
        self.progress_interval = progress_interval

        self._writer: Optional[csv.DictWriter] = None
        self._invalid_file = None

    def __enter__(self) -> "ValidationEngine":
        if self.invalid_rows_path is not None:
            self.invalid_rows_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self._invalid_file = open(
                self.invalid_rows_path,
                "w",
                encoding="utf-8",
                newline="",
            )

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        if self._invalid_file:
            self._invalid_file.close()

    def _write_invalid_row(
        self,
        row: Row,
        result: ValidationResult,
    ) -> None:
        if self._invalid_file is None:
            return

        record = dict(row)
        record["validation_errors"] = " | ".join(
            issue.message for issue in result.issues
        )

        if self._writer is None:
            self._writer = csv.DictWriter(
                self._invalid_file,
                fieldnames=list(record.keys()),
            )
            self._writer.writeheader()

        self._writer.writerow(record)

    def _log_progress(self) -> None:
        processed = self.validator.statistics.rows_processed

        if (
            processed > 0
            and processed % self.progress_interval == 0
        ):
            logger.info(
                "%s: validated %,d rows (%.2f%% valid)",
                self.validator.dataset_name,
                processed,
                self.validator.statistics.validation_rate,
            )

    def validate_chunk(
        self,
        chunk: RowBatch,
        duplicate_key: Optional[str] = None,
    ) -> RowBatch:
        valid_rows: RowBatch = []

        for row in chunk:
            result = self.validator.validate_row(row)

            if duplicate_key:
                duplicate_result = (
                    self.validator.validate_duplicate(
                        row,
                        duplicate_key,
                    )
                )

                result.issues.extend(
                    duplicate_result.issues
                )

                if duplicate_result.has_errors:
                    result.status = ValidationStatus.INVALID

            self.validator.update_statistics(result)

            if result.is_valid:
                valid_rows.append(row)
            else:
                self._write_invalid_row(
                    row,
                    result,
                )

            self._log_progress()

        return valid_rows

    def validate_stream(
        self,
        chunks: ChunkIterator,
        duplicate_key: Optional[str] = None,
    ) -> Generator[RowBatch, None, None]:
        for chunk in chunks:
            validated = self.validate_chunk(
                chunk=chunk,
                duplicate_key=duplicate_key,
            )

            if validated:
                yield validated

    def finalize(self) -> ValidationStatistics:
        stats = self.validator.finalize()

        logger.info(
            (
                "%s validation completed | "
                "Processed: %,d | "
                "Valid: %,d | "
                "Invalid: %,d | "
                "Duplicates: %,d | "
                "Success Rate: %.2f%%"
            ),
            stats.dataset_name,
            stats.rows_processed,
            stats.valid_rows,
            stats.invalid_rows,
            stats.duplicate_rows,
            stats.validation_rate,
        )

        return stats
    
    class IMDbValidator:
        def __init__(
            self,
            dataset_name: str,
            required_columns: List[str],
            duplicate_key: Optional[str] = None,
            invalid_rows_path: Optional[Path] = None,
            progress_interval: int = 100_000,
        ) -> None:
            self.validator = DatasetValidator(
                dataset_name=dataset_name,
                required_columns=required_columns,
            )

            self.engine = ValidationEngine(
                validator=self.validator,
                invalid_rows_path=invalid_rows_path,
                progress_interval=progress_interval,
            )

            self.duplicate_key = duplicate_key

        def validate(
            self,
            chunks: ChunkIterator,
        ) -> Generator[RowBatch, None, None]:
            with self.engine:
                yield from self.engine.validate_stream(
                    chunks=chunks,
                    duplicate_key=self.duplicate_key,
                )

        def statistics(self) -> ValidationStatistics:
            return self.engine.finalize()

        def summary(self) -> Dict[str, Any]:
            return self.validator.summary()


    def validate_dataset(
        dataset_name: str,
        chunks: ChunkIterator,
        required_columns: List[str],
        duplicate_key: Optional[str] = None,
        invalid_rows_path: Optional[Path] = None,
        progress_interval: int = 100_000,
    ) -> tuple[Generator[RowBatch, None, None], IMDbValidator]:
        validator = IMDbValidator(
            dataset_name=dataset_name,
            required_columns=required_columns,
            duplicate_key=duplicate_key,
            invalid_rows_path=invalid_rows_path,
            progress_interval=progress_interval,
        )

        return (
            validator.validate(chunks),
            validator,
        )


    def validate_single_row(
        row: Row,
        required_fields: List[str],
    ) -> ValidationResult:
        validator = DatasetValidator(
            dataset_name="manual",
            required_columns=required_fields,
        )

        return validator.validate_row(row)


    def create_validator(
        dataset_name: str,
        required_columns: List[str],
        duplicate_key: Optional[str] = None,
        invalid_rows_path: Optional[Path] = None,
    ) -> IMDbValidator:
        return IMDbValidator(
            dataset_name=dataset_name,
            required_columns=required_columns,
            duplicate_key=duplicate_key,
            invalid_rows_path=invalid_rows_path,
        )


    __all__ = [
        "ValidationError",
        "ValidationSeverity",
        "ValidationStatus",
        "ValidationRule",
        "ValidationIssue",
        "ValidationResult",
        "ValidationStatistics",
        "DatasetValidator",
        "ValidationEngine",
        "IMDbValidator",
        "validate_required_fields",
        "validate_null_values",
        "validate_empty_values",
        "validate_type",
        "validate_range",
        "validate_dataset",
        "validate_single_row",
        "create_validator",
    ]