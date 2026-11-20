
import json
import csv
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "output" / "normalized_movies.json"
RESOLUTION_FILE = BASE_DIR / "output" / "resolved_movies.json"

JSON_OUTPUT = BASE_DIR / "output" / "unified_movies.json"
CSV_OUTPUT = BASE_DIR / "output" / "unified_movies.csv"
SOURCE_OUTPUT = BASE_DIR / "output" / "movie_sources.csv"


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def first_valid(records, field):
    """Prefer TMDB metadata, then use another available source."""
    priorities = {"tmdb": 0, "imdb": 1, "movielens": 2}
    ordered = sorted(
        records,
        key=lambda r: priorities.get(str(r.get("source_name", "")).casefold(), 3)
    )

    for record in ordered:
        value = record.get(field)

        if value is not None and value != "" and value != []:
            return value

    return None


def integrate_movies():
    print("\n========== ENGINE 4: DATA INTEGRATION ==========")

    records = load_json(INPUT_FILE)
    resolution = load_json(RESOLUTION_FILE)
    if not isinstance(records, list):
        raise ValueError("Normalized movie output must be a JSON list.")
    if not isinstance(resolution, dict) or not isinstance(resolution.get("record_assignments"), list):
        raise ValueError("Resolution output is missing record assignments. Run Engine 3 first.")

    # Map each original record to its resolved entity
    assignments = {}
    for item in resolution["record_assignments"]:
        record_id = item.get("record_id")
        entity_id = item.get("entity_id")
        if not record_id or not entity_id:
            raise ValueError("Invalid record assignment: record_id and entity_id are required.")
        if record_id in assignments:
            raise ValueError(f"Duplicate entity assignment for record: {record_id}")
        assignments[record_id] = entity_id

    # Every normalized record must receive exactly one entity assignment.
    normalized_ids = [record.get("record_id") for record in records]
    if any(not record_id for record_id in normalized_ids):
        raise ValueError("Every normalized record must have a record_id.")
    if len(normalized_ids) != len(set(normalized_ids)):
        raise ValueError("Normalized input contains duplicate record_id values.")

    missing_assignments = set(normalized_ids) - set(assignments)
    unknown_assignments = set(assignments) - set(normalized_ids)
    if missing_assignments or unknown_assignments:
        raise ValueError(
            "Entity assignments do not cover normalized records exactly "
            f"(missing={len(missing_assignments)}, unknown={len(unknown_assignments)})."
        )

    # Group original records by entity.
    grouped_records = defaultdict(list)
    for record in records:
        record_id = record["record_id"]
        grouped_records[assignments[record_id]].append(record)

    unified_movies = []
    source_rows = []

    for entity_id, group in grouped_records.items():

        source_names = sorted({
            record.get("source_name", "Unknown")
            for record in group
        })

        # Support both common genre field names
        genres = first_valid(group, "genres")
        if genres is None:
            genres = first_valid(group, "genre")

        movie = {
            "entity_id": entity_id,
            "movie_title": first_valid(group, "movie_title"),
            "year": first_valid(group, "year"),
            "genres": genres or [],
            "director": first_valid(group, "director"),
            "overview": first_valid(group, "overview"),
            "cast": first_valid(group, "cast") or [],
            "rating": first_valid(group, "rating"),
            "record_count": len(group),
            "source_count": len(source_names),
            "sources": source_names
        }

        unified_movies.append(movie)

        # Preserve original source identifiers
        for record in group:
            source_rows.append({
                "entity_id": entity_id,
                "record_id": record.get("record_id"),
                "source_name": record.get("source_name"),
                "external_id": record.get("external_id"),
                "movielens_id": record.get("movielens_id"),
                "tmdb_id": record.get("tmdb_id"),
                "imdb_id": record.get("imdb_id")
            })

    # Save unified JSON
    with open(JSON_OUTPUT, "w", encoding="utf-8") as file:
        json.dump(
            unified_movies,
            file,
            indent=4,
            ensure_ascii=False
        )

    # Save unified CSV
    csv_fields = [
        "entity_id", "movie_title", "year", "genres",
        "director", "overview", "cast", "rating",
        "record_count", "source_count", "sources"
    ]

    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=csv_fields)
        writer.writeheader()

        for movie in unified_movies:
            row = movie.copy()

            for field in ("genres", "cast", "sources"):
                row[field] = json.dumps(
                    row[field],
                    ensure_ascii=False
                )

            writer.writerow(row)

    # Save source mapping CSV
    with open(SOURCE_OUTPUT, "w", newline="", encoding="utf-8-sig") as file:
        fields = [
            "entity_id", "record_id", "source_name",
            "external_id", "movielens_id", "tmdb_id", "imdb_id"
        ]

        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(source_rows)

    multi_source = sum(
        1 for movie in unified_movies
        if movie["source_count"] > 1
    )

    print("\n========== ENGINE 4 REPORT ==========")
    print("Input records:", len(records))
    print("Unified movie entities:", len(unified_movies))
    print("Multi-source entities:", multi_source)
    print("Single-source entities:", len(unified_movies) - multi_source)
    print("Source mappings:", len(source_rows))
    print("\nGenerated files:")
    print(JSON_OUTPUT)
    print(CSV_OUTPUT)
    print(SOURCE_OUTPUT)
    print("\nEngine 4 completed successfully!")
    print("=====================================\n")


if __name__ == "__main__":
    integrate_movies()
