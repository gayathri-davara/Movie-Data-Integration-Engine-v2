import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine3.matcher import resolve_entities, _candidate_pairs, normalize_title
from source_detection import detect_source
from unittest.mock import patch
import tempfile
import json
from engine4 import integration as engine4
from recommendation_engine import recommend_by_preferences


def record(record_id, source, title, year=None, tmdb_id=None, imdb_id=None, genre=None):
    return {
        "record_id": record_id,
        "source_name": source,
        "movie_title": title,
        "year": year,
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "genre": genre or [],
    }


class EntityResolutionTests(unittest.TestCase):
    def test_exact_identifier_merges_across_sources(self):
        result = resolve_entities([
            record("a", "TMDB", "Avatar", 2009, tmdb_id=19995),
            record("b", "IMDb", "Avatar", 2009, tmdb_id=19995),
        ])
        self.assertEqual(result["stats"]["confirmed_matches"], 1)
        self.assertEqual(result["stats"]["entity_count"], 1)

    def test_same_source_records_are_not_merged(self):
        result = resolve_entities([
            record("a", "TMDB", "Avatar", 2009, tmdb_id=19995),
            record("b", "TMDB", "Avatar", 2009, tmdb_id=19995),
        ])
        self.assertEqual(result["stats"]["entity_count"], 2)
        self.assertEqual(result["stats"]["confirmed_matches"], 0)

    def test_conflicting_identifiers_block_fuzzy_merge(self):
        result = resolve_entities([
            record("a", "MovieLens", "The Matrix", 1999, tmdb_id=1),
            record("b", "TMDB", "The Matrix", 1999, tmdb_id=2),
        ])
        self.assertEqual(result["stats"]["entity_count"], 2)
        self.assertGreaterEqual(result["stats"]["possible_matches"], 1)

    def test_small_title_variation_matches(self):
        result = resolve_entities([
            record("a", "MovieLens", "The Matrix", 1999, genre=["Action", "Sci-Fi"]),
            record("b", "TMDB", "The Matriix", 1999, genre=["Action", "Sci-Fi"]),
        ])
        self.assertEqual(result["stats"]["confirmed_matches"], 1)
        self.assertEqual(result["stats"]["entity_count"], 1)

    def test_large_year_gap_does_not_match(self):
        result = resolve_entities([
            record("a", "MovieLens", "King Kong", 1933),
            record("b", "TMDB", "King Kong", 2005),
        ])
        self.assertEqual(result["stats"]["entity_count"], 2)
        self.assertEqual(result["stats"]["confirmed_matches"], 0)

    def test_duplicate_record_ids_raise(self):
        with self.assertRaises(ValueError):
            resolve_entities([
                record("same", "MovieLens", "A", 2000),
                record("same", "TMDB", "A", 2000),
            ])

    def test_candidate_generation_is_bounded(self):
        rows = [
            record(f"ml-{i}", "MovieLens", f"Unique Movie Title {i:05d}", 2000 + (i % 10))
            for i in range(1000)
        ]
        rows += [
            record(f"tmdb-{i}", "TMDB", f"Unique Movie Title {i:05d}", 2000 + (i % 10))
            for i in range(1000)
        ]
        titles = [normalize_title(item["movie_title"]) for item in rows]
        pairs = _candidate_pairs(rows, titles)
        # A full cross-source Cartesian comparison would be 1,000,000 pairs.
        self.assertLess(len(pairs), 100_000)



class IntegrationValidationTests(unittest.TestCase):
    def test_missing_entity_assignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            normalized_path = temp / "normalized.json"
            resolution_path = temp / "resolved.json"
            normalized_path.write_text(json.dumps([
                record("r1", "TMDB", "Avatar", 2009, tmdb_id=19995)
            ]), encoding="utf-8")
            resolution_path.write_text(json.dumps({
                "record_assignments": []
            }), encoding="utf-8")

            with patch.object(engine4, "INPUT_FILE", normalized_path), \
                 patch.object(engine4, "RESOLUTION_FILE", resolution_path), \
                 patch.object(engine4, "JSON_OUTPUT", temp / "unified.json"), \
                 patch.object(engine4, "CSV_OUTPUT", temp / "unified.csv"), \
                 patch.object(engine4, "SOURCE_OUTPUT", temp / "sources.csv"):
                with self.assertRaisesRegex(ValueError, "do not cover normalized records"):
                    engine4.integrate_movies()


class SourceDetectionTests(unittest.TestCase):
    def test_uploaded_movielens_schema_is_detected(self):
        result = detect_source(ROOT / "data" / "uploads" / "movies_106d4bb1.csv")
        self.assertEqual(result["suggested_source"], "MovieLens")

    def test_uploaded_tmdb_schema_is_detected(self):
        result = detect_source(ROOT / "data" / "uploads" / "tmdb_5000_movies_413d263e.csv")
        self.assertEqual(result["suggested_source"], "TMDB")


class RecommendationSystemTests(unittest.TestCase):
    def test_preference_recommendations_use_unified_catalogue(self):
        result = recommend_by_preferences({
            "mood": "Happy",
            "occasion": "With friends",
            "genres": ["Action", "Comedy"],
            "year_window": "any",
            "min_rating": "7",
            "themes": [],
        }, limit=5)
        self.assertEqual(result["catalogue_size"], 11908)
        self.assertGreater(result["total_matches"], 0)
        self.assertTrue(result["recommendations"])
        self.assertLessEqual(len(result["recommendations"]), 5)
        self.assertTrue(all(item["movie"].get("entity_id")
                            for item in result["recommendations"]))

    def test_selected_theme_filters_candidates(self):
        result = recommend_by_preferences({
            "themes": ["Space"],
            "year_window": "any",
            "min_rating": "any",
        }, limit=5)
        self.assertGreater(result["total_matches"], 0)
        self.assertTrue(all("Space" in item["matched_themes"]
                            for item in result["recommendations"]))

    def test_unknown_or_unselected_preferences_do_not_crash(self):
        result = recommend_by_preferences({}, limit=5)
        self.assertEqual(result["catalogue_size"], 11908)
        self.assertEqual(result["shown"], 5)

    def test_limited_year_window_excludes_unknown_years(self):
        result = recommend_by_preferences({"year_window": "5"}, limit=5)
        self.assertTrue(all(
            2021 <= int(item["movie"]["year"]) <= 2026
            for item in result["recommendations"]
        ))


if __name__ == "__main__":
    unittest.main()
