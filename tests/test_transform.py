import pytest

from etl.transform import (
    DatasetType,
    IMDbRowTransformer,
    TransformResult,
    clean_text,
    normalize_genres,
    normalize_professions,
    normalize_known_titles,
    to_int,
    to_float,
    to_bool,
    to_year,
    map_title_type,
    map_person_role,
    parse_character_names,
)


# ---------------------------------------------------------------------------
# Primitive normalization
# ---------------------------------------------------------------------------

def test_clean_text():
    assert clean_text("  hello world  ") == "hello world"
    assert clean_text("\\N") is None
    assert clean_text(None) is None


def test_numeric_conversion():
    assert to_int("123") == 123
    assert to_int("\\N") is None
    assert to_float("8.5") == 8.5
    assert to_float("\\N") is None


def test_boolean_conversion():
    assert to_bool("1") is True
    assert to_bool("0") is False
    assert to_bool("\\N") is None


def test_year_conversion():
    assert to_year("2024") == 2024
    assert to_year("\\N") is None


# ---------------------------------------------------------------------------
# IMDb list normalization
# ---------------------------------------------------------------------------

def test_genre_normalization():
    assert normalize_genres("Action,Drama") == ["Action", "Drama"]
    assert normalize_genres("\\N") == []


def test_profession_normalization():
    result = normalize_professions("actor,director,writer")
    assert result == ["actor", "director", "writer"]


def test_known_titles_normalization():
    result = normalize_known_titles("tt0000001,tt0000002")
    assert result == ["tt0000001", "tt0000002"]


def test_character_names():
    result = parse_character_names('[\"John\", \"Mike\"]')
    assert result is not None


# ---------------------------------------------------------------------------
# IMDb enum mappings
# ---------------------------------------------------------------------------

def test_title_type_mapping():
    assert map_title_type("movie") == "movie"
    assert map_title_type("short") == "short"
    assert isinstance(map_title_type("unknown_type"), str)


def test_person_role_mapping():
    assert map_person_role("actor") == "actor"
    assert map_person_role("actress") == "actor"
    assert isinstance(map_person_role("unknown_role"), str)


# ---------------------------------------------------------------------------
# Full row transformations
# ---------------------------------------------------------------------------

def test_title_basics_transformation():
    row = {
        "tconst": "tt1234567",
        "titleType": "movie",
        "primaryTitle": "  Test Movie  ",
        "originalTitle": "Test Movie",
        "isAdult": "0",
        "startYear": "2024",
        "endYear": "\\N",
        "runtimeMinutes": "120",
        "genres": "Action,Drama",
    }

    result = IMDbRowTransformer.transform_title_basics(row)

    assert isinstance(result, TransformResult)
    assert result.success

    records = result.records

    assert "movies" in records
    assert records["movies"][0]["imdb_id"] == "tt1234567"
    assert records["movies"][0]["title"] == "Test Movie"
    assert records["movies"][0]["release_year"] == 2024


def test_title_ratings_transformation():
    row = {
        "tconst": "tt1234567",
        "averageRating": "8.5",
        "numVotes": "10000",
    }

    result = IMDbRowTransformer.transform_title_ratings(row)

    assert result.success
    assert "movie_ratings" in result.records

    rating = result.records["movie_ratings"][0]

    assert rating["imdb_rating"] == 8.5
    assert rating["imdb_vote_count"] == 10000


def test_name_basics_transformation():
    row = {
        "nconst": "nm1234567",
        "primaryName": "Test Person",
        "birthYear": "1980",
        "deathYear": "\\N",
        "primaryProfession": "actor,director",
        "knownForTitles": "tt1234567",
    }

    result = IMDbRowTransformer.transform_name_basics(row)

    assert result.success
    assert "people" in result.records

    person = result.records["people"][0]

    assert person["imdb_person_id"] == "nm1234567"
    assert person["full_name"] == "Test Person"
    assert person["birth_year"] == 1980


def test_title_principals_transformation():
    row = {
        "tconst": "tt1234567",
        "ordering": "1",
        "nconst": "nm1234567",
        "category": "actor",
        "job": "\\N",
        "characters": "[\"John\"]",
    }

    result = IMDbRowTransformer.transform_title_principals(row)

    assert result.success
    assert "movie_people" in result.records


def test_title_crew_transformation():
    row = {
        "tconst": "tt1234567",
        "directors": "nm1234567",
        "writers": "nm7654321",
    }

    result = IMDbRowTransformer.transform_title_crew(row)

    assert result.success


# ---------------------------------------------------------------------------
# PostgreSQL record building
# ---------------------------------------------------------------------------

def test_transform_to_postgresql():
    transformer = IMDbRowTransformer()

    row = {
        "tconst": "tt1234567",
        "titleType": "movie",
        "primaryTitle": "Test Movie",
        "originalTitle": "Test Movie",
        "isAdult": "0",
        "startYear": "2024",
        "endYear": "\\N",
        "runtimeMinutes": "120",
        "genres": "Action,Drama",
    }

    result = transformer.transform_to_postgresql(
        DatasetType.TITLE_BASICS,
        row,
    )

    assert result.success
    assert "movies" in result.records