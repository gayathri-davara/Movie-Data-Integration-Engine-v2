
import json
import re
from pathlib import Path
from collections import Counter


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "output" / "raw_movies.json"
OUTPUT_FILE = BASE_DIR / "output" / "normalized_movies.json"


def clean_text(value):
    if value is None:
        return None

    if isinstance(value, list):
        cleaned = []
        for item in value:
            normalized = clean_text(item)
            if normalized:
                cleaned.append(normalized)
        return cleaned

    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def parse_year(value):
    if value is None:
        return None

    match = re.search(r"\b(18|19|20|21)\d{2}\b", str(value))

    if match:
        year = int(match.group())
        return year if 1888 <= year <= 2100 else None

    return None


def normalize_genres(value):
    if not value:
        return []

    if isinstance(value, str):
        genres = re.split(r"[,|;]", value)
    elif isinstance(value, list):
        genres = value
    else:
        return []

    result = []
    seen = set()

    for item in genres:
        genre = clean_text(item)

        if genre:
            genre = genre.title()

            if genre.casefold() not in seen:
                result.append(genre)
                seen.add(genre.casefold())

    return result


def normalize_rating(value, source_name):
    if value is None:
        return None

    try:
        rating = float(value)
    except (ValueError, TypeError):
        return None

    # MovieLens ratings are on a 0-5 scale.
    # Convert them to the common 0-10 scale.
    if str(source_name).casefold() == "movielens":
        rating *= 2

    return round(rating, 2) if 0 <= rating <= 10 else None


def normalize_movie(record):
    if not isinstance(record, dict):
        return None

    source = record.get("source_name", "Unknown")

    original_title = clean_text(record.get("movie_title"))
    year = parse_year(record.get("year"))

    # Extract year from title if not separately available.
    if year is None:
        year = parse_year(original_title)

    # Remove trailing year from standardized title.
    title = original_title

    if title:
        title = re.sub(
            r"\s*\(\d{4}\)\s*$",
            "",
            title
        ).strip()

    if not title:
        return None

    normalized = {
        "record_id": record.get("record_id"),
        "source_name": source,
        "external_id": record.get("external_id"),
        "movielens_id": record.get("movielens_id"),
        "tmdb_id": record.get("tmdb_id"),
        "imdb_id": record.get("imdb_id"),

        "movie_title": title,
        "original_title": original_title,
        "year": year,

        "genre": normalize_genres(record.get("genre")),
        "director": clean_text(record.get("director")),

        "rating": normalize_rating(
            record.get("rating"), source
        ),
        "rating_scale": "0-10",

        "overview": clean_text(record.get("overview")),
        "cast": (
            record.get("cast") if isinstance(record.get("cast"), list)
            else [clean_text(record.get("cast"))] if clean_text(record.get("cast")) else []
        ),

        "missing_fields": [],
        "data_quality_issues": []
    }

    # Identify missing fields.
    for field in ("year", "director", "rating", "overview"):
        if normalized[field] is None:
            normalized["missing_fields"].append(field)

    if not normalized["genre"]:
        normalized["missing_fields"].append("genre")

    if normalized["year"] is None and record.get("year"):
        normalized["data_quality_issues"].append("Invalid year")

    return normalized


def normalize_data():
    print("\n========== ENGINE 2: DATA NORMALIZATION ==========")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Engine 1 output not found: {INPUT_FILE}"
        )

    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        records = json.load(file)

    normalized_records = []
    skipped = 0

    for record in records:
        result = normalize_movie(record)

        if result:
            normalized_records.append(result)
        else:
            skipped += 1

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            normalized_records,
            file,
            indent=4,
            ensure_ascii=False
        )

    source_counts = Counter(
        movie["source_name"]
        for movie in normalized_records
    )

    missing_count = sum(
        bool(movie["missing_fields"])
        for movie in normalized_records
    )

    print("\n========== ENGINE 2 REPORT ==========")
    print("Input records:", len(records))
    print("Normalized records:", len(normalized_records))
    print("Skipped records:", skipped)
    print("Records with missing fields:", missing_count)
    print("Source distribution:", dict(source_counts))
    print("Output:", OUTPUT_FILE)
    print("Engine 2 completed successfully!")
    print("=====================================\n")

    return normalized_records


if __name__ == "__main__":
    normalize_data()
