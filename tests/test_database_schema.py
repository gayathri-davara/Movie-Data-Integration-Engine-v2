"""Smoke tests for the proposed SQLite schema; does not alter the app pipeline."""
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "database" / "schema_v1.sql"


class DatabaseSchemaTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.sources = dict(self.connection.execute(
            "SELECT source_code, source_id FROM data_source"
        ).fetchall())

    def tearDown(self):
        self.connection.close()

    def _batch(self, source_code, batch_id):
        self.connection.execute(
            "INSERT INTO ingestion_batch(batch_id, source_id, source_filename) VALUES (?, ?, ?)",
            (batch_id, self.sources[source_code], batch_id + ".csv"),
        )

    def _record_version(self, source_code, batch_id, external_id):
        cur = self.connection.execute(
            "INSERT INTO source_record(source_id, external_id) VALUES (?, ?)",
            (self.sources[source_code], external_id),
        )
        record_id = cur.lastrowid
        row_number = self.connection.execute(
            "SELECT COALESCE(MAX(source_row_number), 0) + 1 FROM source_record_version WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()[0]
        cur = self.connection.execute(
            "INSERT INTO source_record_version(record_id, batch_id, source_row_number, raw_payload) VALUES (?, ?, ?, '{}')",
            (record_id, batch_id, row_number),
        )
        return record_id, cur.lastrowid

    def test_schema_creates_and_foreign_keys_are_clean(self):
        tables = self.connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        self.assertGreaterEqual(tables, 18)
        self.assertEqual([], self.connection.execute("PRAGMA foreign_key_check").fetchall())

    def test_source_namespaces_allow_same_external_id(self):
        self._batch("MOVIELENS", "ml-batch")
        self._batch("TMDB", "tmdb-batch")
        self._record_version("MOVIELENS", "ml-batch", "1")
        self._record_version("TMDB", "tmdb-batch", "1")

    def test_source_record_cannot_be_versioned_under_other_source_batch(self):
        self._batch("MOVIELENS", "ml-batch")
        self._batch("TMDB", "tmdb-batch")
        cur = self.connection.execute(
            "INSERT INTO source_record(source_id, external_id) VALUES (?, '42')",
            (self.sources["MOVIELENS"],),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO source_record_version(record_id, batch_id, source_row_number, raw_payload) VALUES (?, 'tmdb-batch', 1, '{}')",
                (cur.lastrowid,),
            )

    def test_candidate_pairs_must_be_cross_source(self):
        self._batch("MOVIELENS", "ml-batch")
        self._batch("TMDB", "tmdb-batch")
        _, ml_version = self._record_version("MOVIELENS", "ml-batch", "1")
        _, tmdb_version = self._record_version("TMDB", "tmdb-batch", "24428")
        self.connection.execute(
            "INSERT INTO pipeline_run(run_id, pipeline_version) VALUES ('run-1', 'v1')"
        )
        left, right = sorted((ml_version, tmdb_version))
        self.connection.execute(
            "INSERT INTO match_candidate(run_id,left_record_version_id,right_record_version_id,decision,decision_method) VALUES ('run-1',?,?, 'POSSIBLE_MATCH','test')",
            (left, right),
        )

    def test_entity_rejects_two_records_from_same_source(self):
        self._batch("MOVIELENS", "ml-batch")
        _, v1 = self._record_version("MOVIELENS", "ml-batch", "1")
        _, v2 = self._record_version("MOVIELENS", "ml-batch", "2")
        self.connection.execute("INSERT INTO pipeline_run(run_id,pipeline_version) VALUES ('run-1','v1')")
        entity_id = self.connection.execute("INSERT INTO movie_entity DEFAULT VALUES").lastrowid
        self.connection.execute(
            "INSERT INTO entity_membership(run_id,entity_id,record_version_id,membership_method) VALUES ('run-1',?,?, 'test')",
            (entity_id, v1),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO entity_membership(run_id,entity_id,record_version_id,membership_method) VALUES ('run-1',?,?, 'test')",
                (entity_id, v2),
            )


if __name__ == "__main__":
    unittest.main()
