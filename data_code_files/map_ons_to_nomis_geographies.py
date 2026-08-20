#!/usr/bin/env python3
"""
Build a crosswalk from ONS local-authority house-price geographies to Nomis
resident earnings geographies.

Outputs:
  - data/geography_mapping/nomis_unique_geographies.csv
  - data/geography_mapping/ons_unique_geographies.csv
  - data/geography_mapping/ons_to_nomis_geography_mapping.csv
  - data/geography_mapping/unmapped_ons_geographies.csv

External source used for the main mapping:
  - Office for National Statistics CKAN dataset:
    Local Authority District to County and Unitary Authority
    (December 2024) Lookup in England and Wales
    https://ckan.publishing.service.gov.uk/dataset/local-authority-district-to-county-and-unitary-authority-december-2024-lookup-in-ew

The ONS house-price file contains some current authority names plus a handful of
historic district names. Those historic/reorganised cases are handled with
explicit overrides so the produced mapping is auditable.
"""

from __future__ import annotations

from pathlib import Path
import glob
import re

import pandas as pd


DATA_DIR = Path("data")
NOMIS_PATH = DATA_DIR / "nomis_data" / "nomis_ashe_resident.csv"
ONS_GLOB = str(DATA_DIR / "ons_data" / "ons_house_prices_local_authority.part*.csv")
OUT_DIR = DATA_DIR / "geography_mapping"

LOOKUP_DATASET_URL = (
    "https://ckan.publishing.service.gov.uk/dataset/"
    "local-authority-district-to-county-and-unitary-authority-december-2024-lookup-in-ew"
)
LOOKUP_CSV_URL = (
    "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/"
    "1b80e7fe67e34cf5b084ba23700d7974/csv?layers=0"
)


def normalize_name(value: str) -> str:
    text = str(value).strip().lower()
    text = text.replace("&", " and ")
    text = text.replace("st.", "st")
    text = text.replace("city of ", "")
    text = text.replace(", city of", "")
    text = text.replace(",", " ")
    text = text.replace("-", " ")
    text = text.replace("'", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


MANUAL_TARGETS = {
    # Simple naming differences between ONS and Nomis.
    "bristol": "Bristol",
    "bristol city of": "Bristol",
    "county durham": "Durham",
    "derby": "Derby City",
    "isle of anglesey": "Anglesey",
    "kingston upon hull": "Kingston upon Hull",
    "kingston upon hull city of": "Kingston upon Hull",
    "kingston upon thames": "Kingston-upon-Thames",
    "leicester": "Leicester City",
    "newcastle upon tyne": "Newcastle-upon-Tyne",
    "nottingham": "Nottingham City",
    "rhondda cynon taf": "Rhondda, Cynon, Taff",
    "richmond upon thames": "Richmond-upon-Thames",
    "southend on sea": "Southend-on-sea",
    "st helens": "St Helens",
    "stockton on tees": "Stockton on Tees",
    "stoke on trent": "Stoke on Trent",
    "westminster": "Westminster, City of",

    # Current authorities that need broadening back to the older Nomis area.
    "bedford": "Bedfordshire",
    "central bedfordshire": "Bedfordshire",
    "cheshire east": "Cheshire",
    "cheshire west and chester": "Cheshire",
    "cornwall": "Cornwall and Isles of Scilly",
    "cumberland": "Cumbria",
    "north northamptonshire": "Northamptonshire",
    "west northamptonshire": "Northamptonshire",
    "westmorland and furness": "Cumbria",

    # Areas merged after the Nomis geography set used in this repo.
    "bournemouth christchurch and poole": "Bournemouth|Poole",
    "isles of scilly": "Cornwall and Isles of Scilly",
}


HISTORIC_SUCCESSORS = {
    # Cumbria reorganisation.
    "allerdale": "Cumberland",
    "carlisle": "Cumberland",
    "copeland": "Cumberland",
    "barrow in furness": "Westmorland and Furness",
    "eden": "Westmorland and Furness",
    "south lakeland": "Westmorland and Furness",

    # North Yorkshire reorganisation.
    "craven": "North Yorkshire",
    "hambleton": "North Yorkshire",
    "harrogate": "North Yorkshire",
    "richmondshire": "North Yorkshire",
    "ryedale": "North Yorkshire",
    "scarborough": "North Yorkshire",
    "selby": "North Yorkshire",

    # Somerset reorganisation.
    "mendip": "Somerset",
    "sedgemoor": "Somerset",
    "south somerset": "Somerset",
    "somerset west and taunton": "Somerset",
}


def load_unique_nomis_geographies() -> pd.DataFrame:
    nomis = pd.read_csv(NOMIS_PATH, low_memory=False, usecols=["GEOGRAPHY_NAME", "GEOGRAPHY_CODE"])
    unique = (
        nomis.dropna(subset=["GEOGRAPHY_NAME", "GEOGRAPHY_CODE"])
        .assign(GEOGRAPHY_NAME=lambda frame: frame["GEOGRAPHY_NAME"].astype(str).str.strip())
        .drop_duplicates()
        .sort_values(["GEOGRAPHY_NAME", "GEOGRAPHY_CODE"])
        .reset_index(drop=True)
    )
    return unique


def load_unique_ons_geographies() -> pd.DataFrame:
    files = sorted(glob.glob(ONS_GLOB))
    if not files:
        raise FileNotFoundError(f"No ONS house-price part files matched: {ONS_GLOB}")

    ons = pd.concat(
        [pd.read_csv(path, low_memory=False, usecols=["Geography", "administrative-geography"]) for path in files],
        ignore_index=True,
    )
    unique = (
        ons.dropna(subset=["Geography", "administrative-geography"])
        .assign(Geography=lambda frame: frame["Geography"].astype(str).str.strip())
        .drop_duplicates()
        .sort_values(["Geography", "administrative-geography"])
        .reset_index(drop=True)
    )
    return unique


def build_nomis_lookup(nomis_unique: pd.DataFrame) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for name in nomis_unique["GEOGRAPHY_NAME"]:
        lookup.setdefault(normalize_name(name), name)
    return lookup


def resolve_manual_target(target: str, nomis_lookup: dict[str, str]) -> tuple[str | None, str | None]:
    if "|" in target:
        parts = []
        for piece in target.split("|"):
            match = nomis_lookup.get(normalize_name(piece))
            if not match:
                return None, None
            parts.append(match)
        return "|".join(parts), "one_to_many"

    match = nomis_lookup.get(normalize_name(target))
    if not match:
        return None, None
    return match, "one_to_one"


def build_mapping(ons_unique: pd.DataFrame, nomis_lookup: dict[str, str]) -> pd.DataFrame:
    lookup = pd.read_csv(LOOKUP_CSV_URL)
    lad_to_ctyua = {}
    for _, row in lookup[["LAD24NM", "CTYUA24NM"]].dropna().drop_duplicates().iterrows():
        lad_to_ctyua[normalize_name(row["LAD24NM"])] = str(row["CTYUA24NM"]).strip()

    rows = []
    for _, row in ons_unique.iterrows():
        ons_name = str(row["Geography"]).strip()
        ons_code = str(row["administrative-geography"]).strip()
        ons_key = normalize_name(ons_name)

        nomis_target = None
        mapping_type = None
        mapping_source = None
        lookup_parent = None

        direct = nomis_lookup.get(ons_key)
        if direct:
            nomis_target = direct
            mapping_type = "direct_name_match"
            mapping_source = "dataset_name_overlap"
        elif ons_key in MANUAL_TARGETS:
            nomis_target, cardinality = resolve_manual_target(MANUAL_TARGETS[ons_key], nomis_lookup)
            mapping_type = f"manual_{cardinality}" if cardinality else None
            mapping_source = LOOKUP_DATASET_URL
        else:
            parent_name = lad_to_ctyua.get(ons_key)
            if parent_name is None and ons_key in HISTORIC_SUCCESSORS:
                parent_name = HISTORIC_SUCCESSORS[ons_key]
                mapping_source = "manual_successor_override"

            if parent_name is not None:
                lookup_parent = parent_name
                parent_key = normalize_name(parent_name)

                direct_parent = nomis_lookup.get(parent_key)
                if direct_parent:
                    nomis_target = direct_parent
                    mapping_type = "official_lookup_parent_match"
                    mapping_source = mapping_source or LOOKUP_DATASET_URL
                elif parent_key in MANUAL_TARGETS:
                    nomis_target, cardinality = resolve_manual_target(MANUAL_TARGETS[parent_key], nomis_lookup)
                    mapping_type = f"lookup_parent_manual_{cardinality}" if cardinality else None
                    mapping_source = mapping_source or LOOKUP_DATASET_URL

        rows.append(
            {
                "ons_geography": ons_name,
                "ons_geography_code": ons_code,
                "lookup_parent_geography": lookup_parent,
                "nomis_geography": nomis_target,
                "mapped": pd.notna(nomis_target),
                "mapping_type": mapping_type,
                "mapping_source": mapping_source,
            }
        )

    return pd.DataFrame(rows).sort_values(["mapped", "ons_geography"], ascending=[False, True]).reset_index(drop=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    nomis_unique = load_unique_nomis_geographies()
    ons_unique = load_unique_ons_geographies()
    nomis_lookup = build_nomis_lookup(nomis_unique)
    mapping = build_mapping(ons_unique, nomis_lookup)

    nomis_unique.to_csv(OUT_DIR / "nomis_unique_geographies.csv", index=False)
    ons_unique.to_csv(OUT_DIR / "ons_unique_geographies.csv", index=False)
    mapping.to_csv(OUT_DIR / "ons_to_nomis_geography_mapping.csv", index=False)
    mapping[~mapping["mapped"]].to_csv(OUT_DIR / "unmapped_ons_geographies.csv", index=False)

    mapped_count = int(mapping["mapped"].sum())
    print(f"Nomis unique geographies: {len(nomis_unique):,}")
    print(f"ONS unique geographies: {len(ons_unique):,}")
    print(f"Mapped ONS geographies: {mapped_count:,}/{len(mapping):,}")
    if mapped_count != len(mapping):
        print("Unmapped ONS geographies written to:")
        print(f"  {OUT_DIR / 'unmapped_ons_geographies.csv'}")
    print("Outputs written to:")
    print(f"  {OUT_DIR}")


if __name__ == "__main__":
    main()