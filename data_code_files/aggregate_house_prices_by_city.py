#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
ONS_DATA_DIR = DATA_DIR / "ons_data"
MAPPING_PATH = DATA_DIR / "geography_mapping" / "ons_to_nomis_geography_mapping.csv"
HOUSE_PRICE_GLOB = "ons_house_prices_local_authority_fixed.part*.csv"
OUTPUT_PATH = DATA_DIR / "city_house_prices_latest.csv"

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


def build_city_lookup() -> dict[str, str]:
    lookup = {normalize_name(city): city for city in UK_CITY_LIST}
    for alias, canonical in CITY_ALIASES.items():
        lookup[normalize_name(alias)] = canonical
    return lookup


def to_city_name(value: str, city_lookup: dict[str, str]) -> str | None:
    return city_lookup.get(normalize_name(value))


def is_county_like(name: str) -> bool:
    norm = normalize_name(name)
    tokens = (
        "shire",
        "county",
        "greater london",
        "isles of",
    )
    return any(token in norm for token in tokens)


def load_house_prices_latest() -> pd.DataFrame:
    part_files = sorted(ONS_DATA_DIR.glob(HOUSE_PRICE_GLOB))
    if not part_files:
        raise FileNotFoundError(
            f"No house price files matched {HOUSE_PRICE_GLOB} in {ONS_DATA_DIR}."
        )

    frames = [pd.read_csv(path, low_memory=False) for path in part_files]
    house_prices = pd.concat(frames, ignore_index=True)

    house_prices = house_prices[
        (house_prices["property-type"] == "all")
        & (house_prices["build-status"] == "all")
        & (house_prices["house-sales-and-prices"].isin(["mean", "median", "sales"]))
    ].copy()

    house_prices["V4_1"] = pd.to_numeric(house_prices["V4_1"], errors="coerce")
    house_prices["Date"] = pd.to_datetime(
        house_prices["mmm"].astype(str).str.title() + "-" + house_prices["calendar-years"].astype(str),
        format="%b-%Y",
        errors="coerce",
    )
    house_prices = house_prices.dropna(subset=["Geography", "administrative-geography", "V4_1", "Date"])

    if "source_ons_geography_count" not in house_prices.columns:
        house_prices["source_ons_geography_count"] = 1
    if "source_nomis_geography_count" not in house_prices.columns:
        house_prices["source_nomis_geography_count"] = 1

    latest_date = house_prices["Date"].max()
    house_prices = house_prices[house_prices["Date"] == latest_date].copy()

    mapping_source_col = "city_region_mapping_source" if "city_region_mapping_source" in house_prices.columns else "mapping_source"
    if mapping_source_col not in house_prices.columns:
        house_prices[mapping_source_col] = "identity"

    city_prices = (
        house_prices.pivot_table(
            index=[
                "administrative-geography",
                "Geography",
                "Date",
                "source_ons_geography_count",
                "source_nomis_geography_count",
                mapping_source_col,
            ],
            columns="house-sales-and-prices",
            values="V4_1",
            aggfunc="mean",
        )
        .reset_index()
        .rename_axis(columns=None)
        .rename(
            columns={
                "administrative-geography": "City_Code",
                "Geography": "City",
                "mean": "Mean_Price",
                "median": "Median_Price",
                "sales": "Sales_Count",
                "source_ons_geography_count": "Source_ONS_Geography_Count",
                "source_nomis_geography_count": "Source_Nomis_Geography_Count",
                mapping_source_col: "Mapping_Source",
            }
        )
        .sort_values("Mean_Price", ascending=False)
        .reset_index(drop=True)
    )

    return city_prices


def build_nomis_parent_lookup() -> dict[str, set[str]]:
    if not MAPPING_PATH.exists():
        return {}

    mapping = pd.read_csv(MAPPING_PATH, low_memory=False)
    required_cols = {"lookup_parent_geography", "nomis_geography"}
    if not required_cols.issubset(mapping.columns):
        return {}

    mapped = mapping.dropna(subset=["lookup_parent_geography", "nomis_geography"]).copy()
    mapped["nomis_geography"] = mapped["nomis_geography"].astype(str).str.split("|")
    mapped = mapped.explode("nomis_geography", ignore_index=True)
    mapped["nomis_geography"] = mapped["nomis_geography"].astype(str).str.strip()

    parent_lookup: dict[str, set[str]] = {}
    for _, row in mapped.iterrows():
        key = normalize_name(row["nomis_geography"])
        parent = normalize_name(row["lookup_parent_geography"])
        if not key or not parent:
            continue
        parent_lookup.setdefault(key, set()).add(parent)
    return parent_lookup


def keep_city_only_rows(city_prices: pd.DataFrame) -> pd.DataFrame:
    city_lookup = build_city_lookup()
    parent_lookup = build_nomis_parent_lookup()

    frame = city_prices.copy()
    frame["Canonical_City"] = frame["City"].apply(lambda value: to_city_name(value, city_lookup))
    frame["Norm_City"] = frame["City"].astype(str).map(normalize_name)
    frame["Parent_Set"] = frame["Norm_City"].map(lambda key: parent_lookup.get(key, set()))

    parent_city_map: dict[str, set[str]] = {}
    for _, row in frame.dropna(subset=["Canonical_City"]).iterrows():
        for parent in row["Parent_Set"]:
            parent_city_map.setdefault(parent, set()).add(str(row["Canonical_City"]))

    def assign_target(row: pd.Series) -> str | None:
        if pd.notna(row["Canonical_City"]):
            return str(row["Canonical_City"])

        norm_city = str(row["Norm_City"])
        if norm_city in AREA_TO_CITY:
            return AREA_TO_CITY[norm_city]

        city_candidates: set[str] = set()
        for parent in row["Parent_Set"]:
            city_candidates.update(parent_city_map.get(parent, set()))

        if len(city_candidates) == 1:
            return next(iter(city_candidates))

        # Keep non-city fallback only when this row is already an aggregate area.
        if (
            len(city_candidates) == 0
            and pd.to_numeric(row["Source_ONS_Geography_Count"], errors="coerce") > 1
            and is_county_like(str(row["City"]))
        ):
            return str(row["City"]).strip()
        return None

    frame["Target_City"] = frame.apply(assign_target, axis=1)
    frame = frame.dropna(subset=["Target_City"]).copy()

    frame["Mean_Price"] = pd.to_numeric(frame["Mean_Price"], errors="coerce")
    frame["Median_Price"] = pd.to_numeric(frame["Median_Price"], errors="coerce")
    frame["Sales_Count"] = pd.to_numeric(frame["Sales_Count"], errors="coerce")
    frame["Source_ONS_Geography_Count"] = pd.to_numeric(frame["Source_ONS_Geography_Count"], errors="coerce").fillna(0)
    frame["Source_Nomis_Geography_Count"] = pd.to_numeric(frame["Source_Nomis_Geography_Count"], errors="coerce").fillna(0)

    def weighted_value(values: pd.Series, weights: pd.Series) -> float:
        mask = values.notna() & weights.notna() & (weights > 0)
        if not mask.any():
            valid = values.dropna()
            return float(valid.mean()) if not valid.empty else float("nan")
        return float((values[mask] * weights[mask]).sum() / weights[mask].sum())

    out_rows = []
    for (target_city, date), group in frame.groupby(["Target_City", "Date"], dropna=False):
        sales = group["Sales_Count"]
        out_rows.append(
            {
                "City_Code": "|".join(sorted({str(code) for code in group["City_Code"].dropna().astype(str)})),
                "City": str(target_city),
                "Date": date,
                "Source_ONS_Geography_Count": int(group["Source_ONS_Geography_Count"].sum()),
                "Source_Nomis_Geography_Count": int(group["Source_Nomis_Geography_Count"].sum()),
                "Mapping_Source": "|".join(sorted({str(value) for value in group["Mapping_Source"].dropna().astype(str)})),
                "Mean_Price": weighted_value(group["Mean_Price"], sales),
                "Median_Price": weighted_value(group["Median_Price"], sales),
                "Sales_Count": float(sales.fillna(0).sum()),
            }
        )

    out = pd.DataFrame(out_rows)

    # Add a London aggregate from borough rows while keeping borough cities like Westminster.
    if not out.empty and "London" not in set(out["City"].astype(str)):
        boroughs = frame[frame["City_Code"].astype(str).str.startswith("E09")].copy()
        if not boroughs.empty:
            sales = boroughs["Sales_Count"]
            out = pd.concat(
                [
                    out,
                    pd.DataFrame(
                        [
                            {
                                "City_Code": "E12000007",
                                "City": "London",
                                "Date": boroughs["Date"].iloc[0],
                                "Source_ONS_Geography_Count": int(boroughs["Source_ONS_Geography_Count"].sum()),
                                "Source_Nomis_Geography_Count": int(boroughs["Source_Nomis_Geography_Count"].sum()),
                                "Mapping_Source": "derived_london_borough_rollup",
                                "Mean_Price": weighted_value(boroughs["Mean_Price"], sales),
                                "Median_Price": weighted_value(boroughs["Median_Price"], sales),
                                "Sales_Count": float(sales.fillna(0).sum()),
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )

    return out.sort_values(["Date", "Mean_Price"], ascending=[False, False]).reset_index(drop=True)


def main() -> None:
    city_prices = load_house_prices_latest()
    city_prices = keep_city_only_rows(city_prices)
    city_prices.to_csv(OUTPUT_PATH, index=False)

    print(f"Wrote city summary to {OUTPUT_PATH}")
    print(city_prices.to_string(index=False))


if __name__ == "__main__":
    main()