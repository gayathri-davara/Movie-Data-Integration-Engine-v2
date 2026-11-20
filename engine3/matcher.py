import json
import re
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher
from bisect import bisect_left

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "output" / "normalized_movies.json"
OUTPUT_FILE = BASE_DIR / "output" / "resolved_movies.json"

MATCH_THRESHOLD = 0.92
POSSIBLE_THRESHOLD = 0.78
YEAR_TOLERANCE = 1
NEIGHBOR_WINDOW = 18


def normalize_title(title):
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(title).casefold())


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def normalize_identifier(value):
    if value in (None, ""):
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def find(record, field):
    return normalize_identifier(record.get(field))


def _year(record):
    value = record.get("year")
    try:
        year = int(value)
        return year if 1888 <= year <= 2100 else None
    except (TypeError, ValueError):
        return None


def _genre_set(record):
    genres = record.get("genre") or record.get("genres") or []
    if isinstance(genres, str):
        genres = re.split(r"[,|;]", genres)
    if not isinstance(genres, (list, tuple, set)):
        return set()
    return {str(item).strip().casefold() for item in genres if str(item).strip()}


def _candidate_pairs(records, titles):
    """
    Generate a bounded sorted-neighbourhood candidate set.

    The previous implementation compared every record in each release-year
    bucket with every other record in that bucket. Popular release years
    therefore produced millions of comparisons. Sorting by normalized title
    and inspecting a fixed neighbourhood keeps candidate generation near
    O(n log n), while still allowing small title spelling/format variations.
    """
    ordered = sorted(
        (i for i, title in enumerate(titles) if title),
        key=lambda i: (titles[i], _year(records[i]) or 0, i)
    )
    candidates = set()

    # Exact normalized titles are candidates regardless of year availability.
    exact_index = defaultdict(list)
    for i, title in enumerate(titles):
        if title:
            exact_index[title].append(i)

    for indices in exact_index.values():
        if len(indices) > 1:
            for pos, left in enumerate(indices):
                for right in indices[pos + 1:]:
                    if records[left].get("source_name") != records[right].get("source_name"):
                        candidates.add(tuple(sorted((left, right))))

    # Sorted-neighbourhood fallback for typographical/title formatting variants.
    for position, left in enumerate(ordered):
        upper = min(len(ordered), position + NEIGHBOR_WINDOW + 1)
        for right in ordered[position + 1:upper]:
            if records[left].get("source_name") == records[right].get("source_name"):
                continue
            left_year, right_year = _year(records[left]), _year(records[right])
            if left_year is not None and right_year is not None:
                if abs(left_year - right_year) > YEAR_TOLERANCE:
                    continue
            candidates.add((min(left, right), max(left, right)))

    return candidates


def resolve_entities(records):
    if not isinstance(records, list):
        raise ValueError("Normalized movie input must be a JSON list.")

    count = len(records)
    record_ids = [record.get("record_id") for record in records]
    if any(not record_id for record_id in record_ids):
        raise ValueError("Every normalized record must have a non-empty record_id.")
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("Duplicate record_id values found; entity assignments would be ambiguous.")

    titles = [normalize_title(record.get("movie_title")) for record in records]
    parent = list(range(count))
    members = {i: {i} for i in range(count)}

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def compatible_clusters(left_root, right_root, fuzzy=False):
        left_records = [records[i] for i in members[left_root]]
        right_records = [records[i] for i in members[right_root]]

        left_sources = {str(r.get("source_name", "Unknown")).casefold() for r in left_records}
        right_sources = {str(r.get("source_name", "Unknown")).casefold() for r in right_records}
        if left_sources & right_sources:
            return False

        # Shared authoritative identifiers must never disagree inside an entity.
        for field in ("tmdb_id", "imdb_id"):
            left_ids = {find(r, field) for r in left_records if find(r, field)}
            right_ids = {find(r, field) for r in right_records if find(r, field)}
            if left_ids and right_ids and left_ids.isdisjoint(right_ids):
                return False

        # Prevent fuzzy A-B-C chains from joining mutually dissimilar titles.
        if fuzzy:
            for left_index in members[left_root]:
                for right_index in members[right_root]:
                    a, b = titles[left_index], titles[right_index]
                    if not a or not b or similarity(a, b) < 0.85:
                        return False
                    ya, yb = _year(records[left_index]), _year(records[right_index])
                    if ya is not None and yb is not None and abs(ya - yb) > YEAR_TOLERANCE:
                        return False
        return True

    def union(left, right, fuzzy=False):
        left_root, right_root = root(left), root(right)
        if left_root == right_root:
            return True
        if not compatible_clusters(left_root, right_root, fuzzy=fuzzy):
            return False
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        members[left_root].update(members.pop(right_root))
        return True

    comparisons = []
    compared_pairs = set()
    evaluated_pair_count = 0

    # Stage 1: exact TMDB/IMDb identifier matching.
    id_index = defaultdict(list)
    for index, record in enumerate(records):
        for field in ("tmdb_id", "imdb_id"):
            identifier = find(record, field)
            if identifier:
                id_index[(field, identifier)].append(index)

    for key, indices in id_index.items():
        for position, left in enumerate(indices):
            for right in indices[position + 1:]:
                if str(records[left].get("source_name", "")).casefold() == str(
                    records[right].get("source_name", "")
                ).casefold():
                    continue
                pair = tuple(sorted((left, right)))
                if pair in compared_pairs:
                    continue
                compared_pairs.add(pair)
                evaluated_pair_count += 1
                merged = union(left, right, fuzzy=False)
                comparisons.append({
                    "left_record_id": record_ids[left],
                    "right_record_id": record_ids[right],
                    "score": 1.0,
                    "decision": "MATCH" if merged else "POSSIBLE_MATCH",
                    "method": "EXACT_IDENTIFIER" if merged else "IDENTIFIER_CONFLICT",
                    "identifier": key[0],
                    "reason": None if merged else "Cluster contains conflicting source or identifier evidence",
                })

    # Stage 2: bounded title candidates and weighted evidence scoring.
    candidate_pairs = _candidate_pairs(records, titles)
    for left, right in sorted(candidate_pairs):
        if (left, right) in compared_pairs:
            continue
        evaluated_pair_count += 1
        if str(records[left].get("source_name", "Unknown")).casefold() == str(
            records[right].get("source_name", "Unknown")
        ).casefold():
            continue

        title_left, title_right = titles[left], titles[right]
        if not title_left or not title_right:
            continue

        year_left, year_right = _year(records[left]), _year(records[right])
        if year_left is not None and year_right is not None:
            year_gap = abs(year_left - year_right)
            if year_gap > YEAR_TOLERANCE:
                continue
            year_score = 1.0 if year_gap == 0 else 0.5
        else:
            year_gap = None
            year_score = None

        title_score = similarity(title_left, title_right)
        left_genres, right_genres = _genre_set(records[left]), _genre_set(records[right])
        if left_genres and right_genres:
            union_genres = left_genres | right_genres
            genre_score = len(left_genres & right_genres) / len(union_genres) if union_genres else None
        else:
            genre_score = None

        components = [(0.80, title_score)]
        if year_score is not None:
            components.append((0.15, year_score))
        if genre_score is not None:
            components.append((0.05, genre_score))
        weight_total = sum(weight for weight, _ in components)
        score = sum(weight * value for weight, value in components) / weight_total

        conflicting_ids = any(
            find(records[left], field) and find(records[right], field)
            and find(records[left], field) != find(records[right], field)
            for field in ("tmdb_id", "imdb_id")
        )

        # When both years are unknown, demand stronger title evidence.
        threshold = 0.95 if year_left is None or year_right is None else MATCH_THRESHOLD
        merged = False
        if score >= threshold and not conflicting_ids:
            merged = union(left, right, fuzzy=True)

        if score < POSSIBLE_THRESHOLD and not conflicting_ids:
            continue

        comparisons.append({
            "left_record_id": record_ids[left],
            "right_record_id": record_ids[right],
            "score": round(score, 4),
            "decision": "MATCH" if merged else "POSSIBLE_MATCH",
            "method": "WEIGHTED_TITLE_YEAR_GENRE",
            "year": year_left,
            "year_gap": year_gap,
            "reason": (
                "Conflicting external identifiers" if conflicting_ids
                else "Cluster consistency check prevented automatic merge" if score >= threshold and not merged
                else "Insufficient evidence for automatic merge" if not merged
                else None
            ),
        })

    groups = defaultdict(list)
    for index, record in enumerate(records):
        groups[root(index)].append(record_ids[index])

    entities = []
    assignments = []
    ordered_groups = sorted(groups.values(), key=lambda group: min(map(str, group)))
    for number, member_ids in enumerate(ordered_groups, start=1):
        entity_id = f"M{number:06d}"
        entities.append({"entity_id": entity_id, "record_ids": sorted(member_ids, key=str)})
        assignments.extend(
            {"record_id": record_id, "entity_id": entity_id}
            for record_id in sorted(member_ids, key=str)
        )

    matches = [item for item in comparisons if item["decision"] == "MATCH"]
    possible = [item for item in comparisons if item["decision"] == "POSSIBLE_MATCH"]
    return {
        "matches": matches,
        "possible_matches": possible,
        "entities": entities,
        "record_assignments": assignments,
        "stats": {
            "input_records": count,
            "candidate_pairs_compared": evaluated_pair_count,
            "candidate_pairs_generated": len(candidate_pairs),
            "confirmed_matches": len(matches),
            "possible_matches": len(possible),
            "entity_count": len(entities),
        },
    }


def main():
    print("\n========== ENGINE 3: ENTITY RESOLUTION ==========")
    if not INPUT_FILE.exists():
        raise FileNotFoundError(INPUT_FILE)
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        records = json.load(file)
    result = resolve_entities(records)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(result, file, indent=4, ensure_ascii=False)
    print("\n========== ENGINE 3 REPORT ==========")
    for key, value in result["stats"].items():
        print(f"{key}: {value}")
    print("Output:", OUTPUT_FILE)
    print("Engine 3 completed successfully!")
    print("=====================================\n")


if __name__ == "__main__":
    main()
