from __future__ import annotations

from fastapi import FastAPI

from backend.api.movies import router as movies_router
from backend.services.database import get_database_url
import psycopg


app = FastAPI(
    title="CineMind AI API",
    description="AI-powered movie search and recommendation API.",
    version="1.0.0",
)


app.include_router(movies_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    try:
        with psycopg.connect(get_database_url()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return {
            "status": "healthy",
            "database": "connected",
        }

    except Exception:
        return {
            "status": "unhealthy",
            "database": "disconnected",
        }