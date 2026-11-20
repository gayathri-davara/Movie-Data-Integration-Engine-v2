# Movie Data Integration Engine

A multi-source movie data integration system that combines datasets from MovieLens, TMDB and other movie sources into a unified movie catalogue.

## Project Architecture

### Engine 1 – Data Ingestion
- Reads movie datasets from multiple sources.
- Supports heterogeneous input files.
- Extracts records for further processing.

### Engine 2 – Data Normalization
- Standardizes movie attributes.
- Handles inconsistent formats and values.
- Prepares records for entity matching.

### Engine 3 – Entity Resolution
- Identifies records referring to the same movie.
- Uses identifier-based and similarity-based matching.
- Resolves duplicate movie entities across sources.

### Engine 4 – Data Integration
- Combines resolved records.
- Produces a unified movie catalogue.
- Generates integrated output datasets.

## Recommendation System

A questionnaire-driven recommendation system built on the unified movie catalogue.

Users can select:
- Mood and viewing occasion
- Genres
- Release-year range
- Minimum audience score
- Story themes

## Technology Stack

- Python
- Pandas
- NumPy
- Flask
- SQL

## Project Structure

```text
Movie-Data-Integration-Engine-V2/
├── data/
├── database/
├── docs/
├── engine1/
├── engine2/
├── engine3/
├── engine4/
├── output/
├── static/
├── templates/
├── tests/
├── app.py
├── main.py
├── recommendation_engine.py
├── source_detection.py
├── requirements.txt
└── README.md
```

## Installation

```bash
git clone https://github.com/gayathri-davara/Movie-Data-Integration-Engine-V2.git
cd Movie-Data-Integration-Engine-V2

python -m venv .venv
```

Windows activation:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the Application

```bash
python app.py
```

Open `http://127.0.0.1:5000`.

## Database Design

Database schema and documentation are available in the `database/` and `docs/` directories.

## Testing

```bash
python -m pytest tests/
```

## Project Status

The repository contains four integration engines, database design, generated catalogue outputs, a Flask application and a movie recommendation module.