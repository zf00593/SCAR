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
#
# date: "latest" gives one year only. Use "*" for EVERY year Nomis holds —
# ASHE workplace (NM_99_1) runs from 1998, resident (NM_30_1) from 2002.
# Other accepted forms: "latestMINUS5", "2015-2025", "2019,2020,2021".
NOMIS_PARAMS = {
    "geography": "TYPE480",
    "date": "*",
    "sex": "8",
    "item": "2",
    "pay": "1",
    "measures": "20100,20701",
}

# Row caps per call: ~25,000 as a guest, ~100,000 with a free uid key. Asking
# for every year x every local authority exceeds the guest cap, so paginate.
NOMIS_PAGE = 24_000


def fetch_nomis_dates(dataset: str) -> pd.DataFrame:
    """Every time period the dataset holds.

    Call this before a big pull so you know what "*" is about to return, and so
    you can slice it into year ranges if the full series is too large.
    """
    r = _get(f"{NOMIS_BASE}/{dataset}/time.def.sdmx.json").json()
    out = []
    try:
        codes = r["structure"]["codelists"]["codelist"][0]["code"]
    except (KeyError, IndexError, TypeError):
        return pd.DataFrame()
    for c in codes:
        out.append({"dataset": dataset, "date": c.get("value"),
                    "description": (c.get("description") or {}).get("value")})
    return pd.DataFrame(out)


def fetch_nomis(dataset: str, rows: int, date: str | None = None) -> pd.DataFrame:
    """Fetch a Nomis dataset, paginating until the server stops returning rows.

    Nomis truncates silently at the row cap — you get a valid CSV that is simply
    incomplete, with no error and no warning. Paginating with RecordOffset is
    the only way to know you have everything.
    """
    params = dict(NOMIS_PARAMS)
    if date:
        params["date"] = date
    uid = os.environ.get("NOMIS_UID")
    if uid:
        params["uid"] = uid

    page_size = min(NOMIS_PAGE if not uid else 95_000, rows)
    frames, offset = [], 0

    while offset < rows:
        params["RecordLimit"] = min(page_size, rows - offset)
        params["RecordOffset"] = offset
        r = _get(f"{NOMIS_BASE}/{dataset}.data.csv", params=params)
        chunk = pd.read_csv(io.BytesIO(r.content), low_memory=False)
        if chunk.empty:
            break
        frames.append(chunk)
        got = len(chunk)
        print(f"      offset {offset:,} -> {got:,} rows")
        if got < params["RecordLimit"]:
            break                      # short page = last page
        offset += got
        time.sleep(PAUSE)

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
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
            dates = fetch_nomis_dates(ds)
            if not dates.empty:
                written.append((_write(dates, f"nomis_{name}_dates"), len(dates),
                                f"Every time period available in {ds}"))
                print(f"    {ds}: {len(dates)} periods "
                      f"({dates['date'].iloc[0]}..{dates['date'].iloc[-1]})")
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
SOURCES = {
    "ons": (source_ons, "ONS API — CPIH inflation, private rents", "no key"),
    "nomis": (source_nomis, "Nomis — ASHE earnings by area/workplace", "optional key"),
    "landregistry": (source_land_registry, "HM Land Registry — house prices", "no key"),
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
