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


def _is_unlimited(rows: int) -> bool:
    """Treat rows<=0 as no cap."""
    return rows <= 0


def _cap(df: pd.DataFrame, rows: int) -> pd.DataFrame:
    """Apply an optional row cap to a dataframe."""
    if _is_unlimited(rows):
        return df
    return df.head(rows)


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
# 1. ONS API — inflation and city-level housing prices.  No key.
# --------------------------------------------------------------------------- #

ONS_BASE = "https://api.beta.ons.gov.uk/v1"

# Dataset ids change and some get archived. The catalogue fetcher below dumps
# every available id so you can swap these out without guessing.
ONS_DATASETS = [
    "cpih01",                      # CPIH incl. owner-occupier housing
    "house-prices-local-authority", # local-authority house prices
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
    return _cap(df, rows)


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
# date: LEAVE IT OUT to get every period. Nomis treats an omitted dimension as
# "all values"; "*" is NOT valid for date and makes the server return HTTP 200
# with an empty body — no error message. (Confirmed by --nomis-probe: every
# filter validates with date=latest, and only date="*" empties the response.)
#
# This code fetches year by year using an explicit list from the time codelist,
# which is more robust than omitting the parameter: each request stays small,
# a bad year fails alone instead of killing the whole pull, and you can see
# progress. Verified period counts:
#   NM_99_1 (workplace) 1997-2025 = 29 periods
#   NM_30_1 (resident)  2002-2025 = 24 periods
# Other valid forms: "latest", "latestMINUS5", "2019,2020,2021".
NOMIS_YEARS_PER_REQUEST = 5

NOMIS_PARAMS = {
    "geography": "TYPE482",
    "sex": "8",
    "item": "2",
    "pay": "1",
    "measures": "20100,20701",
}

# Row caps per call: ~25,000 as a guest, ~100,000 with a free uid key. Asking
# for every year x every local authority exceeds the guest cap, so paginate.
NOMIS_PAGE = 24_000
NOMIS_DETAIL = False

# Rough row count for a full pull, so you can see before you fetch whether the
# guest cap will force many pages:
#   periods x geographies x sex x item x pay x measures
# 29 x ~380 local authorities x 1 x 1 x 1 x 2 = ~22,000 rows for workplace.
# Widening sex/item/pay multiplies that fast — see NOMIS_PARAMS_DETAIL below.
GEOG_COUNT_ESTIMATE = {"TYPE482": 300}

# Wider pull: all sexes (5 male, 6 female, 8 total), all pay measures, all
# items (mean/median/percentiles). Roughly 40x the rows — only worth it with a
# NOMIS_UID key, and expect ~25 pages.
NOMIS_PARAMS_DETAIL = {
    "geography": "TYPE482",
    "sex": "5,6,8",
    "item": "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20",
    "pay": "1,2,3,4,5,6,7",
    "measures": "20100,20701",
}


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


def fetch_nomis_all_years(dataset: str, rows: int, detail: bool = False) -> pd.DataFrame:
    """Every year Nomis holds, fetched in small explicit batches.

    Reads the time codelist, then requests years in groups of
    NOMIS_YEARS_PER_REQUEST. Batching rather than one big request means a single
    unavailable year degrades that batch only, and each response stays well
    under the row cap.
    """
    dates = fetch_nomis_dates(dataset)
    if dates.empty:
        print("      no time codelist — falling back to date=latest")
        return fetch_nomis(dataset, rows, date="latest", detail=detail)

    years = [str(y) for y in dates["date"].tolist()]
    print(f"      {len(years)} periods: {years[0]}..{years[-1]}")

    frames, failures = [], []
    for i in range(0, len(years), NOMIS_YEARS_PER_REQUEST):
        batch = years[i:i + NOMIS_YEARS_PER_REQUEST]
        if _is_unlimited(rows):
            remaining = 2_000_000_000
        else:
            remaining = rows - sum(len(f) for f in frames)
            if remaining <= 0:
                print(f"      stopping at --rows {rows:,}; "
                      f"{len(years) - i} periods not fetched")
                break
        try:
            part = fetch_nomis(dataset, remaining, date=",".join(batch), detail=detail)
            if not part.empty:
                frames.append(part)
                print(f"      {batch[0]}-{batch[-1]}: {len(part):,} rows")
            else:
                failures.append((batch, "empty"))
        except Exception as e:
            failures.append((batch, f"{type(e).__name__}: {str(e)[:60]}"))
            print(f"      {batch[0]}-{batch[-1]}: FAILED {type(e).__name__}",
                  file=sys.stderr)
        time.sleep(PAUSE)

    if failures:
        print(f"      {len(failures)} batch(es) failed: "
              f"{[b[0][0] + '-' + b[0][-1] for b in failures]}", file=sys.stderr)
    if not frames:
        return pd.DataFrame()
    return _cap(pd.concat(frames, ignore_index=True), rows)


def fetch_nomis(dataset: str, rows: int, date: str | None = None,
                detail: bool = False) -> pd.DataFrame:
    """Fetch a Nomis dataset, paginating until the server stops returning rows.

    Nomis truncates silently at the row cap — you get a valid CSV that is simply
    incomplete, with no error and no warning. Paginating with RecordOffset is
    the only way to know you have everything.
    """
    params = dict(NOMIS_PARAMS_DETAIL if detail else NOMIS_PARAMS)
    if date:
        params["date"] = date
    uid = os.environ.get("NOMIS_UID")
    if uid:
        params["uid"] = uid

    target_rows = rows if not _is_unlimited(rows) else 2_000_000_000
    page_size = min(NOMIS_PAGE if not uid else 95_000, target_rows)
    frames, offset = [], 0

    while offset < target_rows:
        params["RecordLimit"] = min(page_size, target_rows - offset)
        params["RecordOffset"] = offset
        r = _get(f"{NOMIS_BASE}/{dataset}.data.csv", params=params)
        if not r.content.strip():
            # Nomis returns HTTP 200 with an EMPTY BODY when a dimension code is
            # invalid — no error, no message. Surface the request so the bad
            # code is visible instead of a bare EmptyDataError.
            raise RuntimeError(
                f"Nomis returned an empty body — usually an invalid dimension "
                f"code.\n      URL: {r.url}\n"
                f"      Run: python fetch_data.py --nomis-probe {dataset}")
        try:
            chunk = pd.read_csv(io.BytesIO(r.content), low_memory=False)
        except pd.errors.EmptyDataError:
            raise RuntimeError(
                f"Nomis body had no parseable CSV.\n      URL: {r.url}\n"
                f"      First bytes: {r.content[:200]!r}")
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
    return _cap(df, rows)


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


def nomis_probe(dataset: str):
    """Find which dimension code is making Nomis return an empty body.

    Strategy: start from the minimum query that must work (geography + one date
    + measures), then add filters one at a time. The first addition that empties
    the response is the culprit. Also prints the valid codes for each dimension
    so you can pick a real one.
    """
    uid = os.environ.get("NOMIS_UID")
    base = {"geography": "TYPE480", "date": "latest", "measures": "20100"}
    if uid:
        base["uid"] = uid

    print(f"\n=== probing {dataset} ===")
    st = fetch_nomis_structure(dataset)
    if not st.empty:
        for cl, grp in st.groupby("codelist"):
            if any(k in cl.upper() for k in ("SEX", "ITEM", "PAY", "MEASURE")):
                codes = grp.head(12)[["code_value", "description"]].values.tolist()
                print(f"\n  {cl}:")
                for v, d in codes:
                    print(f"      {v:<6} {d}")
                if len(grp) > 12:
                    print(f"      ... {len(grp) - 12} more")

    def try_params(label, params):
        try:
            r = _get(f"{NOMIS_BASE}/{dataset}.data.csv", params=params)
            n = len(r.content.strip().splitlines())
            status = f"{max(n - 1, 0):,} rows" if n > 1 else "EMPTY BODY"
            print(f"  {label:<38} {status}")
            return n > 1
        except Exception as e:
            print(f"  {label:<38} {type(e).__name__}: {str(e)[:60]}")
            return False

    print("\n  building the query up one filter at a time:")
    ok = try_params("geography + date + measures", base)
    if not ok:
        print("\n  Even the minimal query is empty — check the geography code "
              "(TYPE480) and that the dataset id is right.")
        return

    for key, value in (("sex", NOMIS_PARAMS["sex"]),
                       ("item", NOMIS_PARAMS["item"]),
                       ("pay", NOMIS_PARAMS["pay"])):
        trial = dict(base)
        trial[key] = value
        if not try_params(f"+ {key}={value}", trial):
            print(f"\n  >>> '{key}={value}' is the invalid code. "
                  f"Pick a valid one from the codelist above and update "
                  f"NOMIS_PARAMS['{key}'].")
            return

    full = dict(base, **{k: v for k, v in NOMIS_PARAMS.items() if k != "date"})
    try_params("all filters together", full)

    # The filters were never the problem in practice — the date form was.
    print("\n  date forms:")
    for label, value in (("date=latest", "latest"), ("date=* (all)", "*"),
                         ("date omitted", None), ("date=2024,2025", "2024,2025")):
        trial = dict(full)
        if value is None:
            trial.pop("date", None)
        else:
            trial["date"] = value
        try_params(f"  {label}", trial)
    print("\n  Use whichever returned rows. This code batches explicit years, "
          "which works regardless of whether '*' is supported.")


def source_nomis(rows: int):
    written = []
    if not os.environ.get("NOMIS_UID"):
        print("    note: NOMIS_UID unset — capped at ~25,000 rows per call "
              "(free key raises this to ~100,000)", file=sys.stderr)
    for name, ds in NOMIS_ASHE.items():
        # Codes and dates first: if the data query fails, these are exactly what
        # you need to work out why, so they must not share its try block.
        try:
            st = fetch_nomis_structure(ds)
            if not st.empty:
                written.append((_write(st, f"nomis_{name}_codes"), len(st),
                                f"Dimension code lookup for {ds}"))
        except Exception as e:
            print(f"    ! codes for {ds}: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(PAUSE)

        try:
            dates = fetch_nomis_dates(ds)
            if not dates.empty:
                written.append((_write(dates, f"nomis_{name}_dates"), len(dates),
                                f"Every time period available in {ds}"))
                print(f"    {ds}: {len(dates)} periods "
                      f"({dates['date'].iloc[0]}..{dates['date'].iloc[-1]})")
            n_periods = len(dates) if not dates.empty else 1
            geo = NOMIS_PARAMS.get("geography", "")
            est = n_periods * GEOG_COUNT_ESTIMATE.get(geo, 380) * 2
            print(f"    estimated ~{est:,} rows for a full pull "
                  f"(--rows is currently {rows:,})")
            if not _is_unlimited(rows) and rows < est:
                print(f"    WARNING: --rows {rows:,} will cut this short. "
                      f"Use --rows {est * 2:,} to be safe.")
            df = fetch_nomis_all_years(ds, rows, detail=NOMIS_DETAIL)
            written.append((_write(df, f"nomis_{name}"), len(df),
                            f"ASHE {name.replace('_', ' ')} ({ds}), all years"))
        except Exception as e:
            print(f"    ! {ds}: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(PAUSE)
    return written

# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

SOURCES = {
    "ons": (source_ons, "ONS API — CPIH inflation, local-authority house prices", "no key"),
    "nomis": (source_nomis, "Nomis — ASHE earnings by area/workplace", "optional key"),
}


class FetchDataPipeline:
    """Class-based runner for source pulls and post-fetch harmonization."""

    def __init__(self, out_dir: str, pause_seconds: float = PAUSE):
        self.out_dir = out_dir
        self.pause_seconds = pause_seconds

    def _extract_year_series(self, df: pd.DataFrame) -> pd.Series | None:
        """Extract year values from known time columns."""
        if "DATE_NAME" in df.columns:
            s = pd.to_numeric(df["DATE_NAME"], errors="coerce").dropna().astype(int)
            return s if not s.empty else None
        if "DATE" in df.columns:
            s = pd.to_numeric(df["DATE"], errors="coerce").dropna().astype(int)
            return s if not s.empty else None
        if "Year" in df.columns:
            s = pd.to_numeric(df["Year"], errors="coerce").dropna().astype(int)
            return s if not s.empty else None
        if "calendar-years" in df.columns:
            s = pd.to_numeric(df["calendar-years"], errors="coerce").dropna().astype(int)
            return s if not s.empty else None
        if "Time" in df.columns:
            t = df["Time"].astype(str).str.strip()
            parsed = pd.to_datetime(t, format="%b-%y", errors="coerce")
            if parsed.notna().any():
                return parsed.dt.year.dropna().astype(int)
            numeric = pd.to_numeric(t, errors="coerce").dropna().astype(int)
            return numeric if not numeric.empty else None
        return None

    def _filter_to_years(self, df: pd.DataFrame, years: set[int]) -> pd.DataFrame:
        """Filter a dataframe to a common set of years using its time column."""
        if "DATE_NAME" in df.columns:
            y = pd.to_numeric(df["DATE_NAME"], errors="coerce")
            return df[y.isin(years)].copy()
        if "DATE" in df.columns:
            y = pd.to_numeric(df["DATE"], errors="coerce")
            return df[y.isin(years)].copy()
        if "Year" in df.columns:
            y = pd.to_numeric(df["Year"], errors="coerce")
            return df[y.isin(years)].copy()
        if "calendar-years" in df.columns:
            y = pd.to_numeric(df["calendar-years"], errors="coerce")
            return df[y.isin(years)].copy()
        if "Time" in df.columns:
            t = df["Time"].astype(str).str.strip()
            parsed = pd.to_datetime(t, format="%b-%y", errors="coerce")
            if parsed.notna().any():
                return df[parsed.dt.year.isin(years)].copy()
            numeric = pd.to_numeric(t, errors="coerce")
            return df[numeric.isin(years)].copy()
        return df.copy()

    def align_common_time_range(self, manifest_rows: list[dict]) -> None:
        """Align time-aware CSVs to the common overlapping year range in place."""
        candidates = []
        for row in manifest_rows:
            file_name = row["file"]
            if file_name == "_manifest.csv":
                continue
            if any(k in file_name for k in ("catalogue", "_codes")):
                continue
            if not file_name.endswith(".csv"):
                continue
            candidates.append(os.path.join(self.out_dir, file_name))

        if not candidates:
            print("\n[align] No candidate files for time-range alignment.")
            return

        years_by_file: dict[str, set[int]] = {}
        for path in candidates:
            try:
                df = pd.read_csv(path, low_memory=False)
            except Exception as e:
                print(f"[align] Skipping {os.path.basename(path)}: {type(e).__name__}: {e}")
                continue
            years = self._extract_year_series(df)
            if years is None or years.empty:
                continue
            years_by_file[path] = set(years.tolist())

        if len(years_by_file) < 2:
            print("\n[align] Not enough time-aware files to compute a common range.")
            return

        print("\n[align] Time coverage before alignment:")
        for path in sorted(years_by_file):
            ys = sorted(years_by_file[path])
            print(f"[align] {os.path.basename(path)}: {ys[0]}-{ys[-1]} ({len(ys)} years)")

        common_years = set.intersection(*years_by_file.values())
        if not common_years:
            print("\n[align] No overlapping years across time-aware files.")
            return

        year_min, year_max = min(common_years), max(common_years)
        print(f"\n[align] Common year range across fetched time-series: {year_min}-{year_max}")

        for path in sorted(years_by_file):
            df = pd.read_csv(path, low_memory=False)
            filtered = self._filter_to_years(df, common_years)
            before_rows = len(df)
            filtered.to_csv(path, index=False)
            print(f"[align] {os.path.basename(path)} rows: {before_rows:,} -> {len(filtered):,}")

    def split_large_csv_files(
        self,
        manifest_rows: list[dict],
        split_targets: list[str],
        split_rows: int,
        delete_original: bool,
    ) -> None:
        """Split large CSV files into smaller parts for repo-friendly storage."""
        if split_rows <= 0:
            print("\n[split] split rows must be > 0; skipping split step.")
            return

        target_set = {t.strip() for t in split_targets if t and t.strip()}
        if not target_set:
            print("\n[split] No target files configured; skipping split step.")
            return

        seen = set()
        split_any = False
        for row in manifest_rows:
            file_name = row.get("file", "")
            if file_name not in target_set or file_name in seen:
                continue
            seen.add(file_name)

            path = os.path.join(self.out_dir, file_name)
            if not os.path.exists(path):
                print(f"[split] {file_name}: file missing, skipping")
                continue

            df = pd.read_csv(path, low_memory=False)
            total = len(df)
            if total <= split_rows:
                print(f"[split] {file_name}: {total:,} rows <= {split_rows:,}, no split needed")
                continue

            parts = (total + split_rows - 1) // split_rows
            base = file_name[:-4] if file_name.lower().endswith(".csv") else file_name
            print(f"[split] {file_name}: splitting {total:,} rows into {parts} parts")

            for i in range(parts):
                start = i * split_rows
                stop = min((i + 1) * split_rows, total)
                part_name = f"{base}.part{i + 1:03d}.csv"
                part_path = os.path.join(self.out_dir, part_name)
                df.iloc[start:stop].to_csv(part_path, index=False)
                print(f"[split]   {part_name}: rows {start + 1:,}-{stop:,}")

            if delete_original:
                os.remove(path)
                print(f"[split] removed original {file_name}")
            split_any = True

        if not split_any:
            print("\n[split] No files were split.")

    def run(self, args: argparse.Namespace) -> None:
        todo = args.only or list(SOURCES)
        manifest, skipped = [], []

        fetch_rows = args.rows
        if args.align_time_range and args.full_before_align and not _is_unlimited(args.rows):
            fetch_rows = 0
            print("\n[align] full-before-align enabled: fetching uncapped data, then aligning in-place")

        for name in todo:
            fn, desc, _ = SOURCES[name]
            print(f"\n[{name}] {desc}")
            try:
                for path, n, note in fn(fetch_rows):
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
            time.sleep(self.pause_seconds)

        if manifest:
            m = pd.DataFrame(manifest)
            m.to_csv(os.path.join(self.out_dir, "_manifest.csv"), index=False)
            print(f"\nWrote {len(manifest)} files to {self.out_dir}/ "
                  f"({m['rows'].sum():,} rows total)")
            print(f"Manifest: {self.out_dir}/_manifest.csv")
            if args.align_time_range:
                self.align_common_time_range(manifest)
            if args.split_large_csv:
                self.split_large_csv_files(
                    manifest_rows=manifest,
                    split_targets=args.split_targets,
                    split_rows=args.split_rows,
                    delete_original=args.split_delete_original,
                )
        if skipped:
            print(f"Skipped: {', '.join(skipped)}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="+", choices=list(SOURCES),
                   help="fetch only these sources")
    p.add_argument("--rows", type=int, default=0,
                   help="max rows to keep per source; use 0 for no cap (default 0)")
    p.add_argument("--out-dir", default="data")
    p.add_argument("--list", action="store_true", help="list sources and exit")
    p.add_argument("--nomis-probe", metavar="DATASET",
                   help="diagnose an empty Nomis response, e.g. NM_99_1")
    p.add_argument("--nomis-detail", action="store_true",
                   help="all sexes, items and pay measures (~40x rows; needs a key)")
    p.add_argument("--align-time-range", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="align fetched time-series to shared overlapping years")
    p.add_argument("--full-before-align", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="when aligning, fetch uncapped data first (default true)")
    p.add_argument("--split-large-csv", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="split large fetched CSV files into smaller chunks")
    p.add_argument("--split-targets", nargs="+",
                   default=["ons_house_prices_local_authority.csv"],
                   help="filenames to split when large")
    p.add_argument("--split-rows", type=int, default=200_000,
                   help="max rows per split CSV part")
    p.add_argument("--split-delete-original", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="delete original file after successful split")
    args = p.parse_args()

    if args.list:
        print(f"{'source':<14}{'key':<15}description")
        for k, (_, desc, key) in SOURCES.items():
            print(f"{k:<14}{key:<15}{desc}")
        return

    global OUT_DIR, NOMIS_DETAIL
    OUT_DIR = args.out_dir
    NOMIS_DETAIL = args.nomis_detail

    if args.nomis_probe:
        nomis_probe(args.nomis_probe)
        return

    pipeline = FetchDataPipeline(out_dir=OUT_DIR, pause_seconds=PAUSE)
    pipeline.run(args)


if __name__ == "__main__":
    main()
