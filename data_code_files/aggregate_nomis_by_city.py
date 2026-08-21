#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
NOMIS_DIR = DATA_DIR / "nomis_data"
MAPPING_PATH = DATA_DIR / "geography_mapping" / "ons_to_nomis_geography_mapping.csv"

RESIDENT_PATH = NOMIS_DIR / "nomis_ashe_resident.csv"
WORKPLACE_PATH = NOMIS_DIR / "nomis_ashe_workplace.csv"

OUT_RESIDENT = NOMIS_DIR / "nomis_ashe_resident_cities.csv"
OUT_WORKPLACE = NOMIS_DIR / "nomis_ashe_workplace_cities.csv"
OUT_RESIDENT_ONLY = NOMIS_DIR / "nomis_ashe_resident_city_only.csv"
OUT_WORKPLACE_ONLY = NOMIS_DIR / "nomis_ashe_workplace_city_only.csv"

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


def is_county_like(name: str) -> bool:
    norm = normalize_name(name)
    tokens = (
        "shire",
        "county",
        "greater london",
        "isles of",
    )
    return any(token in norm for token in tokens)


def build_city_lookup() -> dict[str, str]:
    lookup = {normalize_name(city): city for city in UK_CITY_LIST}
    for alias, canonical in CITY_ALIASES.items():
        lookup[normalize_name(alias)] = canonical
    return lookup


def build_parent_maps() -> tuple[dict[str, set[str]], dict[str, int]]:
    if not MAPPING_PATH.exists():
        return {}, {}

    mapping = pd.read_csv(MAPPING_PATH, low_memory=False)
    required_cols = {"lookup_parent_geography", "nomis_geography", "ons_geography"}
    if not required_cols.issubset(mapping.columns):
        return {}, {}

    mapped = mapping.dropna(subset=["nomis_geography"]).copy()
    mapped["nomis_geography"] = mapped["nomis_geography"].astype(str).str.split("|")
    mapped = mapped.explode("nomis_geography", ignore_index=True)
    mapped["nomis_geography"] = mapped["nomis_geography"].astype(str).str.strip()

    nomis_to_parents: dict[str, set[str]] = {}
    nomis_to_ons_count: dict[str, int] = {}

    for key, grp in mapped.groupby("nomis_geography", dropna=False):
        norm_key = normalize_name(key)
        parents = {
            normalize_name(value)
            for value in grp["lookup_parent_geography"].dropna().astype(str)
            if normalize_name(value)
        }
        if parents:
            nomis_to_parents[norm_key] = parents
        nomis_to_ons_count[norm_key] = int(grp["ons_geography"].dropna().astype(str).nunique())

    return nomis_to_parents, nomis_to_ons_count


def aggregate_nomis_to_city(path: Path, out_path: Path, out_city_only_path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    city_lookup = build_city_lookup()
    nomis_to_parents, nomis_to_ons_count = build_parent_maps()

    frame = pd.read_csv(path, low_memory=False)
    frame["OBS_VALUE"] = pd.to_numeric(frame["OBS_VALUE"], errors="coerce")
    frame = frame.dropna(subset=["GEOGRAPHY_NAME", "OBS_VALUE"]).copy()

    frame["Norm_Geog"] = frame["GEOGRAPHY_NAME"].astype(str).map(normalize_name)
    frame["Canonical_City"] = frame["Norm_Geog"].map(city_lookup)
    frame["Parent_Set"] = frame["Norm_Geog"].map(lambda key: nomis_to_parents.get(key, set()))

    parent_city_map: dict[str, set[str]] = {}
    for _, row in frame.dropna(subset=["Canonical_City"]).iterrows():
        for parent in row["Parent_Set"]:
            parent_city_map.setdefault(parent, set()).add(str(row["Canonical_City"]))

    def assign_target(row: pd.Series) -> str | None:
        if pd.notna(row["Canonical_City"]):
            return str(row["Canonical_City"])

        norm = str(row["Norm_Geog"])
        if norm in AREA_TO_CITY:
            return AREA_TO_CITY[norm]

        city_candidates: set[str] = set()
        for parent in row["Parent_Set"]:
            city_candidates.update(parent_city_map.get(parent, set()))

        if len(city_candidates) == 1:
            return next(iter(city_candidates))

        if len(city_candidates) == 0 and nomis_to_ons_count.get(norm, 0) > 1 and is_county_like(str(row["GEOGRAPHY_NAME"])):
            return str(row["GEOGRAPHY_NAME"]).strip()
        return None

    frame["Target_City"] = frame.apply(assign_target, axis=1)
    frame = frame.dropna(subset=["Target_City"]).copy()

    group_cols = [
        "nomis_dataset", "DATE", "DATE_NAME", "SEX", "SEX_NAME", "PAY", "PAY_NAME",
        "ITEM", "ITEM_NAME", "MEASURES", "MEASURES_NAME", "Target_City",
    ]

    agg = (
        frame.groupby(group_cols, dropna=False, as_index=False)
        .agg(
            OBS_VALUE=("OBS_VALUE", "mean"),
            Source_Geography_Count=("GEOGRAPHY_NAME", "nunique"),
            Geography_Code_List=("GEOGRAPHY_CODE", lambda values: "|".join(sorted({str(v) for v in values if pd.notna(v)}))),
        )
    )

    agg = agg.rename(columns={"Target_City": "GEOGRAPHY_NAME", "Geography_Code_List": "GEOGRAPHY_CODE"})
    agg["GEOGRAPHY"] = agg["GEOGRAPHY_NAME"]
    agg = agg.sort_values(["DATE_NAME", "GEOGRAPHY_NAME"]).reset_index(drop=True)

    city_norms = set(build_city_lookup().keys())
    city_only = agg[agg["GEOGRAPHY_NAME"].astype(str).map(normalize_name).isin(city_norms)].copy()

    agg.to_csv(out_path, index=False)
    city_only.to_csv(out_city_only_path, index=False)

    print(f"Wrote: {out_path} ({len(agg):,} rows)")
    print(f"Wrote: {out_city_only_path} ({len(city_only):,} rows)")


def main() -> None:
    aggregate_nomis_to_city(RESIDENT_PATH, OUT_RESIDENT, OUT_RESIDENT_ONLY)
    aggregate_nomis_to_city(WORKPLACE_PATH, OUT_WORKPLACE, OUT_WORKPLACE_ONLY)


if __name__ == "__main__":
    main()
