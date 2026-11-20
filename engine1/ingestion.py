import json
import re
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
# When this file is launched directly (python engine1/ingestion.py), Python
# puts engine1/ rather than the repository root on sys.path.
import sys
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    from source_detection import detect_source
except ImportError:
    detect_source = None

UPLOAD_DIR = BASE_DIR / "data" / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "raw_movies.json"

ALIASES = {
    "movie_title": ["movie_title", "title", "movie_name", "name", "original_title", "film_title", "primaryTitle"],
    "year": ["year", "release_year", "release_date", "date", "year_of_release", "startYear"],
    "genre": ["genre", "genres", "category", "categories"],
    "director": ["director", "directed_by", "film_director"],
    "rating": ["rating", "vote_average", "score", "imdb_rating", "averageRating"],
    "overview": ["overview", "description", "plot", "summary", "synopsis"],
    "cast": ["cast", "actors", "starring", "artists"],
    "tmdb_id": ["tmdb_id", "tmdbid"],
    "imdb_id": ["imdb_id", "imdbid", "tconst"],
    "movielens_id": ["movielens_id", "movieid"],
    "external_id": ["external_id", "movie_id", "id"],
}


def clean_column_name(name):
    return re.sub(r"[^a-z0-9]", "", str(name).casefold())


def clean(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else None


def parse_list(value):
    """Parse delimited values and JSON-encoded TMDB metadata safely."""
    value = clean(value)
    if not value:
        return []

    if value.startswith("[") or value.startswith("{"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                parsed = [parsed]
            if isinstance(parsed, list):
                result = []
                for item in parsed:
                    if isinstance(item, dict):
                        item = item.get("name") or item.get("Name") or item.get("title")
                    item = clean(item)
                    if item:
                        result.append(item)
                return result
        except (json.JSONDecodeError, TypeError):
            pass

    for separator in ("|", ";"):
        if separator in value:
            return [part.strip() for part in value.split(separator) if part.strip()]
    return [value]


def extract_year(value, title=None):
    for candidate in (value, title):
        if candidate is None:
            continue
        match = re.search(r"\b(18|19|20|21)\d{2}\b", str(candidate))
        if match:
            return int(match.group())
    return None


def read_uploaded_file(path):
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return pd.read_csv(path, sep=None, engine="python")
    if suffix == ".txt":
        return pd.read_csv(path, sep=None, engine="python")
    if suffix in (".xlsx", ".xlsm"):
        return pd.read_excel(path)
    raise ValueError(f"Unsupported file format: {path.name}")


def detect_columns(dataframe):
    detected = {}
    normalized_columns = {clean_column_name(column): column for column in dataframe.columns}
    for standard_field, aliases in ALIASES.items():
        for alias in aliases:
            key = clean_column_name(alias)
            if key in normalized_columns:
                detected[standard_field] = normalized_columns[key]
                break
    return detected


def detect_dataset_source(path):
    """Prefer schema-based detection; use filename hints only as a fallback."""
    if detect_source is not None:
        try:
            suggestion = detect_source(path).get("suggested_source")
            if suggestion and suggestion != "Unknown":
                return suggestion
        except Exception as error:
            print(f"Source detection warning for {path.name}: {error}")

    name = path.stem.casefold()
    if "movielens" in name or "movie_lens" in name:
        return "MovieLens"
    if "tmdb" in name:
        return "TMDB"
    if "imdb" in name:
        return "IMDb"
    # Do not invent a separate source name from each uploaded filename.
    # Unknown means the schema did not provide enough evidence.
    return "Unknown"


def _normalize_identifier(value):
    value = clean(value)
    if not value:
        return None
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
    except (ValueError, TypeError):
        pass
    return value


def ingest_uploaded_file(path):
    print(f"Reading uploaded file: {path.name}")
    dataframe = read_uploaded_file(path)
    columns = detect_columns(dataframe)
    if "movie_title" not in columns:
        raise ValueError(
            f"{path.name}: Could not identify a movie title column. "
            f"Available columns: {list(dataframe.columns)}"
        )

    source_name = detect_dataset_source(path)
    records = []
    for index, row in dataframe.iterrows():
        title = clean(row.get(columns["movie_title"]))
        if not title:
            continue

        def value_for(field):
            return row.get(columns[field]) if field in columns else None

        rating_value = clean(value_for("rating"))
        try:
            rating = float(rating_value) if rating_value is not None else None
        except (ValueError, TypeError):
            rating = None

        external_id = _normalize_identifier(value_for("external_id"))
        tmdb_id = _normalize_identifier(value_for("tmdb_id"))
        imdb_id = _normalize_identifier(value_for("imdb_id"))
        movielens_id = _normalize_identifier(value_for("movielens_id"))

        # TMDB's standard export calls its identifier simply `id`.
        if source_name == "TMDB" and not tmdb_id:
            tmdb_id = external_id
        # MovieLens movie exports identify records with `movieId`.
        if source_name == "MovieLens" and not movielens_id:
            movielens_id = external_id

        records.append({
            "record_id": f"{path.stem}_{index + 1}",
            "source_name": source_name,
            "source_file": path.name,
            "external_id": external_id or str(index + 1),
            "movielens_id": movielens_id,
            "imdb_id": imdb_id,
            "tmdb_id": tmdb_id,
            "movie_title": title,
            "year": extract_year(value_for("year"), title),
            "genre": parse_list(value_for("genre")),
            "director": clean(value_for("director")),
            "rating": rating,
            "rating_count": None,
            "overview": clean(value_for("overview")),
            "cast": parse_list(value_for("cast")),
        })

    print(f"Records loaded from {path.name}: {len(records)}")
    print(f"Detected source: {source_name}; columns: {columns}")
    return records


def ingest_data():
    print("\n========== ENGINE 1: DATA INGESTION ==========")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not UPLOAD_DIR.exists():
        raise FileNotFoundError("Upload directory not found. Create data/uploads first.")

    files = sorted(
        path for path in UPLOAD_DIR.iterdir()
        if path.is_file() and path.suffix.casefold() in (".csv", ".txt", ".xlsx", ".xlsm")
    )
    if not files:
        raise ValueError("No uploaded datasets found. Upload at least one supported file.")

    all_records = []
    for path in files:
        all_records.extend(ingest_uploaded_file(path))
    if not all_records:
        raise ValueError("No valid movie records were found in uploaded files.")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(all_records, file, indent=4, ensure_ascii=False)

    print("\n========== ENGINE 1 REPORT ==========")
    print("Uploaded files processed:", len(files))
    print("Total raw records:", len(all_records))
    print("Output:", OUTPUT_FILE)
    print("Engine 1 completed successfully!")
    print("=====================================\n")
    return all_records


if __name__ == "__main__":
    ingest_data()
