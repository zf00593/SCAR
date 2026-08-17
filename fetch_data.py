#!/usr/bin/env python3
"""
fetch_data.py
=============

Pulls a sample from every UK earnings / cost-of-living source that has a public
API and does NOT require an access request, writing one CSV per source.

    pip install requests pandas
    python fetch_data.py                    # everything that needs no key
    python fetch_data.py --only ons nomis   # just those two
    python fetch_data.py --list             # show sources and key requirements
    python fetch_data.py --rows 2000        # raise the per-source sample cap

KEYS

Three sources need a free, instant, self-service key. No application, no
approval, no institutional affiliation. Set them as environment variables and
the relevant fetchers switch on automatically; leave them unset and those
sources are skipped with a note rather than an error.

    export NOMIS_UID=...          # optional — raises row cap from 25k to 100k
    export ADZUNA_APP_ID=...      # developer.adzuna.com
    export ADZUNA_APP_KEY=...
    export REED_API_KEY=...       # reed.co.uk/developers
    export STATXPLORE_KEY=...     # stat-xplore.dwp.gov.uk account page

DELIBERATELY NOT INCLUDED

Anything behind an access request: UK Data Service (LFS, Understanding Society,
Living Costs and Food Survey, Family Resources Survey, Wealth and Assets), and
the ONS Secure Research Service / Integrated Data Service. Those are the only
routes to genuine person-level UK income microdata, and none of them has an API.
See README.md for what you can download without an application.

WHAT YOU ACTUALLY GET

Mostly aggregates. No open API anywhere returns person-level UK earnings. The
closest to individual records here is job-advert data (Adzuna, Reed) — one row
per vacancy, with salary and location, which is a vacancy not a person.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

UA = "uk-cost-of-living-research/1.0 (+https://github.com/AmirH32)"
TIMEOUT = 60
OUT_DIR = "data"

# Per-source pause. These are free public services run on public money or
# goodwill; hammering them is both rude and a good way to get blocked.
PAUSE = 1.0


class Skip(Exception):
    """Raised when a source needs a key that isn't set."""


def _get(url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    kw.setdefault("headers", {}).setdefault("User-Agent", UA)
    r = requests.get(url, **kw)
    r.raise_for_status()
    return r


def _write(df: pd.DataFrame, name: str) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.csv")
    df.to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------- #
# 1. ONS API — inflation, housing costs, rents.  No key.
# --------------------------------------------------------------------------- #

ONS_BASE = "https://api.beta.ons.gov.uk/v1"

# Dataset ids change and some get archived. The catalogue fetcher below dumps
# every available id so you can swap these out without guessing.
ONS_DATASETS = [
    "cpih01",                                # CPIH incl. owner-occupier housing
    "index-private-housing-rental-prices",   # private rents index
]


def fetch_ons_catalogue(rows: int) -> pd.DataFrame:
    """Every dataset the ONS API currently exposes — use this to find ids."""
    out, offset = [], 0
    while True:
        r = _get(f"{ONS_BASE}/datasets", params={"limit": 100, "offset": offset}).json()
        for d in r.get("items", []):
            out.append({
                "id": d.get("id"),
                "title": d.get("title"),
                "description": (d.get("description") or "")[:300],
                "release_frequency": d.get("release_frequency"),
                "next_release": d.get("next_release"),
                "keywords": "|".join(d.get("keywords") or []),
            })
        offset += 100
        if offset >= r.get("total_count", 0) or len(out) >= rows:
            break
        time.sleep(PAUSE)
    return pd.DataFrame(out)


def fetch_ons_dataset(dataset_id: str, rows: int) -> pd.DataFrame:
    """Latest version of an ONS dataset, via its published CSV download.

    Going through the versions endpoint rather than building an /observations
    query: the CSV href is stable across datasets, whereas observation queries
    need dataset-specific dimension names that differ for every dataset.
    """
    versions = _get(f"{ONS_BASE}/datasets/{dataset_id}/editions/time-series/versions",
                    params={"limit": 1}).json()
    items = versions.get("items") or []
    if not items:
        raise RuntimeError(f"no versions returned for {dataset_id}")

    latest = items[0]
    href = (latest.get("downloads") or {}).get("csv", {}).get("href")
    if not href:
        raise RuntimeError(f"no CSV download advertised for {dataset_id}")

    csv = _get(href).content
    df = pd.read_csv(io.BytesIO(csv), low_memory=False)
    df.insert(0, "ons_dataset_id", dataset_id)
    df.insert(1, "ons_version", latest.get("version"))
    df.insert(2, "ons_release_date", latest.get("release_date"))
    return df.head(rows)


def source_ons(rows: int):
    written = []
    df = fetch_ons_catalogue(rows=10_000)
    written.append((_write(df, "ons_catalogue"), len(df),
                    "Index of every dataset on the ONS API"))
    for ds in ONS_DATASETS:
        time.sleep(PAUSE)
        try:
            d = fetch_ons_dataset(ds, rows)
            written.append((_write(d, f"ons_{ds.replace('-', '_')}"), len(d),
                            f"ONS {ds}, latest version"))
        except Exception as e:
            print(f"    ! {ds}: {type(e).__name__}: {e}", file=sys.stderr)
    return written


# --------------------------------------------------------------------------- #
# 2. Nomis — ASHE earnings by area, occupation, industry.  Optional free key.
# --------------------------------------------------------------------------- #

NOMIS_BASE = "https://www.nomisweb.co.uk/api/v01/dataset"

# NM_99_1 = ASHE workplace analysis (people working in an area)
# NM_30_1 = ASHE resident analysis  (people living in an area)
# The workplace/resident split is the only "where they work" dimension you get
# from official earnings data without an access request.
NOMIS_ASHE = {
    "ashe_workplace": "NM_99_1",
    "ashe_resident": "NM_30_1",
}

# geography TYPE480 = local authorities (districts, unitary, boroughs)
# sex=8 all, item=2 median, pay=1 gross weekly, measures=20100 value + 20701 CV
NOMIS_PARAMS = {
    "geography": "TYPE480",
    "date": "latest",
    "sex": "8",
    "item": "2",
    "pay": "1",
    "measures": "20100,20701",
}


def fetch_nomis(dataset: str, rows: int) -> pd.DataFrame:
    params = dict(NOMIS_PARAMS)
    uid = os.environ.get("NOMIS_UID")
    if uid:
        params["uid"] = uid
    url = f"{NOMIS_BASE}/{dataset}.data.csv"
    r = _get(url, params=params)
    df = pd.read_csv(io.BytesIO(r.content), low_memory=False)
    df.insert(0, "nomis_dataset", dataset)
    return df.head(rows)


def fetch_nomis_structure(dataset: str) -> pd.DataFrame:
    """Dimension codes for a Nomis dataset.

    Worth keeping alongside the data: the numeric codes above (item=2, pay=1)
    are meaningless without this, and they differ per dataset.
    """
    r = _get(f"{NOMIS_BASE}/{dataset}.def.sdmx.json").json()
    out = []
    try:
        cls = r["structure"]["codelists"]["codelist"]
    except (KeyError, TypeError):
        return pd.DataFrame()
    for cl in cls:
        for code in cl.get("code", []):
            out.append({
                "dataset": dataset,
                "codelist": cl.get("id"),
                "code_value": code.get("value"),
                "description": (code.get("description") or {}).get("value"),
            })
    return pd.DataFrame(out)


def source_nomis(rows: int):
    written = []
    if not os.environ.get("NOMIS_UID"):
        print("    note: NOMIS_UID unset — capped at ~25,000 rows per call "
              "(free key raises this to ~100,000)", file=sys.stderr)
    for name, ds in NOMIS_ASHE.items():
        try:
            df = fetch_nomis(ds, rows)
            written.append((_write(df, f"nomis_{name}"), len(df),
                            f"ASHE {name.replace('_', ' ')} ({ds}), latest year"))
            time.sleep(PAUSE)
            st = fetch_nomis_structure(ds)
            if not st.empty:
                written.append((_write(st, f"nomis_{name}_codes"), len(st),
                                f"Dimension code lookup for {ds}"))
        except Exception as e:
            print(f"    ! {ds}: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(PAUSE)
    return written


# --------------------------------------------------------------------------- #
# 3. HM Land Registry Price Paid — transaction-level house prices.  No key.
# --------------------------------------------------------------------------- #

LR_ENDPOINT = "https://landregistry.data.gov.uk/landregistry/query"

LR_QUERY = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>

SELECT ?paon ?street ?town ?county ?postcode ?amount ?date ?category
WHERE {
  ?transx lrppi:pricePaid ?amount ;
          lrppi:transactionDate ?date ;
          lrppi:propertyAddress ?addr ;
          lrppi:transactionCategory/skos:prefLabel ?category .
  ?addr lrcommon:postcode ?postcode ;
        lrcommon:town ?town .
  OPTIONAL { ?addr lrcommon:county ?county }
  OPTIONAL { ?addr lrcommon:paon ?paon }
  OPTIONAL { ?addr lrcommon:street ?street }
  FILTER (?date > "%(since)s"^^xsd:date)
}
ORDER BY DESC(?date)
LIMIT %(limit)d
"""


def source_land_registry(rows: int):
    """Recent residential sales. Transaction-level, not person-level."""
    q = LR_QUERY % {"since": "2025-01-01", "limit": min(rows, 10_000)}
    r = requests.get(
        LR_ENDPOINT,
        params={"query": q},
        headers={"Accept": "text/csv", "User-Agent": UA},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), low_memory=False)
    return [(_write(df, "land_registry_price_paid"), len(df),
             "Residential sales, England & Wales, transaction-level")]


# --------------------------------------------------------------------------- #
# 4. Adzuna — job adverts with salary and location.  Free key.
# --------------------------------------------------------------------------- #

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/gb"


def source_adzuna(rows: int):
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise Skip("set ADZUNA_APP_ID and ADZUNA_APP_KEY (free, instant, "
                   "developer.adzuna.com)")

    auth = {"app_id": app_id, "app_key": app_key}
    per_page, page, records = 50, 1, []

    while len(records) < rows and page <= 20:
        r = _get(f"{ADZUNA_BASE}/search/{page}",
                 params={**auth, "results_per_page": per_page,
                         "content-type": "application/json"}).json()
        results = r.get("results", [])
        if not results:
            break
        for j in results:
            loc = j.get("location") or {}
            records.append({
                "id": j.get("id"),
                "title": j.get("title"),
                "company": (j.get("company") or {}).get("display_name"),
                "category": (j.get("category") or {}).get("label"),
                "location": loc.get("display_name"),
                "location_area": "|".join(loc.get("area") or []),
                "latitude": j.get("latitude"),
                "longitude": j.get("longitude"),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
                # Adzuna predicts a salary when the advert omits one. Filter on
                # this before computing any average or you are averaging their
                # model's output, not advertised pay.
                "salary_is_predicted": j.get("salary_is_predicted"),
                "contract_type": j.get("contract_type"),
                "contract_time": j.get("contract_time"),
                "created": j.get("created"),
            })
        page += 1
        time.sleep(PAUSE)

    written = [(_write(pd.DataFrame(records[:rows]), "adzuna_jobs"),
                len(records[:rows]), "UK job adverts: salary, location, employer")]

    time.sleep(PAUSE)
    h = _get(f"{ADZUNA_BASE}/histogram", params={**auth, "what": ""}).json()
    hist = pd.DataFrame(sorted((h.get("histogram") or {}).items()),
                        columns=["salary_band_floor", "advert_count"])
    written.append((_write(hist, "adzuna_salary_histogram"), len(hist),
                    "Distribution of advertised salaries"))
    return written


# --------------------------------------------------------------------------- #
# 5. Reed — job adverts with salary and location.  Free key.
# --------------------------------------------------------------------------- #

REED_BASE = "https://www.reed.co.uk/api/1.0/search"


def source_reed(rows: int):
    key = os.environ.get("REED_API_KEY")
    if not key:
        raise Skip("set REED_API_KEY (free, instant, reed.co.uk/developers)")

    records, skip, take = [], 0, 100
    while len(records) < rows and skip < 1000:
        r = requests.get(REED_BASE, params={"resultsToTake": take, "resultsToSkip": skip},
                         auth=(key, ""), headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            break
        records.extend(results)
        skip += take
        time.sleep(PAUSE)

    df = pd.DataFrame(records[:rows])
    return [(_write(df, "reed_jobs"), len(df),
             "UK job adverts: salary range, location, employer")]


# --------------------------------------------------------------------------- #
# 6. DWP Stat-Xplore — benefits and pensioner income.  Free key.
# --------------------------------------------------------------------------- #

STATX_BASE = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"


def source_statxplore(rows: int):
    key = os.environ.get("STATXPLORE_KEY")
    if not key:
        raise Skip("set STATXPLORE_KEY (free, instant, Stat-Xplore account page)")

    headers = {"APIKey": key, "User-Agent": UA}
    schema = requests.get(f"{STATX_BASE}/schema", headers=headers,
                          timeout=TIMEOUT)
    schema.raise_for_status()

    # The schema listing only, not a table query: /table needs dataset-specific
    # measure and field ids, and guessing them produces confident nonsense.
    # Browse this CSV, pick an id, then build your query from its /schema/{id}.
    items = schema.json().get("children", [])
    df = pd.DataFrame([{"id": i.get("id"), "label": i.get("label"),
                        "type": i.get("type")} for i in items])

    rate = requests.get(f"{STATX_BASE}/rate_limit", headers=headers, timeout=TIMEOUT)
    if rate.ok:
        print(f"    rate limit: {rate.json()}", file=sys.stderr)

    return [(_write(df, "statxplore_schema"), len(df),
             "Stat-Xplore dataset index — pick an id, then query /table")]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

SOURCES = {
    "ons": (source_ons, "ONS API — CPIH inflation, private rents", "no key"),
    "nomis": (source_nomis, "Nomis — ASHE earnings by area/workplace", "optional key"),
    "landregistry": (source_land_registry, "HM Land Registry — house prices", "no key"),
    "adzuna": (source_adzuna, "Adzuna — job adverts, salary + location", "free key"),
    "reed": (source_reed, "Reed — job adverts, salary + location", "free key"),
    "statxplore": (source_statxplore, "DWP Stat-Xplore — benefits/income", "free key"),
}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="+", choices=list(SOURCES),
                   help="fetch only these sources")
    p.add_argument("--rows", type=int, default=1000,
                   help="max rows to keep per source (default 1000)")
    p.add_argument("--out-dir", default="data")
    p.add_argument("--list", action="store_true", help="list sources and exit")
    args = p.parse_args()

    if args.list:
        print(f"{'source':<14}{'key':<15}description")
        for k, (_, desc, key) in SOURCES.items():
            print(f"{k:<14}{key:<15}{desc}")
        return

    global OUT_DIR
    OUT_DIR = args.out_dir

    todo = args.only or list(SOURCES)
    manifest, skipped = [], []

    for name in todo:
        fn, desc, _ = SOURCES[name]
        print(f"\n[{name}] {desc}")
        try:
            for path, n, note in fn(args.rows):
                print(f"    {path}  ({n:,} rows)")
                manifest.append({"source": name, "file": os.path.basename(path),
                                 "rows": n, "description": note,
                                 "fetched_utc": datetime.now(timezone.utc).isoformat()})
        except Skip as e:
            print(f"    skipped — {e}")
            skipped.append(name)
        except Exception as e:
            print(f"    FAILED — {type(e).__name__}: {e}", file=sys.stderr)
            skipped.append(name)
        time.sleep(PAUSE)

    if manifest:
        m = pd.DataFrame(manifest)
        m.to_csv(os.path.join(OUT_DIR, "_manifest.csv"), index=False)
        print(f"\nWrote {len(manifest)} files to {OUT_DIR}/ "
              f"({m['rows'].sum():,} rows total)")
        print(f"Manifest: {OUT_DIR}/_manifest.csv")
    if skipped:
        print(f"Skipped: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
