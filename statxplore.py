#!/usr/bin/env python3
"""
statxplore_fetch.py
===================

DWP Stat-Xplore extractor, rewritten to report why a query failed instead of
swallowing the reason.

    export STATXPLORE_KEY=...
    python statxplore_fetch.py --check              # auth + rate limit only
    python statxplore_fetch.py --explore FRSPP      # dump one database's fields
    python statxplore_fetch.py                      # fetch the configured set
    python statxplore_fetch.py --only FRSPP HBAI_ADMIN

WHY THE PREVIOUS VERSION FAILED SILENTLY

`response.raise_for_status()` throws away the response body. Stat-Xplore puts
its actual complaint in that body as JSON — "Table too large", "Invalid
dimension", "Rate limit exceeded". The old code caught the exception and
printed only "Error fetching X: 400 Client Error: Bad Request", which tells you
nothing. Every request here prints the server's own message on failure.

THE FOUR THINGS THAT ACTUALLY BREAK THESE QUERIES

1. Rate limit. Stat-Xplore enforces a per-key quota. The old script made a
   recursive schema walk PER DATABASE (dozens of GETs each) before every query,
   so it could burn the quota on discovery and have nothing left for tables.
   This version caches schemas to disk and checks /rate_limit as it goes.

2. Table too large. Cells = product of item counts across all dimensions.
   Year x Region x Sex x Age x Ethnicity is easily hundreds of thousands of
   cells and gets rejected outright. This version estimates the cell count
   BEFORE sending and drops dimensions until it fits.

3. Wrong object type as a dimension. The old get_field_uri() fell back to
   `matches[0]` regardless of type, so a MEASURE could end up in the dimensions
   list, which Stat-Xplore rejects. Dimensions here are type-checked.

4. Duplicate dimensions. Two search terms often resolve to the same field
   ("region" and "geography" both hitting GVTREGN), and sending a field twice
   is an error. Deduplicated here.

WHAT YOU GET

Aggregated tabulations, not person-level records. Cells below disclosure
thresholds come back null by design, so a sparse table is usually correct
behaviour rather than a bug — see the null_pct column in the manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from itertools import product

import pandas as pd
import requests

BASE_URL = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"
OUTPUT_DIR = "data/statxplore"
CACHE_DIR = os.path.join(OUTPUT_DIR, "_schema_cache")

# Stat-Xplore rejects oversized tables. The documented ceiling has moved around,
# so this is a deliberately conservative local cap — raise it if your queries
# succeed comfortably.
MAX_CELLS = 100_000
PAUSE = 0.5


class StatXploreError(RuntimeError):
    """Carries the server's own explanation, not just the HTTP status."""


class StatXploreClient:
    def __init__(self, api_key: str, verbose: bool = True):
        if not api_key:
            raise StatXploreError("STATXPLORE_KEY is not set")
        self.verbose = verbose
        self.calls = 0
        self.session = requests.Session()
        self.session.headers.update({
            "APIKey": api_key,            # NOT "Authorization: Bearer" — that
            "Accept": "application/json",  # silently returns 401 on this API
            "Accept-Language": "en",
        })

    # -- plumbing --------------------------------------------------------- #

    def _check(self, r: requests.Response, what: str):
        """Raise with the server's message rather than a bare status code."""
        self.calls += 1
        if r.ok:
            return r.json()

        detail = ""
        try:
            body = r.json()
            detail = body.get("message") or body.get("error") or json.dumps(body)[:400]
        except Exception:
            detail = (r.text or "")[:400]

        hint = ""
        if r.status_code == 401:
            hint = "  -> key rejected. Header must be 'APIKey', not 'Authorization'."
        elif r.status_code == 403:
            hint = "  -> often the rate limit, not permissions. Run --check."
        elif r.status_code == 429:
            hint = "  -> rate limited. Wait, then re-run with fewer datasets."
        elif r.status_code == 400:
            hint = "  -> malformed query: bad dimension/measure id, duplicate " \
                   "dimension, or table too large."

        raise StatXploreError(f"{what}: HTTP {r.status_code} — {detail}{hint}")

    def get(self, path: str):
        r = self.session.get(f"{BASE_URL}{path}", timeout=90)
        return self._check(r, f"GET {path}")

    def rate_limit(self):
        try:
            return self.get("/rate_limit")
        except StatXploreError:
            return None

    # -- schema, cached --------------------------------------------------- #

    def get_schema(self, schema_id: str):
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache = os.path.join(CACHE_DIR, schema_id.replace(":", "_") + ".json")
        if os.path.exists(cache):
            with open(cache) as f:
                return json.load(f)

        schema = self.get(f"/schema/{schema_id}")
        with open(cache, "w") as f:
            json.dump(schema, f)
        time.sleep(PAUSE)
        return schema

    # -- tables ----------------------------------------------------------- #

    def query_table(self, database: str, dimensions: list, measures: list):
        payload = {"database": database, "measures": measures,
                   "dimensions": dimensions}
        if self.verbose:
            print(f"    POST /table  {len(dimensions)} dims, "
                  f"{len(measures)} measure(s)")
        r = self.session.post(f"{BASE_URL}/table", json=payload,
                              headers={"Content-Type": "application/json"},
                              timeout=180)
        return self._check(r, f"POST /table [{database}]")


# --------------------------------------------------------------------------- #
# Schema walking
# --------------------------------------------------------------------------- #

def walk(client, schema_id, seen=None, depth=0, max_depth=4):
    """Collect FIELD/MEASURE/COUNT objects below a schema node.

    Depth-capped: some folders self-reference, and the original unbounded walk
    could spend a large slice of the rate limit before any table was requested.
    """
    seen = seen if seen is not None else set()
    if schema_id in seen or depth > max_depth:
        return []
    seen.add(schema_id)

    try:
        schema = client.get_schema(schema_id)
    except StatXploreError as e:
        print(f"      ! {e}", file=sys.stderr)
        return []

    out = []
    for child in schema.get("children", []):
        ctype, cid = child.get("type"), child.get("id")
        if not cid:
            continue
        if ctype in ("FIELD", "MEASURE", "COUNT"):
            out.append(child)
        elif ctype in ("GROUP", "FOLDER"):
            out.extend(walk(client, cid, seen, depth + 1, max_depth))
    return out


def field_size(client, field_id: str) -> int:
    """Number of selectable items in a field — needed to size a table."""
    try:
        schema = client.get_schema(field_id)
    except StatXploreError:
        return 0
    return len(schema.get("children", []))


def pick_field(objects, *terms):
    """First FIELD whose id or label matches any term. Type-checked.

    The old version fell back to matches[0] regardless of type, so a MEASURE
    could be sent as a dimension — which Stat-Xplore rejects with a 400 that
    the old error handling hid.
    """
    for term in terms:
        t = term.lower()
        for o in objects:
            if o.get("type") != "FIELD":
                continue
            if t in str(o.get("id", "")).lower() or t in str(o.get("label", "")).lower():
                return o
    return None


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #

def flatten(values, prefix=()):
    if not isinstance(values, list):
        return [(prefix, values)]
    rows = []
    for i, child in enumerate(values):
        rows.extend(flatten(child, prefix + (i,)))
    return rows


def parse_table(response) -> pd.DataFrame:
    fields, cubes = response.get("fields", []), response.get("cubes", {})
    if not fields or not cubes:
        raise StatXploreError("response contained no fields or no cubes")

    dims = []
    for f in fields:
        items = []
        for it in f.get("items", []):
            if isinstance(it, dict):
                labels = it.get("labels") or []
                items.append({"label": (labels[0] if labels else it.get("label"))
                                       or it.get("id"),
                              "uri": it.get("uri", it.get("id"))})
            else:
                items.append({"label": str(it), "uri": it})
        dims.append({"label": f.get("label", f.get("id")), "items": items})

    coords = list(product(*[range(len(d["items"])) for d in dims]))
    frame = {}
    for d in dims:
        frame[d["label"]] = []

    rows = {}
    for measure_uri, cube in cubes.items():
        values = (cube or {}).get("values")
        if values is None:
            continue
        vmap = {k: v for k, v in flatten(values)}
        for c in coords:
            key = c
            if key not in rows:
                rows[key] = {dims[i]["label"]: dims[i]["items"][ix]["label"]
                             for i, ix in enumerate(c)}
            rows[key][measure_uri] = vmap.get(c)

    return pd.DataFrame(list(rows.values()))


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

DATASETS = [
    {"label": "FRS_INDIVIDUAL", "id": "str:database:FRSPP",
     "dims": [("year",), ("ageband", "age"), ("sex", "gender")]},
    {"label": "FRS_ADULT", "id": "str:database:FRSAD",
     "dims": [("year",), ("ageband", "age"), ("sex", "gender")]},
    {"label": "FRS_HOUSEHOLD", "id": "str:database:FRSHH",
     "dims": [("year",), ("geograph", "region")]},
    {"label": "HBAI_ADMIN", "id": "str:database:HBAI_ADMIN",
     "dims": [("year",), ("region", "gvtregn"), ("sex",)]},
    {"label": "PI_ADMIN", "id": "str:database:PI_ADMIN",
     "dims": [("year",), ("region", "gvtregn")]},
    {"label": "UC_PEOPLE", "id": "str:database:UC_Monthly",
     "dims": [("month", "date"), ("geograph",), ("gender", "sex")]},
    {"label": "UC_HOUSEHOLDS", "id": "str:database:UC_Households",
     "dims": [("month", "date"), ("geograph",)]},
    {"label": "HOUSING_BENEFIT", "id": "str:database:hb_new",
     "dims": [("geograph",), ("age",)]},
]


def build_query(client, cfg):
    """Resolve dimensions and a measure, and size the table before sending."""
    objects = walk(client, cfg["id"])
    if not objects:
        raise StatXploreError("no fields discovered — check the database id")

    fields, chosen, seen_ids = [], [], set()
    for terms in cfg["dims"]:
        f = pick_field(objects, *terms)
        if not f:
            print(f"      no field matched {terms}")
            continue
        if f["id"] in seen_ids:          # duplicate dimension = 400
            continue
        seen_ids.add(f["id"])
        n = field_size(client, f["id"]) or 1
        fields.append((f, n))

    if not fields:
        raise StatXploreError("no usable dimensions resolved")

    # Drop the largest dimension until the table fits.
    fields.sort(key=lambda x: x[1])
    while fields:
        cells = 1
        for _, n in fields:
            cells *= max(n, 1)
        if cells <= MAX_CELLS:
            break
        dropped, _ = fields.pop()
        print(f"      dropping '{dropped.get('label')}' — table would be "
              f"{cells:,} cells (cap {MAX_CELLS:,})")

    chosen = [[f["id"]] for f, _ in fields]
    cells = 1
    for _, n in fields:
        cells *= max(n, 1)

    measures = [o["id"] for o in objects if o.get("type") == "MEASURE"]
    counts = [o["id"] for o in objects if o.get("type") == "COUNT"]
    measure = (measures or counts)[:1]
    if not measure:
        raise StatXploreError("no measure or count available")

    return chosen, measure, cells, [f.get("label") for f, _ in fields]


def fetch(client, cfg):
    print(f"\n[{cfg['label']}] {cfg['id']}")
    dims, measure, cells, labels = build_query(client, cfg)
    print(f"    dimensions: {labels}  (~{cells:,} cells)")

    for attempt in range(3):
        try:
            resp = client.query_table(cfg["id"], dims, measure)
            break
        except StatXploreError as e:
            if "429" in str(e) and attempt < 2:
                wait = 20 * (attempt + 1)
                print(f"    rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            raise

    df = parse_table(resp)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{cfg['label']}.csv")
    df.to_csv(path, index=False)

    measure_cols = [c for c in df.columns if c.startswith("str:")]
    null_pct = round(df[measure_cols].isna().mean().mean() * 100, 1) if measure_cols else None
    print(f"    saved {len(df):,} rows -> {path}"
          + (f"  ({null_pct}% of values suppressed/null)" if null_pct is not None else ""))
    return {"dataset": cfg["label"], "rows": len(df), "columns": len(df.columns),
            "cells_requested": cells, "null_pct": null_pct,
            "file": os.path.basename(path),
            "fetched_utc": datetime.now(timezone.utc).isoformat()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="+", help="dataset labels to fetch")
    p.add_argument("--check", action="store_true", help="auth + rate limit, then exit")
    p.add_argument("--explore", help="dump one database's fields and exit")
    p.add_argument("--max-cells", type=int, default=MAX_CELLS)
    args = p.parse_args()

    globals()["MAX_CELLS"] = args.max_cells

    client = StatXploreClient(os.environ.get("STATXPLORE_KEY", ""))

    rl = client.rate_limit()
    print(f"rate limit: {rl}" if rl else "rate limit: endpoint returned nothing")
    if args.check:
        client.get("/schema")
        print("auth OK — key accepted, schema readable")
        return

    if args.explore:
        db = args.explore if args.explore.startswith("str:") else f"str:database:{args.explore}"
        objs = walk(client, db)
        rows = [{"type": o.get("type"), "id": o.get("id"), "label": o.get("label")}
                for o in objs]
        df = pd.DataFrame(rows).sort_values(["type", "label"])
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out = os.path.join(OUTPUT_DIR, f"_fields_{args.explore.replace(':', '_')}.csv")
        df.to_csv(out, index=False)
        print(df.to_string(index=False))
        print(f"\n{len(df)} objects -> {out}")
        return

    todo = [d for d in DATASETS if not args.only or d["label"] in args.only]
    manifest, failed = [], []
    for cfg in todo:
        try:
            manifest.append(fetch(client, cfg))
        except StatXploreError as e:
            print(f"    FAILED — {e}", file=sys.stderr)
            failed.append((cfg["label"], str(e)))
        except Exception as e:
            print(f"    FAILED — {type(e).__name__}: {e}", file=sys.stderr)
            failed.append((cfg["label"], f"{type(e).__name__}: {e}"))
        time.sleep(PAUSE)

    if manifest:
        pd.DataFrame(manifest).to_csv(os.path.join(OUTPUT_DIR, "_manifest.csv"),
                                      index=False)
        print(f"\n{len(manifest)} datasets saved, {client.calls} API calls used")
    if failed:
        print("\nFailed:")
        for label, why in failed:
            print(f"  {label}: {why[:160]}")
    rl = client.rate_limit()
    if rl:
        print(f"rate limit remaining: {rl}")


if __name__ == "__main__":
    main()
