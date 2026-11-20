# Movie Preference Recommendation System

The recommendation page is a questionnaire-driven discovery tool built on top
of the existing Engine 4 unified movie catalogue.

## Important: integration engines are unchanged

This update changes only:
- `recommendation_engine.py`
- the `/recommendations` route in `app.py`
- `templates/recommendations.html`
- this README

Engine 1 (ingestion), Engine 2 (normalization), Engine 3 (entity resolution)
and Engine 4 (integration) are not modified.

## How it works

1. The user chooses a mood and viewing occasion.
2. The user can select multiple genres.
3. The user chooses a release-year window.
4. The user chooses an optional minimum audience score.
5. The user can select one or more story themes.
6. The engine reads `output/unified_movies.json`, filters the unified entities,
   scores the remaining candidates and returns the top 20.

Mood and occasion are ranking signals rather than hard exclusions. Selected
genres, year window, minimum audience score and selected themes are filters.
Theme matching uses available title, overview, genre, director and cast text.
A result includes a short explanation of why it matched.

## Data limitations

The current unified catalogue includes title, year, genres, overview, director,
cast and an audience score. It does not contain verified content certification
such as G, PG, PG-13 or R, nor a dedicated TMDB keyword field. Therefore the
questionnaire does not pretend that the audience score is an age rating.
Certification filtering should be added only after a reliable certification
field/source is integrated.

Some catalogue entries have missing or malformed years. The recommender treats
implausible future years as unknown and excludes unknown-year movies when a
limited release window is selected. The supplied MovieLens/TMDB catalogue is
historical, so a "last 5 years" filter may return few or no results.

## Run

```powershell
.venv\Scripts\Activate.ps1
python app.py
```

Open `http://127.0.0.1:5000/recommendations`.

The recommendation engine only reads the unified JSON output. It does not
rerun, rewrite or mutate any of the four integration engines.
