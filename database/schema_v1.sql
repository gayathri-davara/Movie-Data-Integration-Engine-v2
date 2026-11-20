-- Movie Integration Platform: SQLite schema v1
-- Production schema only. Evaluation labels from links.csv are intentionally
-- kept in a separate evaluation store and are not visible to the matcher.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS data_source (
    source_id INTEGER PRIMARY KEY,
    source_code TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ingestion_batch (
    batch_id TEXT PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_source(source_id),
    source_filename TEXT NOT NULL,
    file_sha256 TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    rows_seen INTEGER NOT NULL DEFAULT 0 CHECK (rows_seen >= 0),
    rows_accepted INTEGER NOT NULL DEFAULT 0 CHECK (rows_accepted >= 0),
    error_message TEXT,
    CHECK (rows_accepted <= rows_seen)
);

-- Stable identity: (MOVIELENS, 1) differs from (TMDB, 1).
CREATE TABLE IF NOT EXISTS source_record (
    record_id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_source(source_id),
    external_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, external_id)
);

-- Immutable raw snapshot for a source record in a particular import batch.
CREATE TABLE IF NOT EXISTS source_record_version (
    record_version_id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL REFERENCES source_record(record_id),
    batch_id TEXT NOT NULL REFERENCES ingestion_batch(batch_id),
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    raw_payload TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (record_id, batch_id),
    UNIQUE (batch_id, source_row_number)
);

-- One canonicalized representation per raw record version.
-- Original source values remain in source_record_version.raw_payload.
CREATE TABLE IF NOT EXISTS normalized_record (
    record_version_id INTEGER PRIMARY KEY
        REFERENCES source_record_version(record_version_id) ON DELETE CASCADE,
    original_title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    release_year INTEGER CHECK (release_year IS NULL OR release_year BETWEEN 1888 AND 2100),
    overview TEXT,
    normalization_version TEXT NOT NULL,
    normalized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS genre (
    genre_id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS record_genre (
    record_version_id INTEGER NOT NULL
        REFERENCES normalized_record(record_version_id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES genre(genre_id),
    source_label TEXT,
    PRIMARY KEY (record_version_id, genre_id)
);

CREATE TABLE IF NOT EXISTS person (
    person_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    tmdb_person_id TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS record_credit (
    credit_id INTEGER PRIMARY KEY,
    record_version_id INTEGER NOT NULL
        REFERENCES normalized_record(record_version_id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES person(person_id),
    credit_role TEXT NOT NULL CHECK (credit_role IN ('DIRECTOR','CAST','CREW')),
    character_name TEXT,
    billing_order INTEGER CHECK (billing_order IS NULL OR billing_order >= 0)
);

-- Keep source metrics semantically separate: TMDB vote_average is not an
-- individual MovieLens user rating and must not be silently rescaled/merged.
CREATE TABLE IF NOT EXISTS source_metric (
    record_version_id INTEGER NOT NULL
        REFERENCES source_record_version(record_version_id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    scale_min REAL,
    scale_max REAL,
    observation_count INTEGER CHECK (observation_count IS NULL OR observation_count >= 0),
    PRIMARY KEY (record_version_id, metric_name),
    CHECK ((scale_min IS NULL AND scale_max IS NULL) OR
           (scale_min IS NOT NULL AND scale_max IS NOT NULL AND scale_min < scale_max))
);

CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    pipeline_version TEXT NOT NULL,
    configuration_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT
);

-- Pair stored once in canonical order; retain component scores and blocking evidence.
CREATE TABLE IF NOT EXISTS match_candidate (
    candidate_id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    left_record_version_id INTEGER NOT NULL
        REFERENCES source_record_version(record_version_id),
    right_record_version_id INTEGER NOT NULL
        REFERENCES source_record_version(record_version_id),
    blocking_methods_json TEXT NOT NULL DEFAULT '[]',
    title_similarity REAL CHECK (title_similarity IS NULL OR title_similarity BETWEEN 0 AND 1),
    year_similarity REAL CHECK (year_similarity IS NULL OR year_similarity BETWEEN 0 AND 1),
    genre_similarity REAL CHECK (genre_similarity IS NULL OR genre_similarity BETWEEN 0 AND 1),
    director_similarity REAL CHECK (director_similarity IS NULL OR director_similarity BETWEEN 0 AND 1),
    cast_similarity REAL CHECK (cast_similarity IS NULL OR cast_similarity BETWEEN 0 AND 1),
    final_score REAL CHECK (final_score IS NULL OR final_score BETWEEN 0 AND 1),
    decision TEXT NOT NULL CHECK (decision IN
        ('MATCH','POSSIBLE_MATCH','NON_MATCH','REJECTED_BY_CONSTRAINT')),
    decision_method TEXT NOT NULL,
    decision_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (left_record_version_id < right_record_version_id),
    UNIQUE (run_id, left_record_version_id, right_record_version_id)
);

CREATE TABLE IF NOT EXISTS movie_entity (
    entity_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Membership is run-scoped: later algorithm versions do not overwrite history.
CREATE TABLE IF NOT EXISTS entity_membership (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    entity_id INTEGER NOT NULL REFERENCES movie_entity(entity_id),
    record_version_id INTEGER NOT NULL REFERENCES source_record_version(record_version_id),
    membership_method TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    PRIMARY KEY (run_id, record_version_id)
);

-- One row per entity attribute value; multiple rows support multivalued fields.
CREATE TABLE IF NOT EXISTS entity_attribute (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    entity_id INTEGER NOT NULL REFERENCES movie_entity(entity_id),
    attribute_name TEXT NOT NULL,
    value_ordinal INTEGER NOT NULL DEFAULT 0 CHECK (value_ordinal >= 0),
    attribute_value TEXT NOT NULL,
    value_data_type TEXT NOT NULL DEFAULT 'TEXT'
        CHECK (value_data_type IN ('TEXT','INTEGER','REAL','DATE','JSON')),
    resolution_method TEXT NOT NULL,
    is_selected INTEGER NOT NULL DEFAULT 1 CHECK (is_selected IN (0,1)),
    PRIMARY KEY (run_id, entity_id, attribute_name, value_ordinal)
);

CREATE TABLE IF NOT EXISTS attribute_provenance (
    run_id TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    attribute_name TEXT NOT NULL,
    value_ordinal INTEGER NOT NULL,
    record_version_id INTEGER NOT NULL REFERENCES source_record_version(record_version_id),
    observed_source_value TEXT,
    contribution TEXT NOT NULL CHECK (contribution IN ('SUPPORTS','CONFLICTS','SELECTED_FROM')),
    PRIMARY KEY (run_id, entity_id, attribute_name, value_ordinal, record_version_id),
    FOREIGN KEY (run_id, entity_id, attribute_name, value_ordinal)
        REFERENCES entity_attribute(run_id, entity_id, attribute_name, value_ordinal)
        ON DELETE CASCADE
);

-- Decisions reference stable source_record identities so they survive re-ingestion.
CREATE TABLE IF NOT EXISTS review_decision (
    review_id INTEGER PRIMARY KEY,
    left_record_id INTEGER NOT NULL REFERENCES source_record(record_id),
    right_record_id INTEGER NOT NULL REFERENCES source_record(record_id),
    decision TEXT NOT NULL CHECK (decision IN ('MATCH','NON_MATCH')),
    reviewer TEXT NOT NULL,
    rationale TEXT,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    supersedes_review_id INTEGER REFERENCES review_decision(review_id),
    CHECK (left_record_id < right_record_id)
);

-- Optional later recommender extension. Not populated by metadata ingestion.
CREATE TABLE IF NOT EXISTS recommendation_user (
    recommendation_user_id INTEGER PRIMARY KEY,
    source_code TEXT NOT NULL,
    external_user_id TEXT NOT NULL,
    UNIQUE (source_code, external_user_id)
);

CREATE TABLE IF NOT EXISTS user_rating (
    rating_event_id INTEGER PRIMARY KEY,
    recommendation_user_id INTEGER NOT NULL
        REFERENCES recommendation_user(recommendation_user_id),
    record_id INTEGER NOT NULL REFERENCES source_record(record_id),
    rating_value REAL NOT NULL,
    rating_scale_min REAL NOT NULL,
    rating_scale_max REAL NOT NULL,
    rated_at TEXT,
    CHECK (rating_scale_min < rating_scale_max),
    CHECK (rating_value BETWEEN rating_scale_min AND rating_scale_max)
);

CREATE INDEX IF NOT EXISTS idx_source_record_source_external
    ON source_record(source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_record_version_batch
    ON source_record_version(batch_id);
CREATE INDEX IF NOT EXISTS idx_normalized_title_year
    ON normalized_record(normalized_title, release_year);
CREATE INDEX IF NOT EXISTS idx_record_genre_genre
    ON record_genre(genre_id, record_version_id);
CREATE INDEX IF NOT EXISTS idx_record_credit_person_role
    ON record_credit(person_id, credit_role, record_version_id);
CREATE INDEX IF NOT EXISTS idx_candidate_run_decision_score
    ON match_candidate(run_id, decision, final_score);
CREATE INDEX IF NOT EXISTS idx_membership_entity_run
    ON entity_membership(run_id, entity_id);
CREATE INDEX IF NOT EXISTS idx_review_pair_time
    ON review_decision(left_record_id, right_record_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_rating_record ON user_rating(record_id);

INSERT OR IGNORE INTO data_source (source_code, display_name)
VALUES ('MOVIELENS','MovieLens'), ('TMDB','The Movie Database'),
       ('IMDB','IMDb'), ('UNKNOWN','Unknown');

-- Cross-table integrity rules that SQLite CHECK constraints cannot express.
CREATE TRIGGER IF NOT EXISTS trg_version_batch_source_consistency
BEFORE INSERT ON source_record_version
FOR EACH ROW
WHEN (SELECT source_id FROM source_record WHERE record_id = NEW.record_id)
     != (SELECT source_id FROM ingestion_batch WHERE batch_id = NEW.batch_id)
BEGIN
    SELECT RAISE(ABORT, 'source record and ingestion batch must belong to the same source');
END;

CREATE TRIGGER IF NOT EXISTS trg_candidate_must_be_cross_source
BEFORE INSERT ON match_candidate
FOR EACH ROW
WHEN (SELECT sr.source_id
      FROM source_record_version srv JOIN source_record sr ON sr.record_id = srv.record_id
      WHERE srv.record_version_id = NEW.left_record_version_id)
   = (SELECT sr.source_id
      FROM source_record_version srv JOIN source_record sr ON sr.record_id = srv.record_id
      WHERE srv.record_version_id = NEW.right_record_version_id)
BEGIN
    SELECT RAISE(ABORT, 'entity-resolution candidates must be cross-source pairs');
END;

CREATE TRIGGER IF NOT EXISTS trg_entity_one_record_per_source
BEFORE INSERT ON entity_membership
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM entity_membership em
    JOIN source_record_version existing_version
      ON existing_version.record_version_id = em.record_version_id
    JOIN source_record existing_record
      ON existing_record.record_id = existing_version.record_id
    JOIN source_record_version new_version
      ON new_version.record_version_id = NEW.record_version_id
    JOIN source_record new_record
      ON new_record.record_id = new_version.record_id
    WHERE em.run_id = NEW.run_id
      AND em.entity_id = NEW.entity_id
      AND existing_record.source_id = new_record.source_id
)
BEGIN
    SELECT RAISE(ABORT, 'an entity cannot contain two records from the same source in one run');
END;

CREATE TRIGGER IF NOT EXISTS trg_provenance_record_must_belong_to_entity
BEFORE INSERT ON attribute_provenance
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1 FROM entity_membership em
    WHERE em.run_id = NEW.run_id
      AND em.entity_id = NEW.entity_id
      AND em.record_version_id = NEW.record_version_id
)
BEGIN
    SELECT RAISE(ABORT, 'provenance record must be a member of the referenced entity in this run');
END;
