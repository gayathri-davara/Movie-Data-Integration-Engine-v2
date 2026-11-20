"""Hybrid dataset-source detection for MovieSync.

Detection is advisory: the user confirms or overrides every suggestion.
"""
from pathlib import Path
import re
import pandas as pd

SUPPORTED_SOURCES = ("MovieLens", "TMDB", "IMDb", "Unknown")


def _norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _read_columns(path):
    suffix = Path(path).suffix.casefold()
    if suffix in {".csv", ".txt"}:
        frame = pd.read_csv(path, sep=None, engine="python", nrows=100, encoding_errors="replace")
    elif suffix in {".xlsx", ".xlsm"}:
        frame = pd.read_excel(path, nrows=100)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")
    return frame


def detect_source(path):
    """Return source suggestion, confidence, evidence and detected columns."""
    frame = _read_columns(path)
    columns = {_norm(column) for column in frame.columns}
    scores = {source: 0 for source in SUPPORTED_SOURCES if source != "Unknown"}
    evidence = {source: [] for source in scores}

    rules = {
        "MovieLens": {
            "movieid": (35, "movieId column"),
            "userid": (15, "userId column"),
            "genres": (20, "genres column"),
            "rating": (10, "rating column"),
            "timestamp": (10, "timestamp column"),
            "tag": (5, "tag column"),
        },
        "TMDB": {
            "originaltitle": (30, "original_title column"),
            "voteaverage": (20, "vote_average column"),
            "votecount": (10, "vote_count column"),
            "posterpath": (10, "poster_path column"),
            "releasedate": (15, "release_date column"),
            "original_language": (10, "original_language column"),
            "movieid": (15, "movie_id column"),
            "crew": (10, "crew column"),
            "cast": (10, "cast column"),
            "title": (10, "title column (combined with TMDB credits fields)"),
        },
        "IMDb": {
            "tconst": (40, "tconst identifier column"),
            "primarytitle": (20, "primaryTitle column"),
            "titletype": (15, "titleType column"),
            "startyear": (10, "startYear column"),
            "averagerating": (10, "averageRating column"),
            "numvotes": (5, "numVotes column"),
        },
    }
    for source, source_rules in rules.items():
        for column, (points, description) in source_rules.items():
            if _norm(column) in columns:
                scores[source] += points
                evidence[source].append(description)

    # IMDb title identifiers are particularly distinctive; inspect sample values.
    for column in frame.columns:
        if _norm(column) == "tconst":
            sample = frame[column].dropna().astype(str).head(30)
            if len(sample) and sample.str.fullmatch(r"tt\d{7,10}").mean() >= 0.7:
                scores["IMDb"] += 15
                evidence["IMDb"].append("IMDb-style tt... identifiers")
            break

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_source, best_score = ranked[0]
    second_score = ranked[1][1]
    # Confidence is intentionally conservative and is not a statistical probability.
    confidence = min(100, best_score)
    decisive = best_score >= 40 and (best_score - second_score) >= 10
    suggested = best_source if decisive else "Unknown"
    reason = evidence[best_source] if decisive else ["Insufficient or ambiguous source-specific evidence"]

    return {
        "suggested_source": suggested,
        "confidence": confidence,
        "scores": scores,
        "evidence": reason,
        "columns": [str(column) for column in frame.columns],
        "row_sample_count": int(len(frame)),
        "status": "needs_confirmation",
    }
