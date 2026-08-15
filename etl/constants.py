from pathlib import Path

from etl.config import settings

ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT_DIR / "data"

RAW_DATA_DIR = DATA_DIR / "raw"

PROCESSED_DATA_DIR = DATA_DIR / "processed"

LOG_DIR = DATA_DIR / "logs"

IMDB_DATASET_FILES = {
    "title_basics": "title.basics.tsv.gz",
    "title_ratings": "title.ratings.tsv.gz",
    "title_principals": "title.principals.tsv.gz",
    "title_crew": "title.crew.tsv.gz",
    "title_episode": "title.episode.tsv.gz",
    "title_akas": "title.akas.tsv.gz",
    "name_basics": "name.basics.tsv.gz",
}

# extract.py / validate.py depend on this exact name.
IMDB_DATASETS = IMDB_DATASET_FILES

# Required TSV header columns per IMDb dataset, used by validate.py and
# pipeline.py. Only datasets currently implemented by transform.py are
# listed here (title_akas / title_episode are intentionally out of scope
# for the current ETL foundation milestone).
IMDB_REQUIRED_COLUMNS = {
    "title_basics": [
        "tconst",
        "titleType",
        "primaryTitle",
        "originalTitle",
        "isAdult",
    ],
    "title_ratings": [
        "tconst",
        "averageRating",
        "numVotes",
    ],
    "name_basics": [
        "nconst",
        "primaryName",
    ],
    "title_principals": [
        "tconst",
        "ordering",
        "nconst",
        "category",
    ],
    "title_crew": [
        "tconst",
    ],
}

# The natural/composite key used to detect duplicate rows per dataset,
# passed to ValidationEngine.validate_chunk(duplicate_key=...).
# None means duplicates are not meaningfully detectable on a single column
# (e.g. bridge datasets keyed by a composite relationship).
IMDB_DUPLICATE_KEYS = {
    "title_basics": "tconst",
    "title_ratings": "tconst",
    "name_basics": "nconst",
    "title_principals": None,
    "title_crew": "tconst",
}

# IMDb titleType -> database title_type_enum (database/schema.sql).
# Unmapped values fall back to "movie", matching the column's DB default.
TITLE_TYPE_MAP = {
    "movie": "movie",
    "tvSeries": "tv_series",
    "tvEpisode": "tv_episode",
    "tvMovie": "tv_movie",
    "short": "short",
    "tvShort": "tv_short",
    "tvSpecial": "tv_special",
    "tvMiniSeries": "tv_mini_series",
    "video": "video",
    "videoGame": "video_game",
}

DEFAULT_TITLE_TYPE = "movie"

# IMDb title.principals `category` -> database person_role_enum
# (database/schema.sql). Unmapped values fall back to "miscellaneous",
# which exists in the enum precisely for this purpose.
PERSON_ROLE_MAP = {
    "actor": "actor",
    "actress": "actor",
    "director": "director",
    "writer": "writer",
    "producer": "producer",
    "composer": "composer",
    "cinematographer": "cinematographer",
    "editor": "editor",
    "self": "self",
    "archive_footage": "archive_footage",
    "archive_sound": "archive_sound",
    "production_designer": "miscellaneous",
    "casting_director": "casting",
}

DEFAULT_PERSON_ROLE = "miscellaneous"

SUPPORTED_TITLE_TYPES = {
    "movie",
    "tvSeries",
    "tvMiniSeries",
    "tvMovie",
    "tvSpecial",
}

ADULT_FLAG = {
    "0": False,
    "1": True,
}

DEFAULT_BATCH_SIZE = settings.batch_size

# extract.py's StreamingTSVReader/ProgressTracker default chunk size.
# Master prompt (docs/00_MASTER_PROMPT.md) mandates a default of 5000;
# BATCH_SIZE remains independently configurable via the environment for
# the database loader.
CHUNK_SIZE = settings.batch_size

# Encodings attempted, in order, when auto-detecting an IMDb TSV file's
# text encoding (extract.py: detect_encoding).
ENCODING_CANDIDATES = (
    "utf-8",
    "utf-8-sig",
    "latin-1",
    "cp1252",
)

DATE_FORMAT = "%Y-%m-%d"

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

TEXT_ENCODING = "utf-8"

CSV_SEPARATOR = "\t"

NULL_VALUES = {
    "\\N",
    "",
    None,
}

DEFAULT_LANGUAGE = "en"

DEFAULT_TIMEZONE = "UTC"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"

EMBEDDING_DIMENSION = 384

TMDB_API_BASE_URL = "https://api.themoviedb.org/3"

TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"

TMDB_POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"

YOUTUBE_BASE_URL = "https://www.youtube.com/watch?v="

API_TIMEOUT = 30

MAX_RETRY_ATTEMPTS = 3

RETRY_BACKOFF_SECONDS = 5