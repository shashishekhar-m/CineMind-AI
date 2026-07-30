BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE SCHEMA IF NOT EXISTS cinemind;

SET search_path TO cinemind, public;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS
$$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TYPE title_type_enum AS ENUM (
    'movie',
    'tv_series',
    'tv_episode',
    'tv_movie',
    'short',
    'tv_short',
    'tv_special',
    'tv_mini_series',
    'video',
    'video_game',
    'podcast',
    'podcast_episode'
);

CREATE TYPE content_status_enum AS ENUM (
    'rumored',
    'planned',
    'in_production',
    'post_production',
    'released',
    'cancelled'
);

CREATE TYPE metadata_source_enum AS ENUM (
    'IMDb',
    'TMDb',
    'OMDb',
    'YouTube'
);

CREATE TABLE metadata_sources
(
    source_id           BIGSERIAL PRIMARY KEY,

    source_name         metadata_source_enum NOT NULL UNIQUE,

    dataset_version     TEXT,

    dataset_url         TEXT,

    description         TEXT,

    download_date       TIMESTAMPTZ,

    last_sync           TIMESTAMPTZ,

    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_download_before_sync
        CHECK (
            last_sync IS NULL
            OR
            download_date IS NULL
            OR
            last_sync >= download_date
        )
);

CREATE TRIGGER trg_metadata_sources_updated_at
BEFORE UPDATE
ON metadata_sources
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE metadata_sources IS
'Tracks external data providers used by the ETL pipeline.';

COMMENT ON COLUMN metadata_sources.source_id IS
'Internal primary key.';

COMMENT ON COLUMN metadata_sources.source_name IS
'External provider name.';

COMMENT ON COLUMN metadata_sources.dataset_version IS
'Dataset version or release identifier.';

COMMENT ON COLUMN metadata_sources.dataset_url IS
'Original download URL.';

COMMENT ON COLUMN metadata_sources.description IS
'Description of the external source.';

COMMENT ON COLUMN metadata_sources.download_date IS
'Time when the dataset was downloaded.';

COMMENT ON COLUMN metadata_sources.last_sync IS
'Last successful synchronization timestamp.';

COMMENT ON COLUMN metadata_sources.is_active IS
'Whether this data source is currently active.';

COMMENT ON COLUMN metadata_sources.created_at IS
'Record creation timestamp.';

COMMENT ON COLUMN metadata_sources.updated_at IS
'Last modification timestamp.';

CREATE TABLE movies
(
    movie_id                BIGSERIAL PRIMARY KEY,

    imdb_id                 TEXT NOT NULL UNIQUE,
    tmdb_id                 BIGINT UNIQUE,

    slug                    CITEXT UNIQUE,

    title                   TEXT NOT NULL,
    original_title          TEXT,

    title_type              title_type_enum NOT NULL DEFAULT 'movie',

    release_date            DATE,
    release_year            INTEGER NOT NULL,

    end_year                INTEGER,

    runtime_minutes         INTEGER,

    is_adult                BOOLEAN NOT NULL DEFAULT FALSE,

    original_language       VARCHAR(10),

    original_country        VARCHAR(10),

    overview                TEXT,

    tagline                 TEXT,

    status                  content_status_enum DEFAULT 'released',

    poster_url              TEXT,

    backdrop_url            TEXT,

    trailer_key             TEXT,

    homepage_url            TEXT,

    imdb_url                TEXT,

    tmdb_url                TEXT,

    budget                  BIGINT DEFAULT 0,

    revenue                 BIGINT DEFAULT 0,

    popularity              NUMERIC(12,4) DEFAULT 0,

    vote_average            NUMERIC(4,2),

    vote_count              INTEGER DEFAULT 0,

    belongs_to_collection   BOOLEAN NOT NULL DEFAULT FALSE,

    has_video               BOOLEAN NOT NULL DEFAULT FALSE,

    metadata_source_id      BIGINT
        REFERENCES metadata_sources(source_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    last_synced_at          TIMESTAMPTZ,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    deleted_at              TIMESTAMPTZ,

    CONSTRAINT chk_release_year
        CHECK (
            release_year >= 1878
            AND release_year <= 2100
        ),

    CONSTRAINT chk_end_year
        CHECK (
            end_year IS NULL
            OR end_year >= release_year
        ),

    CONSTRAINT chk_runtime
        CHECK (
            runtime_minutes IS NULL
            OR runtime_minutes > 0
        ),

    CONSTRAINT chk_budget
        CHECK (
            budget >= 0
        ),

    CONSTRAINT chk_revenue
        CHECK (
            revenue >= 0
        ),

    CONSTRAINT chk_popularity
        CHECK (
            popularity >= 0
        ),

    CONSTRAINT chk_vote_average
        CHECK (
            vote_average IS NULL
            OR (
                vote_average >= 0
                AND vote_average <= 10
            )
        ),

    CONSTRAINT chk_vote_count
        CHECK (
            vote_count >= 0
        ),

    CONSTRAINT chk_language_code
        CHECK (
            original_language IS NULL
            OR LENGTH(original_language) <= 10
        ),

    CONSTRAINT chk_country_code
        CHECK (
            original_country IS NULL
            OR LENGTH(original_country) <= 10
        ),

    CONSTRAINT chk_deleted_after_created
        CHECK (
            deleted_at IS NULL
            OR deleted_at >= created_at
        ),

    CONSTRAINT chk_last_sync
        CHECK (
            last_synced_at IS NULL
            OR last_synced_at >= created_at
        )
);

CREATE TRIGGER trg_movies_updated_at
BEFORE UPDATE
ON movies
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE movies IS
'Master table storing all movie and TV title metadata enriched from IMDb and TMDb.';

COMMENT ON COLUMN movies.movie_id IS 'Internal primary key.';
COMMENT ON COLUMN movies.imdb_id IS 'IMDb title identifier (tconst).';
COMMENT ON COLUMN movies.tmdb_id IS 'TMDb movie or TV identifier.';
COMMENT ON COLUMN movies.slug IS 'SEO-friendly unique slug.';
COMMENT ON COLUMN movies.title IS 'Primary display title.';
COMMENT ON COLUMN movies.original_title IS 'Original title.';
COMMENT ON COLUMN movies.title_type IS 'IMDb content type.';
COMMENT ON COLUMN movies.release_date IS 'Official release date.';
COMMENT ON COLUMN movies.release_year IS 'Release year.';
COMMENT ON COLUMN movies.end_year IS 'End year for series.';
COMMENT ON COLUMN movies.runtime_minutes IS 'Runtime in minutes.';
COMMENT ON COLUMN movies.is_adult IS 'Adult content flag.';
COMMENT ON COLUMN movies.original_language IS 'Original language code.';
COMMENT ON COLUMN movies.original_country IS 'Primary production country.';
COMMENT ON COLUMN movies.overview IS 'Movie synopsis.';
COMMENT ON COLUMN movies.tagline IS 'Marketing tagline.';
COMMENT ON COLUMN movies.status IS 'Production/release status.';
COMMENT ON COLUMN movies.poster_url IS 'Poster image URL.';
COMMENT ON COLUMN movies.backdrop_url IS 'Backdrop image URL.';
COMMENT ON COLUMN movies.trailer_key IS 'YouTube trailer key.';
COMMENT ON COLUMN movies.homepage_url IS 'Official homepage.';
COMMENT ON COLUMN movies.imdb_url IS 'IMDb webpage.';
COMMENT ON COLUMN movies.tmdb_url IS 'TMDb webpage.';
COMMENT ON COLUMN movies.budget IS 'Production budget.';
COMMENT ON COLUMN movies.revenue IS 'Worldwide revenue.';
COMMENT ON COLUMN movies.popularity IS 'TMDb popularity score.';
COMMENT ON COLUMN movies.vote_average IS 'TMDb average rating.';
COMMENT ON COLUMN movies.vote_count IS 'TMDb vote count.';
COMMENT ON COLUMN movies.belongs_to_collection IS 'Collection membership flag.';
COMMENT ON COLUMN movies.has_video IS 'Trailer/video availability.';
COMMENT ON COLUMN movies.metadata_source_id IS 'Reference to metadata source.';
COMMENT ON COLUMN movies.last_synced_at IS 'Last successful synchronization.';
COMMENT ON COLUMN movies.created_at IS 'Creation timestamp.';
COMMENT ON COLUMN movies.updated_at IS 'Last update timestamp.';
COMMENT ON COLUMN movies.deleted_at IS 'Soft delete timestamp.';

CREATE TABLE movie_ratings
(
    rating_id               BIGSERIAL PRIMARY KEY,

    movie_id                BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    imdb_rating             NUMERIC(3,1),

    imdb_vote_count         INTEGER DEFAULT 0,

    tmdb_rating             NUMERIC(3,1),

    tmdb_vote_count         INTEGER DEFAULT 0,

    rotten_tomatoes_score   SMALLINT,

    metacritic_score        SMALLINT,

    letterboxd_rating       NUMERIC(3,2),

    popularity_score        NUMERIC(12,4) DEFAULT 0,

    weighted_rating         NUMERIC(6,3),

    trending_score          NUMERIC(8,3),

    ranking_score           NUMERIC(8,3),

    last_updated_source     metadata_source_enum,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_movie_rating
        UNIQUE (movie_id),

    CONSTRAINT chk_imdb_rating
        CHECK (
            imdb_rating IS NULL
            OR (imdb_rating >= 0 AND imdb_rating <= 10)
        ),

    CONSTRAINT chk_tmdb_rating
        CHECK (
            tmdb_rating IS NULL
            OR (tmdb_rating >= 0 AND tmdb_rating <= 10)
        ),

    CONSTRAINT chk_imdb_votes
        CHECK (
            imdb_vote_count >= 0
        ),

    CONSTRAINT chk_tmdb_votes
        CHECK (
            tmdb_vote_count >= 0
        ),

    CONSTRAINT chk_rotten_score
        CHECK (
            rotten_tomatoes_score IS NULL
            OR (
                rotten_tomatoes_score >= 0
                AND rotten_tomatoes_score <= 100
            )
        ),

    CONSTRAINT chk_metacritic_score
        CHECK (
            metacritic_score IS NULL
            OR (
                metacritic_score >= 0
                AND metacritic_score <= 100
            )
        ),

    CONSTRAINT chk_letterboxd_rating
        CHECK (
            letterboxd_rating IS NULL
            OR (
                letterboxd_rating >= 0
                AND letterboxd_rating <= 5
            )
        ),

    CONSTRAINT chk_popularity_score
        CHECK (
            popularity_score >= 0
        ),

    CONSTRAINT chk_weighted_rating
        CHECK (
            weighted_rating IS NULL
            OR (
                weighted_rating >= 0
                AND weighted_rating <= 10
            )
        ),

    CONSTRAINT chk_trending_score
        CHECK (
            trending_score IS NULL
            OR trending_score >= 0
        ),

    CONSTRAINT chk_ranking_score
        CHECK (
            ranking_score IS NULL
            OR ranking_score >= 0
        )
);

CREATE TRIGGER trg_movie_ratings_updated_at
BEFORE UPDATE
ON movie_ratings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE movie_ratings IS
'Stores rating information collected from multiple providers.';

COMMENT ON COLUMN movie_ratings.rating_id IS 'Primary key.';
COMMENT ON COLUMN movie_ratings.movie_id IS 'Referenced movie.';
COMMENT ON COLUMN movie_ratings.imdb_rating IS 'IMDb average rating.';
COMMENT ON COLUMN movie_ratings.imdb_vote_count IS 'IMDb vote count.';
COMMENT ON COLUMN movie_ratings.tmdb_rating IS 'TMDb average rating.';
COMMENT ON COLUMN movie_ratings.tmdb_vote_count IS 'TMDb vote count.';
COMMENT ON COLUMN movie_ratings.rotten_tomatoes_score IS 'Rotten Tomatoes percentage.';
COMMENT ON COLUMN movie_ratings.metacritic_score IS 'Metacritic critic score.';
COMMENT ON COLUMN movie_ratings.letterboxd_rating IS 'Letterboxd average rating.';
COMMENT ON COLUMN movie_ratings.popularity_score IS 'Normalized popularity score.';
COMMENT ON COLUMN movie_ratings.weighted_rating IS 'Weighted recommendation score.';
COMMENT ON COLUMN movie_ratings.trending_score IS 'Trending score.';
COMMENT ON COLUMN movie_ratings.ranking_score IS 'Overall ranking score.';
COMMENT ON COLUMN movie_ratings.last_updated_source IS 'Last source used to update this record.';
COMMENT ON COLUMN movie_ratings.created_at IS 'Creation timestamp.';
COMMENT ON COLUMN movie_ratings.updated_at IS 'Last update timestamp.';

CREATE TABLE genres
(
    genre_id        BIGSERIAL PRIMARY KEY,

    genre_name      CITEXT NOT NULL UNIQUE,

    description     TEXT,

    is_active       BOOLEAN NOT NULL DEFAULT TRUE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_genre_name
        CHECK (LENGTH(TRIM(genre_name)) > 0)
);

CREATE TRIGGER trg_genres_updated_at
BEFORE UPDATE
ON genres
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_genres
(
    movie_id        BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    genre_id        BIGINT NOT NULL
        REFERENCES genres(genre_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (movie_id, genre_id)
);


CREATE TABLE languages
(
    language_id             BIGSERIAL PRIMARY KEY,

    iso_639_1               VARCHAR(2) UNIQUE,

    iso_639_2               VARCHAR(3) UNIQUE,

    language_name           TEXT NOT NULL UNIQUE,

    native_name             TEXT,

    english_name            TEXT,

    is_active               BOOLEAN NOT NULL DEFAULT TRUE,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_iso639_1
        CHECK (
            iso_639_1 IS NULL
            OR LENGTH(iso_639_1)=2
        ),

    CONSTRAINT chk_iso639_2
        CHECK (
            iso_639_2 IS NULL
            OR LENGTH(iso_639_2)=3
        )
);

CREATE TRIGGER trg_languages_updated_at
BEFORE UPDATE
ON languages
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_languages
(
    movie_id            BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    language_id         BIGINT NOT NULL
        REFERENCES languages(language_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    is_original         BOOLEAN NOT NULL DEFAULT FALSE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (movie_id, language_id)
);


CREATE TABLE keywords
(
    keyword_id          BIGSERIAL PRIMARY KEY,

    keyword_name        CITEXT NOT NULL UNIQUE,

    source              metadata_source_enum,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_keyword_name
        CHECK (
            LENGTH(TRIM(keyword_name)) > 0
        )
);

CREATE TRIGGER trg_keywords_updated_at
BEFORE UPDATE
ON keywords
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_keywords
(
    movie_id            BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    keyword_id          BIGINT NOT NULL
        REFERENCES keywords(keyword_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    relevance_score     NUMERIC(5,4),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (movie_id, keyword_id),

    CONSTRAINT chk_keyword_relevance
        CHECK (
            relevance_score IS NULL
            OR (
                relevance_score >= 0
                AND relevance_score <= 1
            )
        )
);


CREATE TYPE person_role_enum AS ENUM
(
    'actor',
    'actress',
    'director',
    'writer',
    'producer',
    'composer',
    'cinematographer',
    'editor',
    'self',
    'archive_footage',
    'archive_sound',
    'guest',
    'host',
    'narrator',
    'creator',
    'executive_producer',
    'casting',
    'animation',
    'visual_effects',
    'stunts',
    'miscellaneous'
);

CREATE TABLE people
(
    person_id               BIGSERIAL PRIMARY KEY,

    imdb_person_id          TEXT NOT NULL UNIQUE,

    tmdb_person_id          BIGINT UNIQUE,

    full_name               TEXT NOT NULL,

    primary_profession      TEXT,

    known_for_titles        TEXT,

    biography               TEXT,

    birth_date              DATE,

    birth_year              INTEGER,

    death_date              DATE,

    death_year              INTEGER,

    gender                  SMALLINT,

    profile_image_url       TEXT,

    imdb_profile_url        TEXT,

    tmdb_profile_url        TEXT,

    homepage_url            TEXT,

    place_of_birth          TEXT,

    popularity              NUMERIC(12,4) DEFAULT 0,

    metadata_source_id      BIGINT
        REFERENCES metadata_sources(source_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    last_synced_at          TIMESTAMPTZ,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    deleted_at              TIMESTAMPTZ,

    CONSTRAINT chk_birth_year
        CHECK (
            birth_year IS NULL
            OR (
                birth_year >= 1800
                AND birth_year <= 2100
            )
        ),

    CONSTRAINT chk_death_year
        CHECK (
            death_year IS NULL
            OR (
                death_year >= birth_year
            )
        ),

    CONSTRAINT chk_popularity
        CHECK (
            popularity >= 0
        )
);

CREATE TRIGGER trg_people_updated_at
BEFORE UPDATE
ON people
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE movie_people
(
    movie_person_id         BIGSERIAL PRIMARY KEY,

    movie_id                BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    person_id               BIGINT NOT NULL
        REFERENCES people(person_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    role                    person_role_enum NOT NULL,

    character_name          TEXT,

    billing_order           INTEGER,

    department              TEXT,

    job_title               TEXT,

    is_lead                 BOOLEAN NOT NULL DEFAULT FALSE,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_movie_person_role
        UNIQUE
        (
            movie_id,
            person_id,
            role,
            character_name
        ),

    CONSTRAINT chk_billing_order
        CHECK (
            billing_order IS NULL
            OR billing_order >= 0
        )
);

CREATE TRIGGER trg_movie_people_updated_at
BEFORE UPDATE
ON movie_people
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();



CREATE TABLE collections
(
    collection_id              BIGSERIAL PRIMARY KEY,

    tmdb_collection_id         BIGINT UNIQUE,

    collection_name            TEXT NOT NULL UNIQUE,

    overview                   TEXT,

    poster_url                 TEXT,

    backdrop_url               TEXT,

    homepage_url               TEXT,

    metadata_source_id         BIGINT
        REFERENCES metadata_sources(source_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    last_synced_at             TIMESTAMPTZ,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    deleted_at                 TIMESTAMPTZ,

    CONSTRAINT chk_collection_name
        CHECK (
            LENGTH(TRIM(collection_name)) > 0
        )
);

CREATE TRIGGER trg_collections_updated_at
BEFORE UPDATE
ON collections
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_collections
(
    movie_id                   BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    collection_id              BIGINT NOT NULL
        REFERENCES collections(collection_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY
    (
        movie_id,
        collection_id
    )
);


CREATE TABLE production_companies
(
    company_id                 BIGSERIAL PRIMARY KEY,

    tmdb_company_id            BIGINT UNIQUE,

    company_name               TEXT NOT NULL UNIQUE,

    origin_country             VARCHAR(10),

    homepage_url               TEXT,

    logo_path                  TEXT,

    description                TEXT,

    algorithm_score            NUMERIC(10,6),

    reranked_score             NUMERIC(10,6),

    explanation                TEXT,

    request_size               INTEGER,

    response_size              INTEGER,

    response_time_bucket       TEXT,

    pipeline_version           TEXT,

    git_commit_hash            TEXT,

    last_trained_at            TIMESTAMPTZ,

    training_dataset           TEXT,

    api_endpoint               TEXT,

    license                    TEXT,

    website                    TEXT,

    metadata_source_id         BIGINT
        REFERENCES metadata_sources(source_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    deleted_at                 TIMESTAMPTZ,

    CONSTRAINT chk_company_name
        CHECK (
            LENGTH(TRIM(company_name)) > 0
        )
);

CREATE TRIGGER trg_production_companies_updated_at
BEFORE UPDATE
ON production_companies
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_production_companies
(
    movie_id                   BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    company_id                 BIGINT NOT NULL
        REFERENCES production_companies(company_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY
    (
        movie_id,
        company_id
    )
);


CREATE TABLE production_countries
(
    country_id                 BIGSERIAL PRIMARY KEY,

    iso_code                   VARCHAR(3) NOT NULL UNIQUE,

    country_name               TEXT NOT NULL UNIQUE,

    native_name                TEXT,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_iso_code
        CHECK (
            LENGTH(iso_code) BETWEEN 2 AND 3
        ),

    CONSTRAINT chk_country_name
        CHECK (
            LENGTH(TRIM(country_name)) > 0
        )
);

CREATE TRIGGER trg_production_countries_updated_at
BEFORE UPDATE
ON production_countries
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_production_countries
(
    movie_id                   BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    country_id                 BIGINT NOT NULL
        REFERENCES production_countries(country_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY
    (
        movie_id,
        country_id
    )
);



CREATE TABLE users
(
    user_id                     BIGSERIAL PRIMARY KEY,

    username                    CITEXT NOT NULL UNIQUE,

    email                       CITEXT NOT NULL UNIQUE,

    password_hash               TEXT NOT NULL,

    first_name                  TEXT,

    last_name                   TEXT,

    display_name                TEXT,

    avatar_url                  TEXT,

    bio                         TEXT,

    country                     TEXT,

    preferred_language          VARCHAR(10),

    timezone                    TEXT,

    is_verified                 BOOLEAN NOT NULL DEFAULT FALSE,

    is_admin                    BOOLEAN NOT NULL DEFAULT FALSE,

    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,

    last_login_at               TIMESTAMPTZ,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    deleted_at                  TIMESTAMPTZ,

    CONSTRAINT chk_username
        CHECK (length(trim(username)) >= 3),

    CONSTRAINT chk_email
        CHECK(email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE
ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE favorites
(
    favorite_id                 BIGSERIAL PRIMARY KEY,

    user_id                     BIGINT NOT NULL
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    movie_id                    BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_user_favorite
        UNIQUE
        (
            user_id,
            movie_id
        )
);


CREATE TABLE watch_history
(
    watch_history_id            BIGSERIAL PRIMARY KEY,

    user_id                     BIGINT NOT NULL
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    movie_id                    BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    watched_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    watch_duration_seconds      INTEGER DEFAULT 0,

    completed                   BOOLEAN NOT NULL DEFAULT FALSE,

    progress_percent            NUMERIC(5,2) DEFAULT 0,

    device                      TEXT,

    platform                    TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_watch_duration
        CHECK (watch_duration_seconds >= 0),

    CONSTRAINT chk_progress
        CHECK (progress_percent >= 0 AND progress_percent <= 100)
);

CREATE TRIGGER trg_watch_history_updated_at
BEFORE UPDATE
ON watch_history
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE reviews
(
    review_id                   BIGSERIAL PRIMARY KEY,

    user_id                     BIGINT NOT NULL
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    movie_id                    BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    rating                      NUMERIC(3,1),

    review_title                TEXT,

    review_text                 TEXT,

    contains_spoilers           BOOLEAN NOT NULL DEFAULT FALSE,

    helpful_votes               INTEGER NOT NULL DEFAULT 0,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    deleted_at                  TIMESTAMPTZ,

    CONSTRAINT chk_review_rating
        CHECK (rating >= 0.5 AND rating <= 10.0),

    CONSTRAINT chk_helpful_votes
        CHECK (helpful_votes >= 0),

    CONSTRAINT uq_user_movie_review
        UNIQUE
        (
            user_id,
            movie_id
        )
);

CREATE TRIGGER trg_reviews_updated_at
BEFORE UPDATE
ON reviews
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE search_history
(
    search_history_id           BIGSERIAL PRIMARY KEY,

    user_id                     BIGINT
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    search_query                TEXT NOT NULL,

    result_count                INTEGER DEFAULT 0,

    search_filters              JSONB,

    searched_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    ip_address                  INET,

    user_agent                  TEXT,

    session_id                  UUID DEFAULT uuid_generate_v4(),

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_result_count
        CHECK (result_count >= 0)
);



CREATE TYPE recommendation_model_type_enum AS ENUM
(
    'popularity',
    'content_based',
    'collaborative_filtering',
    'tfidf',
    'sentence_transformer',
    'hybrid',
    'semantic_search',
    'custom'
);

CREATE TABLE recommendation_models
(
    model_id                    BIGSERIAL PRIMARY KEY,

    model_name                  TEXT NOT NULL UNIQUE,

    model_type                  recommendation_model_type_enum NOT NULL,

    model_version               TEXT NOT NULL,

    description                 TEXT,

    embedding_model             TEXT,

    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    deleted_at                  TIMESTAMPTZ
);

CREATE TRIGGER trg_recommendation_models_updated_at
BEFORE UPDATE
ON recommendation_models
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_embeddings
(
    embedding_id                BIGSERIAL PRIMARY KEY,

    movie_id                    BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    model_id                    BIGINT NOT NULL
        REFERENCES recommendation_models(model_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    embedding_vector            VECTOR(384) NOT NULL,

    embedding_dimension         INTEGER NOT NULL DEFAULT 384,

    embedding_provider          TEXT,

    embedding_checksum          TEXT,

    embedding_version           TEXT NOT NULL,

    generated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_movie_embedding
        UNIQUE
        (
            movie_id,
            model_id,
            embedding_version
        ),

    CONSTRAINT chk_embedding_dimension
        CHECK (embedding_dimension > 0)
);

CREATE TRIGGER trg_movie_embeddings_updated_at
BEFORE UPDATE
ON movie_embeddings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE recommendation_logs
(
    recommendation_log_id       BIGSERIAL PRIMARY KEY,

    user_id                     BIGINT
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    model_id                    BIGINT
        REFERENCES recommendation_models(model_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    request_uuid                UUID NOT NULL DEFAULT uuid_generate_v4(),

    recommendation_type         TEXT,

    execution_time_ms           INTEGER,

    total_results               INTEGER,

    request_payload             JSONB,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_execution_time
        CHECK (execution_time_ms >= 0),

    CONSTRAINT chk_total_results
        CHECK (total_results >= 0)
);


CREATE TABLE recommendation_results
(
    recommendation_result_id    BIGSERIAL PRIMARY KEY,

    recommendation_log_id       BIGINT NOT NULL
        REFERENCES recommendation_logs(recommendation_log_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    movie_id                    BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    rank_position               INTEGER NOT NULL,

    similarity_score            NUMERIC(8,6),

    recommendation_reason       TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_log_movie
        UNIQUE
        (
            recommendation_log_id,
            movie_id
        ),

    CONSTRAINT chk_rank_position
        CHECK (rank_position > 0),

    CONSTRAINT chk_similarity_score
        CHECK
        (
            similarity_score IS NULL
            OR
            (
                similarity_score >= 0
                AND similarity_score <= 1
            )
        )
);




CREATE TABLE api_logs
(
    api_log_id                  BIGSERIAL PRIMARY KEY,

    request_id                  UUID NOT NULL DEFAULT uuid_generate_v4(),

    user_id                     BIGINT
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    endpoint                    TEXT NOT NULL,

    http_method                 VARCHAR(10) NOT NULL,

    status_code                 INTEGER NOT NULL,

    request_ip                  INET,

    user_agent                  TEXT,

    request_headers             JSONB,

    request_body                JSONB,

    response_body               JSONB,

    execution_time_ms           INTEGER NOT NULL DEFAULT 0,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_api_status
        CHECK (status_code BETWEEN 100 AND 599),

    CONSTRAINT chk_api_execution_time
        CHECK (execution_time_ms >= 0)
);


CREATE TABLE etl_runs
(
    etl_run_id                  BIGSERIAL PRIMARY KEY,

    pipeline_name               TEXT NOT NULL,

    source_name                 TEXT NOT NULL,

    source_version              TEXT,

    started_at                  TIMESTAMPTZ NOT NULL,

    finished_at                 TIMESTAMPTZ,

    status                      TEXT NOT NULL,

    records_read                BIGINT DEFAULT 0,

    records_inserted            BIGINT DEFAULT 0,

    records_updated             BIGINT DEFAULT 0,

    records_deleted             BIGINT DEFAULT 0,

    records_failed              BIGINT DEFAULT 0,

    execution_time_seconds      NUMERIC(12,2),

    log_file                    TEXT,

    error_message               TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_etl_records_read
        CHECK (records_read >= 0),

    CONSTRAINT chk_etl_records_inserted
        CHECK (records_inserted >= 0),

    CONSTRAINT chk_etl_records_updated
        CHECK (records_updated >= 0),

    CONSTRAINT chk_etl_records_deleted
        CHECK (records_deleted >= 0),

    CONSTRAINT chk_etl_records_failed
        CHECK (records_failed >= 0),

    CONSTRAINT chk_etl_execution_time
        CHECK
        (
            execution_time_seconds IS NULL
            OR execution_time_seconds >= 0
        )
);

CREATE TRIGGER trg_etl_runs_updated_at
BEFORE UPDATE
ON etl_runs
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE TABLE movie_views
(
    movie_view_id               BIGSERIAL PRIMARY KEY,

    movie_id                    BIGINT NOT NULL
        REFERENCES movies(movie_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    user_id                     BIGINT
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    viewed_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    session_id                  UUID DEFAULT uuid_generate_v4(),

    source                      TEXT,

    watch_duration_seconds      INTEGER DEFAULT 0,

    completed                   BOOLEAN DEFAULT FALSE,

    CONSTRAINT chk_movie_view_duration
        CHECK (watch_duration_seconds >= 0)
);


CREATE TABLE popular_searches
(
    popular_search_id           BIGSERIAL PRIMARY KEY,

    search_term                 TEXT NOT NULL,

    search_count                BIGINT NOT NULL DEFAULT 1,

    last_searched_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_popular_search
        UNIQUE (search_term),

    CONSTRAINT chk_search_count
        CHECK (search_count >= 0)
);

CREATE TRIGGER trg_popular_searches_updated_at
BEFORE UPDATE
ON popular_searches
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();


CREATE MATERIALIZED VIEW movie_search_document
AS
SELECT
    m.movie_id,
    m.title,
    m.original_title,
    to_tsvector(
        'english',
        coalesce(m.title, '') || ' ' ||
        coalesce(m.original_title, '') || ' ' ||
        coalesce(m.overview, '')
    ) AS search_vector
FROM movies m
WHERE m.deleted_at IS NULL;

COMMIT;