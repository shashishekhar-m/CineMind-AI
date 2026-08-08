from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional, Set, TypeAlias

from etl.constants import (
    DEFAULT_PERSON_ROLE,
    DEFAULT_TITLE_TYPE,
    NULL_VALUES,
    PERSON_ROLE_MAP,
    SUPPORTED_TITLE_TYPES,
    TITLE_TYPE_MAP,
)
from etl.logger import get_logger

logger = get_logger(__name__)

Row: TypeAlias = Dict[str, Any]
Record: TypeAlias = Dict[str, Any]
RecordBatch: TypeAlias = List[Record]
BridgeRecord: TypeAlias = Dict[str, Any]


class TransformError(Exception):
    pass


class DatasetType(str, Enum):
    TITLE_BASICS = "title.basics"
    TITLE_RATINGS = "title.ratings"
    TITLE_CREW = "title.crew"
    TITLE_PRINCIPALS = "title.principals"
    NAME_BASICS = "name.basics"
    TITLE_AKAS = "title.akas"
    TITLE_EPISODE = "title.episode"


@dataclass(slots=True)
class TransformResult:
    dataset: DatasetType
    record: Optional[Record] = None
    bridge_records: Dict[str, RecordBatch] = field(default_factory=dict)
    skipped: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.skipped and not self.errors


@dataclass(slots=True)
class TransformStatistics:
    dataset: DatasetType

    rows_processed: int = 0
    rows_transformed: int = 0
    rows_skipped: int = 0
    rows_failed: int = 0

    bridge_records_created: int = 0

    unique_movies: Set[str] = field(default_factory=set)
    unique_people: Set[str] = field(default_factory=set)

    @property
    def success_rate(self) -> float:
        if self.rows_processed == 0:
            return 0.0

        return round(
            (self.rows_transformed / self.rows_processed) * 100,
            2,
        )


def is_null(value: Any) -> bool:
    if value is None:
        return True

    if isinstance(value, str):
        return value.strip() in NULL_VALUES

    return False


def clean_text(value: Any) -> Optional[str]:
    if is_null(value):
        return None

    text = str(value).strip()

    return text or None


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def safe_strip(value: Any) -> Optional[str]:
    text = clean_text(value)

    if text is None:
        return None

    return normalize_whitespace(text)


def split_pipe(value: Any) -> List[str]:
    text = clean_text(value)

    if text is None:
        return []

    return [
        item.strip()
        for item in text.split("|")
        if item.strip()
    ]


def split_comma(value: Any) -> List[str]:
    text = clean_text(value)

    if text is None:
        return []

    return [
        item.strip()
        for item in text.split(",")
        if item.strip()
    ]

def to_int(value: Any) -> Optional[int]:
    text = clean_text(value)

    if text is None:
        return None

    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> Optional[float]:
    text = clean_text(value)

    if text is None:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def to_bool(value: Any) -> Optional[bool]:
    text = clean_text(value)

    if text is None:
        return None

    text = text.lower()

    if text in {"1", "true", "t", "yes", "y"}:
        return True

    if text in {"0", "false", "f", "no", "n"}:
        return False

    return None


def to_year(value: Any) -> Optional[int]:
    year = to_int(value)

    if year is None:
        return None

    if year < 1800 or year > 2100:
        return None

    return year


def to_date(
    year: Any,
    month: int = 1,
    day: int = 1,
) -> Optional[date]:
    parsed_year = to_year(year)

    if parsed_year is None:
        return None

    try:
        return date(parsed_year, month, day)
    except ValueError:
        return None


def clean_string(value: Any) -> Optional[str]:
    text = safe_strip(value)

    if text is None:
        return None

    return text


def clean_title(value: Any) -> Optional[str]:
    text = clean_string(value)

    if text is None:
        return None

    return text.title()


def clean_sentence(value: Any) -> Optional[str]:
    text = clean_string(value)

    if text is None:
        return None

    return text


def parse_csv_list(value: Any) -> List[str]:
    text = clean_string(value)

    if text is None:
        return []

    return [
        item.strip()
        for item in text.split(",")
        if item.strip()
    ]


def parse_pipe_list(value: Any) -> List[str]:
    text = clean_string(value)

    if text is None:
        return []

    return [
        item.strip()
        for item in text.split("|")
        if item.strip()
    ]


def unique_list(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []

    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)

    return result


def normalize_genres(value: Any) -> List[str]:
    return unique_list(parse_csv_list(value))


def normalize_professions(value: Any) -> List[str]:
    return unique_list(parse_csv_list(value))


def normalize_known_titles(value: Any) -> List[str]:
    return unique_list(parse_csv_list(value))


def map_title_type(imdb_title_type: Optional[str]) -> str:
    if imdb_title_type is None:
        return DEFAULT_TITLE_TYPE

    return TITLE_TYPE_MAP.get(imdb_title_type, DEFAULT_TITLE_TYPE)


def map_person_role(imdb_category: Optional[str]) -> str:
    if imdb_category is None:
        return DEFAULT_PERSON_ROLE

    return PERSON_ROLE_MAP.get(imdb_category, DEFAULT_PERSON_ROLE)


def parse_character_names(value: Any) -> Optional[str]:
    """IMDb serializes title.principals.characters as a JSON array string,
    e.g. '["Andy Dufresne"]'. Returns a clean comma-joined string, or
    None if there's nothing usable.
    """

    text = clean_string(value)

    if text is None:
        return None

    try:
        names = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text

    if not isinstance(names, list):
        return text

    cleaned = [str(name).strip() for name in names if str(name).strip()]

    return ", ".join(cleaned) if cleaned else None

class IMDbRowTransformer:
    @staticmethod
    def transform_title_basics(row: Row) -> TransformResult:
        imdb_id = clean_string(row.get("tconst"))

        if imdb_id is None:
            return TransformResult(
                dataset=DatasetType.TITLE_BASICS,
                skipped=True,
                errors=["Missing IMDb title ID"],
            )

        title_type = clean_string(row.get("titleType"))

        if title_type is not None and title_type not in SUPPORTED_TITLE_TYPES:
            return TransformResult(
                dataset=DatasetType.TITLE_BASICS,
                skipped=True,
                errors=[f"Unsupported title type '{title_type}'"],
            )

        primary_title = clean_string(row.get("primaryTitle"))
        release_year = to_year(row.get("startYear"))

        # movies.title and movies.release_year are NOT NULL in
        # database/schema.sql; rows missing either cannot be loaded.
        if primary_title is None:
            return TransformResult(
                dataset=DatasetType.TITLE_BASICS,
                skipped=True,
                errors=["Missing primary title"],
            )

        if release_year is None:
            return TransformResult(
                dataset=DatasetType.TITLE_BASICS,
                skipped=True,
                errors=["Missing or invalid release year"],
            )

        genres = normalize_genres(row.get("genres"))

        movie = {
            "imdb_id": imdb_id,
            "title_type": title_type,
            "primary_title": primary_title,
            "original_title": clean_string(row.get("originalTitle")),
            "is_adult": to_bool(row.get("isAdult")),
            "release_year": release_year,
            "end_year": to_year(row.get("endYear")),
            "runtime_minutes": to_int(row.get("runtimeMinutes")),
        }

        return TransformResult(
            dataset=DatasetType.TITLE_BASICS,
            record=movie,
            bridge_records={
                "genres": [
                    {"genre_name": genre}
                    for genre in genres
                ]
            },
        )

    @staticmethod
    def transform_title_ratings(row: Row) -> TransformResult:
        imdb_id = clean_string(row.get("tconst"))

        if imdb_id is None:
            return TransformResult(
                dataset=DatasetType.TITLE_RATINGS,
                skipped=True,
                errors=["Missing IMDb title ID"],
            )

        rating = {
            "imdb_id": imdb_id,
            "imdb_rating": to_float(row.get("averageRating")),
            "vote_count": to_int(row.get("numVotes")),
        }

        return TransformResult(
            dataset=DatasetType.TITLE_RATINGS,
            record=rating,
        )

    @staticmethod
    def transform_name_basics(row: Row) -> TransformResult:
        imdb_person_id = clean_string(row.get("nconst"))

        if imdb_person_id is None:
            return TransformResult(
                dataset=DatasetType.NAME_BASICS,
                skipped=True,
                errors=["Missing IMDb person ID"],
            )

        professions = normalize_professions(
            row.get("primaryProfession")
        )

        known_titles = normalize_known_titles(
            row.get("knownForTitles")
        )

        full_name = clean_string(row.get("primaryName"))

        # people.full_name is NOT NULL in database/schema.sql.
        if full_name is None:
            return TransformResult(
                dataset=DatasetType.NAME_BASICS,
                skipped=True,
                errors=["Missing full name"],
            )

        person = {
            "imdb_person_id": imdb_person_id,
            "full_name": full_name,
            "birth_year": to_year(row.get("birthYear")),
            "death_year": to_year(row.get("deathYear")),
            "primary_profession": (
                ",".join(professions) if professions else None
            ),
            "known_for_titles": (
                ",".join(known_titles) if known_titles else None
            ),
        }

        return TransformResult(
            dataset=DatasetType.NAME_BASICS,
            record=person,
        )

    @staticmethod
    def transform_title_principals(row: Row) -> TransformResult:
        imdb_id = clean_string(row.get("tconst"))
        imdb_person_id = clean_string(row.get("nconst"))

        if imdb_id is None or imdb_person_id is None:
            return TransformResult(
                dataset=DatasetType.TITLE_PRINCIPALS,
                skipped=True,
                errors=["Missing relationship identifiers"],
            )

        principal = {
            "imdb_id": imdb_id,
            "imdb_person_id": imdb_person_id,
            "ordering": to_int(row.get("ordering")),
            "category": clean_string(row.get("category")),
            "job": clean_string(row.get("job")),
            "characters": parse_character_names(row.get("characters")),
        }

        return TransformResult(
            dataset=DatasetType.TITLE_PRINCIPALS,
            record=principal,
        )

    @staticmethod
    def transform_title_crew(row: Row) -> TransformResult:
        imdb_id = clean_string(row.get("tconst"))

        if imdb_id is None:
            return TransformResult(
                dataset=DatasetType.TITLE_CREW,
                skipped=True,
                errors=["Missing IMDb title ID"],
            )

        directors = normalize_known_titles(row.get("directors"))
        writers = normalize_known_titles(row.get("writers"))

        return TransformResult(
            dataset=DatasetType.TITLE_CREW,
            record={
                "imdb_id": imdb_id,
            },
            bridge_records={
                "directors": [
                    {
                        "imdb_id": imdb_id,
                        "imdb_person_id": person_id,
                        "role": "director",
                    }
                    for person_id in directors
                ],
                "writers": [
                    {
                        "imdb_id": imdb_id,
                        "imdb_person_id": person_id,
                        "role": "writer",
                    }
                    for person_id in writers
                ],
            },
        )
    
    @staticmethod
    def normalize_movie_genres(
        imdb_id: str,
        genres: List[str],
    ) -> RecordBatch:
        return [
            {
                "imdb_id": imdb_id,
                "genre_name": genre,
            }
            for genre in unique_list(genres)
        ]
    
    @staticmethod
    def normalize_movie_languages(
        imdb_id: str,
        language_code: Optional[str],
    ) -> RecordBatch:
        if not language_code:
            return []

        return [
            {
                "imdb_id": imdb_id,
                "iso_639_1": language_code.lower(),
                "is_original": True,
            }
        ]
    
    @staticmethod
    def normalize_movie_people(
        principals: RecordBatch,
    ) -> RecordBatch:
        records: RecordBatch = []

        for principal in principals:
            records.append(
                {
                    "imdb_id": principal["imdb_id"],
                    "imdb_person_id": principal["imdb_person_id"],
                    "role": map_person_role(principal.get("category")),
                    "job_title": principal.get("job"),
                    "character_name": principal.get("characters"),
                    "billing_order": principal.get("ordering"),
                }
            )

        return records
    
    @staticmethod
    def normalize_movie_crew(
        directors: RecordBatch,
        writers: RecordBatch,
    ) -> RecordBatch:
        return directors + writers
    
    @staticmethod
    def build_movie_record(
        movie: Record,
    ) -> Record:
        return {
            "imdb_id": movie.get("imdb_id"),
            "title": movie.get("primary_title"),
            "original_title": movie.get("original_title"),
            "title_type": map_title_type(movie.get("title_type")),
            "release_year": movie.get("release_year"),
            "end_year": movie.get("end_year"),
            "runtime_minutes": movie.get("runtime_minutes"),
            "original_language": None,
            "is_adult": movie.get("is_adult", False),
        }
    
    @staticmethod
    def build_movie_rating_record(
        rating: Record,
    ) -> Record:
        return {
            "imdb_id": rating.get("imdb_id"),
            "imdb_rating": rating.get("imdb_rating"),
            "imdb_vote_count": rating.get("vote_count"),
        }
    
    @staticmethod
    def build_person_record(
        person: Record,
    ) -> Record:
        return {
            "imdb_person_id": person.get("imdb_person_id"),
            "full_name": person.get("full_name"),
            "birth_year": person.get("birth_year"),
            "death_year": person.get("death_year"),
            "primary_profession": person.get("primary_profession"),
            "known_for_titles": person.get("known_for_titles"),
        }
    
    @staticmethod
    def build_postgresql_records(
        result: TransformResult,
    ) -> Dict[str, RecordBatch]:
        output: Dict[str, RecordBatch] = {}

        if result.dataset == DatasetType.TITLE_BASICS:
            movie = IMDbRowTransformer.build_movie_record(result.record or {})

            output["movies"] = [movie]
            output["genres"] = result.bridge_records.get("genres", [])
            output["movie_genres"] = IMDbRowTransformer.normalize_movie_genres(
                movie["imdb_id"],
                [
                    genre["genre_name"]
                    for genre in result.bridge_records.get("genres", [])
                ],
            )
            output["movie_languages"] = IMDbRowTransformer.normalize_movie_languages(
                movie["imdb_id"],
                movie.get("original_language"),
            )

        elif result.dataset == DatasetType.TITLE_RATINGS:
            output["movie_ratings"] = [
                IMDbRowTransformer.build_movie_rating_record(result.record or {})
            ]

        elif result.dataset == DatasetType.NAME_BASICS:
            output["people"] = [
                IMDbRowTransformer.build_person_record(result.record or {})
            ]

        elif result.dataset == DatasetType.TITLE_PRINCIPALS:
            output["movie_people"] = IMDbRowTransformer.normalize_movie_people(
                [result.record or {}]
            )

        elif result.dataset == DatasetType.TITLE_CREW:
            output["movie_people"] = IMDbRowTransformer.normalize_movie_crew(
                result.bridge_records.get("directors", []),
                result.bridge_records.get("writers", []),
            )

        return output
    
class IMDbTransformer:
    def __init__(self) -> None:
        self.statistics: Dict[DatasetType, TransformStatistics] = {
            dataset: TransformStatistics(dataset=dataset)
            for dataset in DatasetType
        }

    def transform(
        self,
        dataset: DatasetType,
        row: Row,
    ) -> TransformResult:
        statistics = self.statistics[dataset]
        statistics.rows_processed += 1

        try:
            if dataset == DatasetType.TITLE_BASICS:
                result = IMDbRowTransformer.transform_title_basics(row)

            elif dataset == DatasetType.TITLE_RATINGS:
                result = IMDbRowTransformer.transform_title_ratings(row)

            elif dataset == DatasetType.NAME_BASICS:
                result = IMDbRowTransformer.transform_name_basics(row)

            elif dataset == DatasetType.TITLE_PRINCIPALS:
                result = IMDbRowTransformer.transform_title_principals(row)

            elif dataset == DatasetType.TITLE_CREW:
                result = IMDbRowTransformer.transform_title_crew(row)

            else:
                raise TransformError(
                    f"Unsupported dataset: {dataset}"
                )

            if result.skipped:
                statistics.rows_skipped += 1

            elif result.errors:
                statistics.rows_failed += 1

            else:
                statistics.rows_transformed += 1

                if result.record:
                    imdb_id = result.record.get("imdb_id")
                    imdb_person_id = result.record.get("imdb_person_id")

                    if imdb_id:
                        statistics.unique_movies.add(imdb_id)

                    if imdb_person_id:
                        statistics.unique_people.add(imdb_person_id)

                statistics.bridge_records_created += sum(
                    len(records)
                    for records in result.bridge_records.values()
                )

            return result

        except Exception as exc:
            statistics.rows_failed += 1

            logger.exception(
                "Transformation failed for dataset %s",
                dataset.value,
            )

            return TransformResult(
                dataset=dataset,
                skipped=True,
                errors=[str(exc)],
            )

    def transform_to_postgresql(
        self,
        dataset: DatasetType,
        row: Row,
    ) -> Dict[str, RecordBatch]:
        result = self.transform(dataset, row)

        if result.skipped or result.errors:
            return {}

        return IMDbRowTransformer.build_postgresql_records(result)

    def get_statistics(
        self,
        dataset: Optional[DatasetType] = None,
    ) -> Any:
        if dataset is not None:
            return self.statistics[dataset]

        return self.statistics

    def reset_statistics(self) -> None:
        self.statistics = {
            dataset: TransformStatistics(dataset=dataset)
            for dataset in DatasetType
        }


transformer = IMDbTransformer()

__all__ = [
    "DatasetType",
    "TransformError",
    "TransformResult",
    "TransformStatistics",
    "IMDbRowTransformer",
    "IMDbTransformer",
    "transformer",
]