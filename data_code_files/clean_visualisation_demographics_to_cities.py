#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DEM_DIR = ROOT_DIR / "visualisations_data" / "demographic_data"

FILES = [
    DEM_DIR / "sex_with_region.csv",
    DEM_DIR / "religion_with_region.csv",
    DEM_DIR / "ethnicity_with_region.csv",
]

UK_CITY_LIST = [
    "Bath", "Birmingham", "Bradford", "Brighton and Hove", "Bristol", "Cambridge",
    "Canterbury", "Carlisle", "Chelmsford", "Chester", "Chichester", "Colchester",
    "Coventry", "Derby", "Doncaster", "Durham", "Ely", "Exeter", "Gloucester",
    "Hereford", "Kingston upon Hull", "Lancaster", "Leeds", "Leicester", "Lichfield",
    "Lincoln", "Liverpool", "London", "Manchester", "Milton Keynes",
    "Newcastle upon Tyne", "Norwich", "Nottingham", "Oxford", "Peterborough",
    "Plymouth", "Portsmouth", "Preston", "Ripon", "Salford", "Salisbury", "Sheffield",
    "Southampton", "Southend-on-Sea", "St Albans", "Stoke on Trent", "Sunderland",
    "Truro", "Wakefield", "Wells", "Westminster", "Winchester", "Wolverhampton",
    "Worcester", "York", "Armagh", "Bangor", "Belfast", "Lisburn", "Londonderry",
    "Newry", "Aberdeen", "Dundee", "Dunfermline", "Edinburgh", "Glasgow", "Inverness",
    "Perth", "Stirling", "Cardiff", "Newport", "St Asaph", "St Davids", "Swansea",
    "Wrexham", "Douglas",
]

CITY_ALIASES = {
    "brighton hove": "Brighton and Hove",
    "kingston upon hull": "Kingston upon Hull",
    "kingston upon hull city of": "Kingston upon Hull",
    "newcastle upon tyne": "Newcastle upon Tyne",
    "newcastle upon tyneside": "Newcastle upon Tyne",
    "bristol city of": "Bristol",
    "stoke on trent": "Stoke on Trent",
    "stoke upon trent": "Stoke on Trent",
    "southend on sea": "Southend-on-Sea",
    "southend on sea city": "Southend-on-Sea",
    "st albans city and district": "St Albans",
    "westminster city of": "Westminster",
    "city of westminster": "Westminster",
    "city of london": "London",
    "derry": "Londonderry",
    "newport newport": "Newport",
    "city of edinburgh": "Edinburgh",
    "edinburgh city of": "Edinburgh",
    "aberdeen city": "Aberdeen",
    "dundee city": "Dundee",
    "glasgow city": "Glasgow",
    "perth and kinross": "Perth",
    "highland": "Inverness",
}

AREA_TO_CITY = {
    "bath and north east somerset": "Bath",
    "cheshire west and chester": "Chester",
    "east cambridgeshire": "Ely",
    "herefordshire": "Hereford",
    "herefordshire county of": "Hereford",
    "cornwall": "Truro",
    "cornwall and isles of scilly": "Truro",
    "county durham": "Durham",
    "durham": "Durham",
    "harrogate": "Ripon",
    "mendip": "Wells",
    "sedgemoor": "Wells",
    "south somerset": "Wells",
    "taunton deane": "Wells",
    "west somerset": "Wells",
    "wiltshire": "Salisbury",
    "somerset": "Wells",
    "gwynedd": "Bangor",
    "denbighshire": "St Asaph",
    "pembrokeshire": "St Davids",
}


def normalize_name(value: str) -> str:
    text = str(value).strip().lower()
    text = text.replace("&", " and ")
    text = text.replace("-", " ")
    text = text.replace(",", " ")
    text = text.replace(".", " ")
    text = text.replace("'", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def city_lookup() -> dict[str, str]:
    lookup = {normalize_name(city): city for city in UK_CITY_LIST}
    for alias, canonical in CITY_ALIASES.items():
        lookup[normalize_name(alias)] = canonical
    return lookup


def infer_category_columns(columns: list[str]) -> tuple[str, str]:
    code_candidates = [c for c in columns if c.endswith("Code") and c != "Lower tier local authorities Code"]
    if not code_candidates:
        raise ValueError("Could not infer category code column")
    code_col = code_candidates[0]
    value_col = code_col[:-5].strip()
    if value_col not in columns:
        raise ValueError(f"Could not find category label column for {code_col}")
    return code_col, value_col


def map_city(area_name: str, lookup: dict[str, str]) -> tuple[str | None, str]:
    norm = normalize_name(area_name)
    if norm in lookup:
        return lookup[norm], "direct_or_alias"
    if norm in AREA_TO_CITY:
        return AREA_TO_CITY[norm], "area_to_city"
    return None, "unmapped"


def clean_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path, low_memory=False)
    code_col, cat_col = infer_category_columns(list(df.columns))

    lookup = city_lookup()
    mapped = df["Lower tier local authorities"].astype(str).map(lambda x: map_city(x, lookup))
    df["City"] = mapped.map(lambda x: x[0])
    df["Proxy_Source"] = mapped.map(lambda x: x[1])
    df["Proxy_Flag"] = df["Proxy_Source"].ne("direct_or_alias")
    df = df.dropna(subset=["City"]).copy()

    df["Observation"] = pd.to_numeric(df["Observation"], errors="coerce").fillna(0)

    grouped = (
        df.groupby(["City", "geography", code_col, cat_col, "Proxy_Flag", "Proxy_Source"], dropna=False, as_index=False)
        .agg(
            Observation=("Observation", "sum"),
            Source_Area_Count=("Lower tier local authorities", "nunique"),
            Source_Areas=("Lower tier local authorities", lambda values: "|".join(sorted({str(v) for v in values if pd.notna(v)}))),
        )
    )

    grouped = grouped.sort_values(["City", code_col]).reset_index(drop=True)
    grouped.to_csv(path, index=False)

    print(f"Cleaned {path.name}: {len(grouped):,} rows, {grouped['City'].nunique()} cities")


if __name__ == "__main__":
    for file_path in FILES:
        clean_file(file_path)
