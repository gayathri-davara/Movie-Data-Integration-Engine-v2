# Bug-fix audit notes

## Confirmed problems fixed

1. **Engine 1 source detection was silently bypassed when run through `main.py`.**
   `ingestion.py` was executed as a script from `engine1/`, so the repository root
   was not guaranteed to be on `sys.path`. The import failed and the code fell
   back to the upload filename as the source name. The repository root is now
   added before importing `source_detection`, and unknown schemas use `Unknown`
   rather than inventing a source from the filename.

2. **Engine 3 had an unbounded year-bucket pair comparison.**
   It compared all records in a year bucket with all records in that year and
   adjacent years. The supplied 14,545-record data set did not finish within the
   initial two-minute audit window. Candidate generation now uses exact-title
   groups plus a bounded sorted-neighbourhood window, avoiding the quadratic
   year-bucket expansion.

3. **Engine 3 fuzzy matching used title similarity alone.**
   It now computes a weighted score using title similarity, release-year
   agreement, and genre Jaccard similarity when those attributes are available.
   Missing year information triggers a stricter threshold. Conflicting external
   identifiers remain review-only.

4. **Engine 3 could form unsafe fuzzy transitive clusters.**
   Fuzzy cluster unions now check source uniqueness, identifier consistency,
   title coherence, and year consistency across the clusters.

5. **Engine 3 comparison statistics under-reported work.**
   Candidate pairs generated and candidate pairs evaluated are now reported
   separately, and the evaluated counter is incremented for fuzzy candidates.

6. **Engine 4 silently ignored normalized records without an assignment.**
   It now validates that normalized record IDs and resolution assignments form
   an exact one-to-one coverage before creating unified entities.

7. **Engine 4 source priority was case-sensitive.**
   TMDB / IMDb / MovieLens priority selection is now case-insensitive.

## Validation

Run:

```bash
python -m unittest discover -s tests -v
python main.py
```

The audit run on the supplied uploads processed 14,545 records end-to-end in
approximately 30.6 seconds in this environment. It produced 11,908 unified
entities, including 2,637 multi-source entities and 9,271 single-source
entities. These are pipeline outputs, not a ground-truth accuracy measurement.

## Remaining data limitation

The supplied upload folder contains MovieLens `movies.csv`-style data and the
TMDB 5000 movies export. It does not contain the MovieLens ratings file joined
to movies, the TMDB credits file joined to movies, or an IMDb title dataset in
the upload folder. Therefore many records correctly remain without ratings or
director metadata; Engine 2 reports missing fields rather than fabricating
values.
