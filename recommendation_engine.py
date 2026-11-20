"""Preference-based movie recommendations from the Engine 4 unified catalogue.

This module intentionally does not run or modify the integration pipeline.
It reads output/unified_movies.json and ranks its existing movie entities
using questionnaire answers (mood, occasion, genres, release window,
audience score and themes).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
UNIFIED_FILE = BASE_DIR / "output" / "unified_movies.json"

GENRES = [
    "Action", "Comedy", "Drama", "Adventure", "Thriller", "Crime",
    "Romance", "Science Fiction", "Fantasy", "Family", "Mystery",
    "Biography", "History", "Animation", "Music", "Sport", "Documentary",
    "Western", "War", "Horror"
]

THEME_KEYWORDS = {
    "Based on true stories": ["based on a true", "true story", "true events", "real-life", "based on real"],
    "Space": ["outer space", "space exploration", "space station", "space mission", "astronaut", "planet", "galaxy", "alien invasion", "extraterrestrial", "spaceship", "mars", "nasa", "interstellar"],
    "New York": ["new york", "manhattan", "brooklyn", "new york city"],
    "Wedding": ["wedding", "bride", "groom", "marriage", "married"],
    "Heist": ["heist", "robbery", "robbers", "bank job", "steal", "thieves"],
    "Based on a book": ["based on the novel", "based on a book", "adaptation of", "based on the book"],
    "Racing": ["racing", "race car", "formula one", "formula 1", "racer", "nascar", "grand prix"],
    "Girl power": ["female empowerment", "women empowerment", "girl power", "women's rights", "female friendship"],
    "Family-oriented": ["family", "parents", "children", "siblings", "mother", "father"],
    "Prequels and sequels": ["sequel", "prequel", "returns", "part ii", "part 2", "chapter 2", "continues"],
    "Superheroes": ["superhero", "super-hero", "super power", "superpower", "masked hero"],
    "Survival": ["survival", "survive", "stranded", "wilderness", "disaster"],
    "Time travel": ["time travel", "time machine", "travels through time", "future and past"],
    "Feel-good": ["friendship", "hope", "inspiring", "heartwarming", "feel-good", "uplifting"],
}

MOOD_GENRES = {
    "Happy": {"Comedy": 3, "Family": 2, "Adventure": 2, "Animation": 2, "Music": 1},
    "Neutral": {"Drama": 2, "Mystery": 2, "Thriller": 1, "Crime": 1, "Science Fiction": 1},
    "Sad": {"Comedy": 3, "Family": 2, "Romance": 2, "Animation": 1},
}
MOOD_TERMS = {
    "Happy": ["fun", "joy", "celebration", "friendship", "adventure", "comedy", "love"],
    "Neutral": ["mystery", "journey", "investigation", "discovery", "drama"],
    "Sad": ["hope", "friendship", "heartwarming", "comedy", "family", "inspiring"],
}
OCCASION_GENRES = {
    "Watching by myself": {"Mystery": 2, "Thriller": 2, "Drama": 1, "Science Fiction": 1},
    "Movie date": {"Romance": 3, "Comedy": 2, "Drama": 1},
    "With friends": {"Comedy": 2, "Action": 2, "Adventure": 2, "Horror": 1},
    "With family and relatives": {"Family": 3, "Animation": 2, "Comedy": 2, "Adventure": 1},
    "With boyfriend/girlfriend": {"Romance": 3, "Comedy": 2, "Drama": 1},
    "Movie night / group gathering": {"Comedy": 2, "Action": 2, "Horror": 2, "Adventure": 1},
}
OCCASION_TERMS = {
    "Watching by myself": ["psychological", "mystery", "mind", "space", "journey"],
    "Movie date": ["love", "romance", "relationship", "couple", "wedding"],
    "With friends": ["friendship", "team", "adventure", "comedy", "competition"],
    "With family and relatives": ["family", "children", "parents", "siblings", "friendship"],
    "With boyfriend/girlfriend": ["love", "romance", "relationship", "couple"],
    "Movie night / group gathering": ["team", "competition", "comedy", "adventure", "horror"],
}


def _load_movies() -> list[dict[str, Any]]:
    if not UNIFIED_FILE.exists():
        raise FileNotFoundError(
            "Unified movie catalogue not found. Run the four-engine pipeline first."
        )
    with UNIFIED_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("The unified movie catalogue has an unexpected format.")
    return [movie for movie in data if isinstance(movie, dict)]


def _normalise_genres(value: Any) -> set[str]:
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
            values = parsed if isinstance(parsed, list) else re.split(r"[,|]", value)
        except (json.JSONDecodeError, TypeError):
            values = re.split(r"[,|]", value)
    else:
        values = []
    return {str(item).strip().casefold() for item in values if str(item).strip()}


def _movie_text(movie: dict[str, Any]) -> str:
    fields = (
        movie.get("movie_title"), movie.get("overview"),
        movie.get("director"), movie.get("cast"), movie.get("genres")
    )
    return " ".join(str(value) for value in fields if value).casefold()


def _year(movie: dict[str, Any]) -> int | None:
    value = movie.get("year")
    try:
        match = re.search(r"\d{4}", str(value))
        parsed = int(match.group()) if match else None
        # Guard against malformed upstream values where a title's year-like
        # number was mistakenly placed in the release-year field.
        return parsed if parsed is not None and 1888 <= parsed <= 2026 else None
    except (TypeError, ValueError):
        return None


def _rating(movie: dict[str, Any]) -> float | None:
    try:
        value = float(movie.get("rating"))
        return value if 0 <= value <= 10 else None
    except (TypeError, ValueError):
        return None


def _contains_term(text: str, term: str) -> bool:
    # Word boundaries avoid matches such as "mars" inside "marsh" or
    # "alien" inside unrelated phrases such as "illegal-alien smuggling".
    escaped = re.escape(term.casefold()).replace(r"\ ", r"\s+")
    pattern = r"(?<!\w)" + escaped + r"(?!\w)"
    if term.casefold() == "alien invasion":
        return bool(re.search(pattern, text)) or "extraterrestrial" in text
    return bool(re.search(pattern, text))


def _theme_matches(movie: dict[str, Any], selected_themes: list[str]) -> list[str]:
    text = _movie_text(movie)
    matched = []
    for theme in selected_themes:
        terms = THEME_KEYWORDS.get(theme, [])
        if any(_contains_term(text, term) for term in terms):
            matched.append(theme)
    return matched


def recommend_by_preferences(preferences: dict[str, Any], limit: int = 20) -> dict[str, Any]:
    """Filter and rank unified movies using questionnaire preferences."""
    movies = _load_movies()
    selected_genres = [str(x) for x in preferences.get("genres", []) if str(x) in GENRES]
    selected_themes = [
        str(x) for x in preferences.get("themes", [])
        if str(x) in THEME_KEYWORDS
    ]
    mood = str(preferences.get("mood") or "")
    occasion = str(preferences.get("occasion") or "")
    year_window = str(preferences.get("year_window") or "any")
    min_rating_raw = str(preferences.get("min_rating") or "any")

    year_limits = {"5": 5, "10": 10, "25": 25}
    max_age = year_limits.get(year_window)
    current_year = 2026

    min_rating = None
    if min_rating_raw in {"6", "7", "8"}:
        min_rating = float(min_rating_raw)

    mood_weights = MOOD_GENRES.get(mood, {})
    occasion_weights = OCCASION_GENRES.get(occasion, {})
    mood_terms = MOOD_TERMS.get(mood, [])
    occasion_terms = OCCASION_TERMS.get(occasion, [])

    ranked: list[tuple[float, dict[str, Any], list[str], list[str]]] = []
    for movie in movies:
        title = str(movie.get("movie_title") or "").strip()
        if not title:
            continue

        movie_genres = _normalise_genres(movie.get("genres"))
        if selected_genres and not any(g.casefold() in movie_genres for g in selected_genres):
            continue

        movie_year = _year(movie)
        if max_age is not None:
            # Unknown release years cannot be proven to meet a selected time window.
            if movie_year is None or movie_year < current_year - max_age:
                continue

        score_value = _rating(movie)
        if min_rating is not None and (score_value is None or score_value < min_rating):
            continue

        matched_themes = _theme_matches(movie, selected_themes)
        # If the user explicitly selected themes, require at least one theme match.
        if selected_themes and not matched_themes:
            continue

        score = 0.0
        reasons: list[str] = []
        matched_genres = [
            genre for genre in selected_genres
            if genre.casefold() in movie_genres
        ]
        if matched_genres:
            score += 10.0 * len(matched_genres)
            reasons.append("Matches " + ", ".join(matched_genres))

        genre_names = {g.title(): g for g in movie_genres}
        for genre, weight in mood_weights.items():
            if genre.casefold() in movie_genres:
                score += weight
        if mood and any(g.casefold() in movie_genres for g in mood_weights):
            reasons.append(f"Genre fit for a {mood.lower()} mood")

        for genre, weight in occasion_weights.items():
            if genre.casefold() in movie_genres:
                score += weight
        if occasion and any(g.casefold() in movie_genres for g in occasion_weights):
            reasons.append(f"Suitable genre mix for: {occasion.lower()}")

        text = _movie_text(movie)
        mood_hits = sum(1 for term in mood_terms if term in text)
        occasion_hits = sum(1 for term in occasion_terms if term in text)
        score += min(mood_hits, 3) * 0.8
        score += min(occasion_hits, 3) * 0.5

        if matched_themes:
            score += 8.0 * len(matched_themes)
            reasons.append("Theme match: " + ", ".join(matched_themes))

        if score_value is not None:
            # Audience score is a ranking signal, not an age/content certification.
            score += score_value * 0.35
            reasons.append(f"Audience score {score_value:.1f}/10")

        if movie_year is not None:
            reasons.append(f"Released {movie_year}")

        ranked.append((score, movie, reasons, matched_themes))

    ranked.sort(
        key=lambda item: (
            -item[0],
            -(_rating(item[1]) or 0),
            -( _year(item[1]) or 0),
            str(item[1].get("movie_title", "")).casefold()
        )
    )

    results = []
    for score, movie, reasons, matched_themes in ranked[:max(1, min(limit, 50))]:
        results.append({
            "movie": movie,
            "match_score": round(score, 2),
            "reasons": reasons[:4] or ["Matches your selected movie preferences"],
            "matched_themes": matched_themes,
        })

    return {
        "recommendations": results,
        "total_matches": len(ranked),
        "shown": len(results),
        "preferences": {
            "mood": mood,
            "occasion": occasion,
            "genres": selected_genres,
            "year_window": year_window,
            "min_rating": min_rating_raw,
            "themes": selected_themes,
        },
        "catalogue_size": len(movies),
    }
