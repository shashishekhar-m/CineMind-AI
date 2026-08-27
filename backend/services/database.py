from __future__ import annotations

import os
from collections.abc import Generator

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return database_url


def get_connection() -> psycopg.Connection:
    return psycopg.connect(get_database_url())


def get_db() -> Generator[psycopg.Connection, None, None]:
    conn = get_connection()

    try:
        yield conn
    finally:
        conn.close()
