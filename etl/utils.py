import gzip
import time
from pathlib import Path
from typing import Generator

import pandas as pd

from constants import CSV_SEPARATOR, NULL_VALUES


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def timer(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"{func.__name__} completed in {end-start:.2f} seconds")
        return result

    return wrapper


def read_tsv_in_chunks(
    file_path: Path,
    chunk_size: int,
) -> Generator[pd.DataFrame, None, None]:

    with gzip.open(file_path, "rt", encoding="utf-8") as file:
        reader = pd.read_csv(
            file,
            sep=CSV_SEPARATOR,
            na_values=list(NULL_VALUES),
            keep_default_na=False,
            chunksize=chunk_size,
            low_memory=False,
        )

        for chunk in reader:
            yield chunk


def normalize_null(value):
    if value in NULL_VALUES:
        return None
    return value


def convert_runtime(runtime):
    if runtime is None:
        return None

    try:
        return int(runtime)
    except Exception:
        return None


def convert_year(year):
    if year is None:
        return None

    try:
        return int(year)
    except Exception:
        return None


def convert_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def convert_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return None