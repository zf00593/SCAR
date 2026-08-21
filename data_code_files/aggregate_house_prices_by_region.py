#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
ONS_DATA_DIR = DATA_DIR / "ons_data"
DEMOGRAPHIC_DATA_DIR = DATA_DIR / "demographic_data"
HOUSE_PRICE_GLOB = "ons_house_prices_local_authority_final.part*.csv"
REGION_LOOKUP_PATH = DEMOGRAPHIC_DATA_DIR / "sex_with_region.csv"
OUTPUT_PATH = DATA_DIR / "regional_house_prices_latest.csv"


def normalize_name(value: str) -> str:
    text = str(value).strip().lower()
    text = text.replace("&", " and ")
    text = text.replace("-", " ")
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    ordered = pd.DataFrame({"value": values, "weight": weights}).sort_values("value")
    cumulative_weight = ordered["weight"].cumsum()
    midpoint = ordered["weight"].sum() / 2
    return float(ordered.loc[cumulative_weight >= midpoint, "value"].iloc[0])


def load_region_lookup() -> pd.DataFrame:
    lookup = pd.read_csv(REGION_LOOKUP_PATH, low_memory=False)
    lookup = lookup[["Lower tier local authorities", "geography"]].copy()
    lookup["City"] = lookup["Lower tier local authorities"].map(normalize_name)
    lookup = lookup.rename(columns={"geography": "Region"})
    lookup = lookup[["City", "Region"]].dropna().drop_duplicates()
    return lookup


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

    house_prices["Price_Value"] = pd.to_numeric(house_prices["V4_1"], errors="coerce")
    house_prices["Date"] = pd.to_datetime(
        house_prices["mmm"].astype(str).str.title() + "-" + house_prices["calendar-years"].astype(str),
        format="%b-%Y",
        errors="coerce",
    )
    house_prices = house_prices.dropna(subset=["Geography", "Price_Value", "Date"])

    latest_date = house_prices["Date"].max()
    house_prices = house_prices[house_prices["Date"] == latest_date].copy()

    pivoted = (
        house_prices.pivot_table(
            index=["administrative-geography", "Geography", "Date"],
            columns="house-sales-and-prices",
            values="Price_Value",
            aggfunc="first",
        )
        .reset_index()
        .rename_axis(columns=None)
    )

    pivoted["City"] = pivoted["Geography"].map(normalize_name)
    return pivoted.rename(
        columns={
            "mean": "Local_Mean_Price",
            "median": "Local_Median_Price",
            "sales": "Sales_Count",
        }
    )


def build_regional_summary() -> pd.DataFrame:
    region_lookup = load_region_lookup()
    latest_prices = load_house_prices_latest()

    merged = latest_prices.merge(region_lookup, on="City", how="left")
    merged = merged.dropna(subset=["Region", "Local_Mean_Price", "Local_Median_Price", "Sales_Count"])

    regional = (
        merged.groupby(["Region"], as_index=False)
        .apply(
            lambda group: pd.Series(
                {
                    "Regional_Mean_Price": np.average(
                        group["Local_Mean_Price"], weights=group["Sales_Count"]
                    ),
                    "Regional_Median_Price_Approx": weighted_median(
                        group["Local_Median_Price"], group["Sales_Count"]
                    ),
                    "Regional_Sales_Count": group["Sales_Count"].sum(),
                    "Local_Authority_Count": group["administrative-geography"].nunique(),
                    "Date": group["Date"].iloc[0],
                }
            )
        )
        .reset_index(drop=True)
    )

    return regional.sort_values("Regional_Mean_Price", ascending=False).reset_index(drop=True)


def main() -> None:
    regional_summary = build_regional_summary()
    regional_summary.to_csv(OUTPUT_PATH, index=False)

    print(f"Wrote regional summary to {OUTPUT_PATH}")
    print(regional_summary.to_string(index=False))
    print()
    print("Note: Regional_Median_Price_Approx is a sales-weighted median of local-authority medians.")
    print("A true regional median needs transaction-level data, not published summary medians.")


if __name__ == "__main__":
    main()