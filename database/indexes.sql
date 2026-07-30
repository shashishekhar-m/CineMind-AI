CREATE INDEX idx_movie_genres_movie
ON movie_genres(movie_id);

CREATE INDEX idx_movie_genres_genre
ON movie_genres(genre_id);

CREATE INDEX idx_movie_languages_movie
ON movie_languages(movie_id);

CREATE INDEX idx_movie_languages_language
ON movie_languages(language_id);

CREATE INDEX idx_movie_keywords_movie
ON movie_keywords(movie_id);

CREATE INDEX idx_movie_keywords_keyword
ON movie_keywords(keyword_id);

CREATE INDEX idx_genres_name
ON genres(genre_name);

CREATE INDEX idx_languages_name
ON languages(language_name);

CREATE INDEX idx_keywords_name
ON keywords(keyword_name);

CREATE INDEX idx_people_name
ON people(full_name)
WHERE deleted_at IS NULL;

CREATE INDEX idx_people_imdb
ON people(imdb_person_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_people_tmdb
ON people(tmdb_person_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_people_profession
ON people(primary_profession)
WHERE deleted_at IS NULL;

CREATE INDEX idx_movie_people_movie
ON movie_people(movie_id);

CREATE INDEX idx_movie_people_person
ON movie_people(person_id);

CREATE INDEX idx_movie_people_role
ON movie_people(role);

CREATE INDEX idx_movie_people_character
ON movie_people(character_name);

CREATE INDEX idx_collections_name
ON collections(collection_name);

CREATE INDEX idx_collections_tmdb
ON collections(tmdb_collection_id);

CREATE INDEX idx_movie_collections_movie
ON movie_collections(movie_id);

CREATE INDEX idx_movie_collections_collection
ON movie_collections(collection_id);

CREATE INDEX idx_production_companies_name
ON production_companies(company_name);

CREATE INDEX idx_production_companies_tmdb
ON production_companies(tmdb_company_id);

CREATE INDEX idx_movie_production_companies_movie
ON movie_production_companies(movie_id);

CREATE INDEX idx_movie_production_companies_company
ON movie_production_companies(company_id);

CREATE INDEX idx_production_countries_iso
ON production_countries(iso_code);

CREATE INDEX idx_production_countries_name
ON production_countries(country_name);

CREATE INDEX idx_movie_production_countries_movie
ON movie_production_countries(movie_id);

CREATE INDEX idx_movie_production_countries_country
ON movie_production_countries(country_id);

CREATE INDEX idx_users_username
ON users(username)
WHERE deleted_at IS NULL;

CREATE INDEX idx_users_email
ON users(email)
WHERE deleted_at IS NULL;

CREATE INDEX idx_favorites_user
ON favorites(user_id);

CREATE INDEX idx_favorites_movie
ON favorites(movie_id);

CREATE INDEX idx_watch_history_user
ON watch_history(user_id);

CREATE INDEX idx_watch_history_movie
ON watch_history(movie_id);

CREATE INDEX idx_watch_history_date
ON watch_history(watched_at);

CREATE INDEX idx_reviews_user
ON reviews(user_id);

CREATE INDEX idx_reviews_movie
ON reviews(movie_id);

CREATE INDEX idx_reviews_rating
ON reviews(rating);

CREATE INDEX idx_search_history_user
ON search_history(user_id);

CREATE INDEX idx_search_history_query
ON search_history
USING GIN (to_tsvector('english', search_query));

CREATE INDEX idx_search_history_date
ON search_history(searched_at);

CREATE INDEX idx_recommendation_models_type
ON recommendation_models(model_type);

CREATE INDEX idx_recommendation_models_active
ON recommendation_models(is_active);

CREATE INDEX idx_movie_embeddings_movie
ON movie_embeddings(movie_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_movie_embeddings_model
ON movie_embeddings(model_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_movie_embeddings_vector
ON movie_embeddings
USING ivfflat (embedding_vector vector_cosine_ops);

CREATE INDEX idx_recommendation_logs_user
ON recommendation_logs(user_id);

CREATE INDEX idx_recommendation_logs_model
ON recommendation_logs(model_id);

CREATE INDEX idx_recommendation_logs_created
ON recommendation_logs(created_at);

CREATE INDEX idx_recommendation_results_log
ON recommendation_results(recommendation_log_id);

CREATE INDEX idx_recommendation_results_movie
ON recommendation_results(movie_id);

CREATE INDEX idx_recommendation_results_rank
ON recommendation_results(rank_position);

CREATE INDEX idx_api_logs_user
ON api_logs(user_id);

CREATE INDEX idx_api_logs_request
ON api_logs(request_id);

CREATE INDEX idx_api_logs_endpoint
ON api_logs(endpoint);

CREATE INDEX idx_api_logs_created
ON api_logs(created_at);

CREATE INDEX idx_etl_runs_pipeline
ON etl_runs(pipeline_name);

CREATE INDEX idx_etl_runs_status
ON etl_runs(status);

CREATE INDEX idx_etl_runs_started
ON etl_runs(started_at);

CREATE INDEX idx_movie_views_movie
ON movie_views(movie_id);

CREATE INDEX idx_movie_views_user
ON movie_views(user_id);

CREATE INDEX idx_movie_views_viewed
ON movie_views(viewed_at);

CREATE INDEX idx_popular_search_term
ON popular_searches(search_term);

CREATE INDEX idx_popular_search_count
ON popular_searches(search_count DESC);

CREATE UNIQUE INDEX idx_movie_search_document_movie
ON movie_search_document(movie_id);

CREATE INDEX idx_movie_search_document_vector
ON movie_search_document
USING GIN(search_vector);

CREATE INDEX idx_movie_title_trgm
ON movies
USING GIN(title gin_trgm_ops);

CREATE INDEX idx_movie_original_title_trgm
ON movies
USING GIN(original_title gin_trgm_ops);

CREATE INDEX idx_people_name_trgm
ON people
USING GIN(full_name gin_trgm_ops);

CREATE INDEX idx_movies_fulltext
ON movies
USING GIN (
    to_tsvector(
        'english',
        coalesce(title,'') || ' ' ||
        coalesce(overview,'') || ' ' ||
        coalesce(tagline,'')
    )
);

CREATE UNIQUE INDEX idx_movies_imdb
ON movies(imdb_id);

CREATE UNIQUE INDEX idx_movies_tmdb
ON movies(tmdb_id);

CREATE INDEX idx_movie_ratings_rating
ON movie_ratings(imdb_rating DESC);

CREATE INDEX idx_movie_ratings_votes
ON movie_ratings(vote_count DESC);

CREATE INDEX idx_movies_year_language
ON movies(release_year, original_language);