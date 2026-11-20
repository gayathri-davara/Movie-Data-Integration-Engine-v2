import hashlib
import os
import secrets
from werkzeug.utils import secure_filename
import uuid

import csv
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from recommendation_engine import recommend_by_preferences, GENRES, THEME_KEYWORDS

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
UPLOAD_DIR = BASE_DIR / "data" / "uploads"

ALLOWED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".xlsm"}
OUTPUT_ARTIFACTS = (
    "raw_movies.json", "normalized_movies.json", "resolved_movies.json",
    "unified_movies.json", "unified_movies.csv", "movie_sources.csv"
)

app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
MAIN_FILE = BASE_DIR / "main.py"

pipeline_lock = threading.Lock()


def invalidate_outputs():
    """Remove old pipeline artifacts so the UI cannot present stale results."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename in OUTPUT_ARTIFACTS:
        path = OUTPUT_DIR / filename
        if path.is_file():
            path.unlink()


pipeline_status = {
    "running": False,
    "message": "Ready",
    "current_engine": None,
    "started_at": None,
    "duration": None,
    "progress": 0,
    "engines": [
        {"name": "Engine 1", "title": "Data Ingestion", "status": "pending"},
        {"name": "Engine 2", "title": "Data Normalization", "status": "pending"},
        {"name": "Engine 3", "title": "Entity Resolution", "status": "pending"},
        {"name": "Engine 4", "title": "Data Integration", "status": "pending"}
    ],
    "logs": []
}

def get_file_hash(path):
    sha256 = hashlib.sha256()

    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def load_json(filename):
    path = OUTPUT_DIR / filename

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError, UnicodeError):
        return None


def get_dashboard_data():
    raw = load_json("raw_movies.json") or []
    normalized = load_json("normalized_movies.json") or []
    resolved = load_json("resolved_movies.json") or {}
    unified = load_json("unified_movies.json") or []

    raw = raw if isinstance(raw, list) else []
    normalized = normalized if isinstance(normalized, list) else []
    resolved = resolved if isinstance(resolved, dict) else {}
    unified = unified if isinstance(unified, list) else []
    resolution_stats = resolved.get("stats", {})
    resolution_stats = resolution_stats if isinstance(resolution_stats, dict) else {}

    source_counts = {}
    for record in raw:
        source = record.get("source_name", "Unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

    multi_source = sum(
        1 for movie in unified
        if movie.get("source_count", 0) > 1
    )

    possible_matches = resolved.get("possible_matches", [])
    possible_matches = possible_matches if isinstance(possible_matches, list) else []

    output_files = list(OUTPUT_ARTIFACTS)

    engines = [
        {
            "name": "Engine 1",
            "title": "Data Ingestion",
            "description": "Loads heterogeneous movie datasets.",
            "output": "raw_movies.json"
        },
        {
            "name": "Engine 2",
            "title": "Data Normalization",
            "description": "Cleans and standardizes movie attributes.",
            "output": "normalized_movies.json"
        },
        {
            "name": "Engine 3",
            "title": "Entity Resolution",
            "description": "Identifies duplicate movie records.",
            "output": "resolved_movies.json"
        },
        {
            "name": "Engine 4",
            "title": "Data Integration",
            "description": "Creates unified movie entities.",
            "output": "unified_movies.json"
        }
    ]

    for engine in engines:
        engine["completed"] = (OUTPUT_DIR / engine["output"]).exists()

    return {
        "raw_count": len(raw),
        "normalized_count": len(normalized),
        "unified_count": len(unified),
        "confirmed_matches": resolution_stats.get("confirmed_matches", 0),
        "possible_count": len(possible_matches),
        "multi_source": multi_source,
        "single_source": len(unified) - multi_source,
        "source_counts": source_counts,
        "engines": engines,
        "output_files": [
            {"name": name, "exists": (OUTPUT_DIR / name).exists()}
            for name in output_files
        ],
        "movies": unified
    }


def execute_pipeline():
    try:
        process = subprocess.Popen(
            [sys.executable, "-u", str(MAIN_FILE)],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )

        for line in process.stdout:
            line = line.rstrip()

            if not line:
                continue

            pipeline_status["logs"].append(line)

            # Keep the latest 300 log lines
            pipeline_status["logs"] = pipeline_status["logs"][-300:]

            upper_line = line.upper()

            if "RUNNING ENGINE 1" in upper_line:
                pipeline_status["current_engine"] = "Engine 1"
                pipeline_status["engines"][0]["status"] = "running"

            elif "RUNNING ENGINE 2" in upper_line:
                pipeline_status["current_engine"] = "Engine 2"
                pipeline_status["engines"][1]["status"] = "running"

            elif "RUNNING ENGINE 3" in upper_line:
                pipeline_status["current_engine"] = "Engine 3"
                pipeline_status["engines"][2]["status"] = "running"

            elif "RUNNING ENGINE 4" in upper_line:
                pipeline_status["current_engine"] = "Engine 4"
                pipeline_status["engines"][3]["status"] = "running"

            elif "ENGINE 1: DATA INGESTION COMPLETED SUCCESSFULLY" in upper_line:
                pipeline_status["engines"][0]["status"] = "completed"
                pipeline_status["progress"] = 25

            elif "ENGINE 2: DATA NORMALIZATION COMPLETED SUCCESSFULLY" in upper_line:
                pipeline_status["engines"][1]["status"] = "completed"
                pipeline_status["progress"] = 50

            elif "ENGINE 3: ENTITY RESOLUTION COMPLETED SUCCESSFULLY" in upper_line:
                pipeline_status["engines"][2]["status"] = "completed"
                pipeline_status["progress"] = 75

            elif "ENGINE 4: DATA INTEGRATION COMPLETED SUCCESSFULLY" in upper_line:
                pipeline_status["engines"][3]["status"] = "completed"
                pipeline_status["progress"] = 100

        return_code = process.wait()

        if return_code == 0:
            pipeline_status["message"] = "Pipeline completed successfully"
            pipeline_status["progress"] = 100
            pipeline_status["current_engine"] = None
            pipeline_status["logs"].append("ALL ENGINES COMPLETED SUCCESSFULLY")
        else:
            pipeline_status["message"] = "Pipeline failed"
            pipeline_status["current_engine"] = None

            for engine in pipeline_status["engines"]:
                if engine["status"] == "running":
                    engine["status"] = "failed"

            pipeline_status["logs"].append(
                f"PIPELINE FAILED WITH EXIT CODE {return_code}"
            )

    except Exception as error:
        pipeline_status["message"] = f"Pipeline error: {error}"
        pipeline_status["logs"].append(f"ERROR: {error}")

        for engine in pipeline_status["engines"]:
            if engine["status"] == "running":
                engine["status"] = "failed"

    finally:
        pipeline_status["running"] = False
        pipeline_status["current_engine"] = None

        if pipeline_status["started_at"] is not None:
            pipeline_status["duration"] = round(
                time.time() - pipeline_status["started_at"], 2
            )

        pipeline_lock.release()


@app.route("/run-pipeline", methods=["POST"])
def run_pipeline():
    if not pipeline_lock.acquire(blocking=False):
        flash("Pipeline is already running.", "warning")
        return redirect(url_for("index"))

    invalidate_outputs()

    pipeline_status.update({
        "running": True,
        "message": "Pipeline started",
        "current_engine": None,
        "started_at": time.time(),
        "duration": None,
        "progress": 0,
        "logs": []
    })

    for engine in pipeline_status["engines"]:
        engine["status"] = "pending"

    worker = threading.Thread(
        target=execute_pipeline,
        daemon=True
    )
    worker.start()

    return redirect(url_for("index") + "#monitor")


@app.route("/pipeline-status")
def pipeline_status_api():
    result = dict(pipeline_status)
    result["engines"] = [dict(engine) for engine in pipeline_status["engines"]]
    result["logs"] = list(pipeline_status["logs"])

    if result["running"] and result["started_at"] is not None:
        result["elapsed"] = round(time.time() - result["started_at"], 1)
    else:
        result["elapsed"] = result["duration"] or 0

    return jsonify(result)



@app.route("/")
def index():
    data = get_dashboard_data()

    query = request.args.get("q", "").strip().casefold()
    movies = data["movies"]

    if query:
        movies = [
            movie for movie in movies
            if query in str(movie.get("movie_title") or "").casefold()
            or query in str(movie.get("director") or "").casefold()
            or query in str(movie.get("year") or "")
        ]

    data["movies"] = movies[:100]
    data["search_query"] = request.args.get("q", "")
    data["search_total"] = len(movies)

    return render_template(
        "index.html",
        data=data,
        status=pipeline_status
    )





@app.route("/possible-matches")
def possible_matches():
    resolved = load_json("resolved_movies.json") or {}
    matches = resolved.get("possible_matches", [])

    return render_template(
        "index.html",
        data=get_dashboard_data(),
        status=pipeline_status,
        possible_view=True,
        possible_records=matches[:100]
    )



@app.route("/movie/<entity_id>")
def movie_detail(entity_id):
    unified_movies = load_json("unified_movies.json") or []
    normalized_movies = load_json("normalized_movies.json") or []
    resolved = load_json("resolved_movies.json") or {}

    # Find consolidated movie
    movie = next(
        (m for m in unified_movies if m.get("entity_id") == entity_id),
        None
    )

    if movie is None:
        flash("Movie entity not found.", "error")
        return redirect(url_for("index"))

    # Map normalized records by record ID
    normalized_index = {
        record.get("record_id"): record
        for record in normalized_movies
    }

    # Find original records belonging to this entity
    source_records = []
    source_file = OUTPUT_DIR / "movie_sources.csv"
    entity_record_ids = set()

    if source_file.exists():
        with open(source_file, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)

            for row in reader:
                if row.get("entity_id") == entity_id:
                    record_id = row.get("record_id")
                    entity_record_ids.add(record_id)

                    original = normalized_index.get(record_id, {})

                    source_records.append({
                        "mapping": row,
                        "record": original
                    })

    # Find confirmed match evidence for this entity
    match_evidence = []

    for match in resolved.get("matches", []):
        left_id = match.get("left_record_id")
        right_id = match.get("right_record_id")

        if left_id in entity_record_ids and right_id in entity_record_ids:
            match_evidence.append({
                "left_id": left_id,
                "right_id": right_id,
                "score": match.get("score"),
                "decision": match.get("decision"),
                "method": match.get("method"),
                "identifier": match.get("identifier"),
                "year": match.get("year")
            })

    # Find possible matches involving this entity's records.
    # These are displayed for review, not treated as merged evidence.
    possible_evidence = []

    for match in resolved.get("possible_matches", []):
        left_id = match.get("left_record_id")
        right_id = match.get("right_record_id")

        if left_id in entity_record_ids or right_id in entity_record_ids:
            possible_evidence.append(match)

    return render_template(
        "movie_detail.html",
        movie=movie,
        source_records=source_records,
        match_evidence=match_evidence,
        possible_evidence=possible_evidence
    )


@app.route("/recommendations", methods=["GET", "POST"])
def recommendations():
    result = None
    error = None
    if request.method == "POST":
        preferences = {
            "mood": request.form.get("mood", "Happy"),
            "occasion": request.form.get("occasion", "Watching by myself"),
            "genres": request.form.getlist("genres"),
            "year_window": request.form.get("year_window", "any"),
            "min_rating": request.form.get("min_rating", "any"),
            "themes": request.form.getlist("themes"),
        }
        try:
            result = recommend_by_preferences(preferences, limit=20)
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
            error = str(exc)

    return render_template(
        "recommendations.html",
        result=result,
        error=error,
        genres=GENRES,
        themes=list(THEME_KEYWORDS.keys()),
    )


@app.route("/upload", methods=["POST"])
def upload_datasets():
    if pipeline_status["running"]:
        flash("Cannot upload datasets while the pipeline is running.", "warning")
        return redirect(url_for("index"))

    files = request.files.getlist("datasets")

    if not files or all(not file.filename for file in files):
        flash("Please select at least one dataset.", "warning")
        return redirect(url_for("index"))

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    uploaded = []
    skipped = []
    errors = []

    existing_hashes = {
        get_file_hash(path)
        for path in UPLOAD_DIR.iterdir()
        if path.is_file()
    }

    for file in files:
        if not file.filename:
            continue

        original_name = secure_filename(file.filename)
        extension = Path(original_name).suffix.casefold()

        if extension not in ALLOWED_EXTENSIONS:
            errors.append(f"{original_name}: unsupported file type")
            continue

        file.stream.seek(0)
        sha256 = hashlib.sha256()

        for chunk in iter(lambda: file.stream.read(1024 * 1024), b""):
            sha256.update(chunk)

        file_hash = sha256.hexdigest()
        file.stream.seek(0)

        if file_hash in existing_hashes:
            skipped.append(original_name)
            continue

        stored_name = (
            f"{Path(original_name).stem}_"
            f"{uuid.uuid4().hex[:8]}{extension}"
        )

        file.save(UPLOAD_DIR / stored_name)

        existing_hashes.add(file_hash)
        uploaded.append(original_name)

    if uploaded:
        invalidate_outputs()
        flash(
            f"Successfully uploaded {len(uploaded)} dataset(s). Previous results were cleared; rerun the pipeline.",
            "success"
        )

    if skipped:
        flash(
            f"Skipped {len(skipped)} duplicate file(s): "
            f"{', '.join(skipped)}",
            "warning"
        )

    if errors:
        flash("; ".join(errors), "error")

    return redirect(url_for("index"))


@app.route("/clear-uploads", methods=["POST"])
def clear_uploads():
    if pipeline_status["running"]:
        flash("Cannot clear datasets while the pipeline is running.", "warning")
        return redirect(url_for("index"))

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    deleted_count = 0

    for path in UPLOAD_DIR.iterdir():
        if path.is_file():
            path.unlink()
            deleted_count += 1

    invalidate_outputs()
    flash(
        f"Cleared {deleted_count} uploaded dataset(s) and invalidated previous results.",
        "success"
    )

    return redirect(url_for("index"))
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
