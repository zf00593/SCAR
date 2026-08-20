#!/usr/bin/env python3
"""
Apply the ONS-to-Nomis geography mapping to the split ONS house-price files.

This writes new files into data/ons_data with "fixed" in the filename while
preserving the original part files. The transformation is non-destructive:
original ONS geography columns are retained and Nomis-mapped geography columns
are appended.

Outputs:
  data/ons_data/ons_house_prices_local_authority_fixed.part001.csv
  data/ons_data/ons_house_prices_local_authority_fixed.part002.csv
  ...
"""

from __future__ import annotations

from pathlib import Path
import glob

import pandas as pd


DATA_DIR = Path("data")
ONS_DIR = DATA_DIR / "ons_data"
MAPPING_PATH = DATA_DIR / "geography_mapping" / "ons_to_nomis_geography_mapping.csv"
NOMIS_UNIQUE_PATH = DATA_DIR / "geography_mapping" / "nomis_unique_geographies.csv"
AGGREGATED_PREFIX = "ons_house_prices_local_authority_fixed_aggregated"
CITY_REGION_PREFIX = "ons_house_prices_local_authority_fixed_city_regions"
SPLIT_ROWS = 200_000
LONDON_CODE = "E12000007"
LONDON_NAME = "London"

# Official where available, curated otherwise:
# - Greater Manchester metropolitan county / combined authority -> Manchester
# - Liverpool City Region combined authority -> Liverpool
# - West Midlands metropolitan county -> Birmingham
# - West Yorkshire metropolitan county -> Leeds
# - South Yorkshire metropolitan county -> Sheffield
# - Tyne and Wear metropolitan county -> Newcastle-upon-Tyne
# - Tees Valley combined authority -> Middlesbrough
# - West of England combined authority -> Bristol
# - Cardiff Capital Region -> Cardiff
# - Swansea Bay City Region -> Swansea
# - Hull and East Yorkshire fallback -> Kingston upon Hull
# - York and North Yorkshire combined authority -> York
CITY_REGION_RULES = {
    "London": {
        "source_names": {
            "Barking and Dagenham", "Barnet", "Bexley", "Brent", "Bromley", "Camden",
            "City of London", "Croydon", "Ealing", "Enfield", "Greenwich", "Hackney",
            "Hammersmith and Fulham", "Haringey", "Harrow", "Havering", "Hillingdon",
            "Hounslow", "Islington", "Kensington and Chelsea", "Kingston-upon-Thames",
            "Lambeth", "Lewisham", "Merton", "Newham", "Redbridge",
            "Richmond-upon-Thames", "Southwark", "Sutton", "Tower Hamlets",
            "Waltham Forest", "Wandsworth", "Westminster, City of",
        },
        "code": LONDON_CODE,
        "source": "official_london_borough_rollup",
    },
    "Manchester": {
        "source_names": {
            "Bolton", "Bury", "Manchester", "Oldham", "Rochdale", "Salford",
            "Stockport", "Tameside", "Trafford", "Wigan",
        },
        "source": "official_greater_manchester",
    },
    "Liverpool": {
        "source_names": {
            "Halton", "Knowsley", "Liverpool", "Sefton", "St Helens", "Wirral",
        },
        "source": "official_liverpool_city_region",
    },
    "Birmingham": {
        "source_names": {
            "Birmingham", "Coventry", "Dudley", "Sandwell", "Solihull", "Walsall",
            "Wolverhampton",
        },
        "source": "official_west_midlands",
    },
    "Leeds": {
        "source_names": {"Bradford", "Calderdale", "Kirklees", "Leeds", "Wakefield"},
        "source": "official_west_yorkshire",
    },
    "Sheffield": {
        "source_names": {"Barnsley", "Doncaster", "Rotherham", "Sheffield"},
        "source": "official_south_yorkshire",
    },
    "Newcastle-upon-Tyne": {
        "source_names": {
            "Gateshead", "Newcastle-upon-Tyne", "North Tyneside", "South Tyneside", "Sunderland",
        },
        "source": "official_tyne_and_wear",
    },
    "Middlesbrough": {
        "source_names": {
            "Darlington", "Hartlepool", "Middlesbrough", "Redcar and Cleveland", "Stockton on Tees",
        },
        "source": "official_tees_valley",
    },
    "Bristol": {
        "source_names": {"Bath and North East Somerset", "Bristol", "South Gloucestershire"},
        "source": "official_west_of_england",
    },
    "Cardiff": {
        "source_names": {
            "Blaenau Gwent", "Bridgend", "Caerphilly", "Cardiff", "Merthyr Tydfil",
            "Monmouthshire", "Newport", "Rhondda, Cynon, Taff", "Torfaen", "Vale of Glamorgan",
        },
        "source": "official_cardiff_capital_region",
    },
    "Swansea": {
        "source_names": {"Carmarthenshire", "Neath Port Talbot", "Pembrokeshire", "Swansea"},
        "source": "official_swansea_bay_city_region",
    },
    "Kingston upon Hull": {
        "source_names": {"East Riding of Yorkshire", "Kingston upon Hull"},
        "source": "curated_hull_east_yorkshire",
    },
    "York": {
        "source_names": {"North Yorkshire", "York"},
        "source": "official_york_north_yorkshire",
    },
}


def build_nomis_code_lookup() -> dict[str, str]:
    nomis_unique = pd.read_csv(NOMIS_UNIQUE_PATH)
    return dict(zip(nomis_unique["GEOGRAPHY_NAME"], nomis_unique["GEOGRAPHY_CODE"]))


def build_city_region_lookup(nomis_code_lookup: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    city_region_lookup: dict[str, tuple[str, str, str]] = {}
    for target_name, rule in CITY_REGION_RULES.items():
        target_code = rule.get("code") or nomis_code_lookup.get(target_name, f"CITYREGION_{target_name.upper().replace(' ', '_').replace('-', '_').replace(',', '')}")
        source = str(rule["source"])
        for source_name in rule["source_names"]:
            city_region_lookup[str(source_name)] = (target_name, target_code, source)
    return city_region_lookup


def mapping_with_codes() -> pd.DataFrame:
    mapping = pd.read_csv(MAPPING_PATH)
    nomis_code_lookup = build_nomis_code_lookup()

    def to_codes(name_value: str) -> str:
        if pd.isna(name_value):
            return ""
        names = [piece.strip() for piece in str(name_value).split("|") if piece.strip()]
        codes = [nomis_code_lookup.get(name, "") for name in names]
        codes = [code for code in codes if code]
        return "|".join(codes)

    mapping = mapping.copy()
    mapping["nomis_geography_code"] = mapping["nomis_geography"].apply(to_codes)
    return mapping[[
        "ons_geography_code",
        "ons_geography",
        "nomis_geography",
        "nomis_geography_code",
        "mapped",
        "mapping_type",
        "mapping_source",
    ]]


def output_path_for(source_path: Path) -> Path:
    name = source_path.name
    return source_path.with_name(name.replace(".part", "_fixed.part"))


def is_london_code(value: str) -> bool:
    return str(value).startswith("E09")


def build_aggregated_frame(fixed_frames: list[pd.DataFrame]) -> pd.DataFrame:
    combined = pd.concat(fixed_frames, ignore_index=True)

    expanded = combined.copy()
    expanded["nomis_geography"] = expanded["nomis_geography"].astype(str).str.split("|")
    expanded["nomis_geography_code"] = expanded["nomis_geography_code"].astype(str).str.split("|")
    expanded = expanded.explode(["nomis_geography", "nomis_geography_code"], ignore_index=True)

    expanded["nomis_geography"] = expanded["nomis_geography"].astype(str).str.strip()
    expanded["nomis_geography_code"] = expanded["nomis_geography_code"].astype(str).str.strip()

    expanded["aggregated_geography"] = expanded["nomis_geography"]
    expanded["aggregated_geography_code"] = expanded["nomis_geography_code"]

    london_mask = expanded["aggregated_geography_code"].apply(is_london_code)
    expanded.loc[london_mask, "aggregated_geography"] = LONDON_NAME
    expanded.loc[london_mask, "aggregated_geography_code"] = LONDON_CODE

    expanded = expanded.copy()
    expanded["administrative-geography"] = expanded["aggregated_geography_code"]
    expanded["Geography"] = expanded["aggregated_geography"]

    group_cols = [
        "ons_dataset_id",
        "ons_version",
        "ons_release_date",
        "Data Marking",
        "calendar-years",
        "Time",
        "mmm",
        "Month",
        "administrative-geography",
        "Geography",
        "property-type",
        "PropertyType",
        "build-status",
        "BuildStatus",
        "house-sales-and-prices",
        "HouseSalesAndPrices",
    ]

    aggregated = (
        expanded.groupby(group_cols, dropna=False, as_index=False)
        .agg(
            V4_1=("V4_1", "mean"),
            source_ons_geography_count=("ons_geography_code", "nunique"),
            source_nomis_geography_count=("nomis_geography_code", "nunique"),
        )
    )
    return aggregated


def build_city_region_frame(fixed_frames: list[pd.DataFrame]) -> pd.DataFrame:
    nomis_code_lookup = build_nomis_code_lookup()
    city_region_lookup = build_city_region_lookup(nomis_code_lookup)

    combined = pd.concat(fixed_frames, ignore_index=True)

    expanded = combined.copy()
    expanded["nomis_geography"] = expanded["nomis_geography"].astype(str).str.split("|")
    expanded["nomis_geography_code"] = expanded["nomis_geography_code"].astype(str).str.split("|")
    expanded = expanded.explode(["nomis_geography", "nomis_geography_code"], ignore_index=True)

    expanded["nomis_geography"] = expanded["nomis_geography"].astype(str).str.strip()
    expanded["nomis_geography_code"] = expanded["nomis_geography_code"].astype(str).str.strip()

    expanded["city_region_geography"] = expanded["nomis_geography"]
    expanded["city_region_geography_code"] = expanded["nomis_geography_code"]
    expanded["city_region_mapping_source"] = "identity"

    for source_name, (target_name, target_code, target_source) in city_region_lookup.items():
        mask = expanded["nomis_geography"] == source_name
        expanded.loc[mask, "city_region_geography"] = target_name
        expanded.loc[mask, "city_region_geography_code"] = target_code
        expanded.loc[mask, "city_region_mapping_source"] = target_source

    expanded = expanded.copy()
    expanded["administrative-geography"] = expanded["city_region_geography_code"]
    expanded["Geography"] = expanded["city_region_geography"]

    group_cols = [
        "ons_dataset_id",
        "ons_version",
        "ons_release_date",
        "Data Marking",
        "calendar-years",
        "Time",
        "mmm",
        "Month",
        "administrative-geography",
        "Geography",
        "property-type",
        "PropertyType",
        "build-status",
        "BuildStatus",
        "house-sales-and-prices",
        "HouseSalesAndPrices",
    ]

    city_region = (
        expanded.groupby(group_cols, dropna=False, as_index=False)
        .agg(
            V4_1=("V4_1", "mean"),
            source_ons_geography_count=("ons_geography_code", "nunique"),
            source_nomis_geography_count=("nomis_geography_code", "nunique"),
            city_region_mapping_source=("city_region_mapping_source", lambda values: "|".join(sorted(set(str(v) for v in values if pd.notna(v))))),
        )
    )
    return city_region


def write_aggregated_parts(aggregated: pd.DataFrame) -> list[tuple[str, int]]:
    written = []
    total = len(aggregated)
    parts = (total + SPLIT_ROWS - 1) // SPLIT_ROWS
    for index in range(parts):
        start = index * SPLIT_ROWS
        stop = min((index + 1) * SPLIT_ROWS, total)
        path = ONS_DIR / f"{AGGREGATED_PREFIX}.part{index + 1:03d}.csv"
        aggregated.iloc[start:stop].to_csv(path, index=False)
        written.append((path.name, stop - start))
    return written


def write_parts(frame: pd.DataFrame, prefix: str) -> list[tuple[str, int]]:
    written = []
    total = len(frame)
    parts = (total + SPLIT_ROWS - 1) // SPLIT_ROWS
    for index in range(parts):
        start = index * SPLIT_ROWS
        stop = min((index + 1) * SPLIT_ROWS, total)
        path = ONS_DIR / f"{prefix}.part{index + 1:03d}.csv"
        frame.iloc[start:stop].to_csv(path, index=False)
        written.append((path.name, stop - start))
    return written


def main() -> None:
    source_files = sorted(
        Path(path) for path in glob.glob(str(ONS_DIR / "ons_house_prices_local_authority.part*.csv"))
        if "_fixed.part" not in Path(path).name
    )
    if not source_files:
        raise FileNotFoundError("No source ONS part files found to fix.")

    mapping = mapping_with_codes()
    if not bool(mapping["mapped"].all()):
        raise RuntimeError("Mapping file contains unmapped rows; aborting fixed-file creation.")

    written = []
    fixed_frames: list[pd.DataFrame] = []
    for source_path in source_files:
        frame = pd.read_csv(source_path, low_memory=False)
        fixed = frame.merge(
            mapping,
            how="left",
            left_on=["administrative-geography", "Geography"],
            right_on=["ons_geography_code", "ons_geography"],
            validate="many_to_one",
        )

        missing = fixed["nomis_geography"].isna().sum()
        if missing:
            raise RuntimeError(f"{source_path.name}: {missing} rows did not receive a Nomis mapping")

        output_path = output_path_for(source_path)
        fixed.to_csv(output_path, index=False)
        written.append((output_path.name, len(fixed)))
        fixed_frames.append(fixed)

    aggregated = build_aggregated_frame(fixed_frames)
    aggregated_written = write_aggregated_parts(aggregated)
    city_region = build_city_region_frame(fixed_frames)
    city_region_written = write_parts(city_region, CITY_REGION_PREFIX)

    print("Wrote fixed ONS part files:")
    for name, rows in written:
        print(f"  {name} ({rows:,} rows)")
    print("Wrote aggregated fixed ONS part files:")
    for name, rows in aggregated_written:
        print(f"  {name} ({rows:,} rows)")
    print("Wrote city-region fixed ONS part files:")
    for name, rows in city_region_written:
        print(f"  {name} ({rows:,} rows)")


if __name__ == "__main__":
    main()