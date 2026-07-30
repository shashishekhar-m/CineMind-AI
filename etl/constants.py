from pathlib import Path

from config import settings

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