BEGIN;

SET search_path TO cinemind, public;

INSERT INTO metadata_sources
(
    source_name,
    dataset_version,
    description
)
VALUES
(
    'IMDb',
    'Daily TSV',
    'Primary movie and television metadata'
),
(
    'TMDb',
    'API v3',
    'Movie enrichment including posters, overviews, collections and popularity'
),
(
    'OMDb',
    'API',
    'Supplementary ratings and metadata'
),
(
    'YouTube',
    'Data API v3',
    'Official trailers'
);

INSERT INTO genres (genre_name)
VALUES
('Action'),
('Adventure'),
('Animation'),
('Biography'),
('Comedy'),
('Crime'),
('Documentary'),
('Drama'),
('Family'),
('Fantasy'),
('History'),
('Horror'),
('Music'),
('Musical'),
('Mystery'),
('Romance'),
('Sci-Fi'),
('Sport'),
('Thriller'),
('War'),
('Western'),
('Film-Noir'),
('Reality-TV'),
('Talk-Show'),
('Game-Show'),
('News');

INSERT INTO languages
(
    iso_639_1,
    language_name
)
VALUES
('en','English'),
('hi','Hindi'),
('bn','Bengali'),
('ta','Tamil'),
('te','Telugu'),
('ml','Malayalam'),
('kn','Kannada'),
('mr','Marathi'),
('gu','Gujarati'),
('pa','Punjabi'),
('ur','Urdu'),
('ko','Korean'),
('ja','Japanese'),
('zh','Chinese'),
('fr','French'),
('de','German'),
('es','Spanish'),
('it','Italian'),
('ru','Russian'),
('pt','Portuguese'),
('tr','Turkish'),
('ar','Arabic'),
('th','Thai'),
('id','Indonesian'),
('vi','Vietnamese');

INSERT INTO production_countries
(
    iso_code,
    country_name
)
VALUES
('US','United States'),
('IN','India'),
('KR','South Korea'),
('JP','Japan'),
('CN','China'),
('GB','United Kingdom'),
('FR','France'),
('DE','Germany'),
('IT','Italy'),
('ES','Spain'),
('CA','Canada'),
('AU','Australia'),
('NZ','New Zealand');

INSERT INTO recommendation_models
(
    model_name,
    model_type,
    model_version,
    description,
    is_active
)
VALUES
(
    'Popularity Ranking',
    'popularity',
    '1.0',
    'Ranks movies using popularity and vote count.',
    TRUE
),
(
    'Genre Similarity',
    'content_based',
    '1.0',
    'Genre overlap recommendation.',
    TRUE
),
(
    'TF-IDF Content Model',
    'tfidf',
    '1.0',
    'Content recommendation using TF-IDF.',
    TRUE
),
(
    'Sentence Transformer',
    'sentence_transformer',
    '1.0',
    'Semantic recommendation using sentence embeddings.',
    FALSE
),
(
    'Hybrid Recommendation',
    'hybrid',
    '1.0',
    'Popularity + Genre + Semantic ranking.',
    FALSE
);

COMMIT;