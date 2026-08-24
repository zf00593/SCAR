#!/usr/bin/env python3
"""
calculate_regional_cpiu_timeseries.py
====================================

Creates a regional CPIU proxy time series from city-level house prices and
yearly national CPIU averages.

Inputs:
  - data/city_data/city_cost_timeseries.csv
  - data/ons_data/cpih yearly mean.csv

Method:
  1. For each year, compute UK mean city house price.
  2. Compute city CPIU proxy:
       city_cpiu_proxy = national_cpiu_year * (city_house_price / uk_mean_city_house_price_year)
  3. Map each city to a broad UK region using GEOGRAPHY_CODE prefix.
  4. Aggregate to region-year means and compute year-over-year change.

Output:
  - data/regional_data/regional_cpiu_timeseries.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"

CITY_TS_PATH = DATA_DIR / "city_data" / "city_cost_timeseries.csv"
NATIONAL_CPIU_PATH = DATA_DIR / "ons_data" / "cpih yearly mean.csv"
OUTPUT_PATH = DATA_DIR / "regional_data" / "regional_cpiu_timeseries.csv"


def map_broad_region_from_code(code: str) -> str:
    code = str(code)
    if code.startswith("E"):
        return "England"
    if code.startswith("W"):
        return "Wales"
    if code.startswith("S"):
        return "Scotland"
    if code.startswith("N"):
        return "Northern Ireland"
    if code.startswith("M"):
        return "Isle of Man"
    return "Other/Unknown"


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    city = pd.read_csv(CITY_TS_PATH, low_memory=False)
    national = pd.read_csv(NATIONAL_CPIU_PATH, low_memory=False)

    city["Year"] = pd.to_numeric(city["Year"], errors="coerce")
    city["House_Price"] = pd.to_numeric(city["House_Price"], errors="coerce")

    national["year"] = pd.to_numeric(national["year"], errors="coerce")
    national["mean_v4_0"] = pd.to_numeric(national["mean_v4_0"], errors="coerce")

    city = city.dropna(subset=["Year", "House_Price", "GEOGRAPHY_CODE"]).copy()
    national = national.dropna(subset=["year", "mean_v4_0"]).copy()

    city["Year"] = city["Year"].astype(int)
    national["year"] = national["year"].astype(int)

    return city, national


def main() -> None:
    city, national = load_inputs()

    national = national.rename(columns={"year": "Year", "mean_v4_0": "National_CPIU"})

    # UK yearly baseline from city house prices.
    uk_yearly_house_price = (
        city.groupby("Year", as_index=False)["House_Price"]
        .mean()
        .rename(columns={"House_Price": "UK_Mean_City_House_Price"})
    )

    city = city.merge(uk_yearly_house_price, on="Year", how="left")
    city = city.merge(national[["Year", "National_CPIU"]], on="Year", how="inner")

    city = city[city["UK_Mean_City_House_Price"] > 0].copy()
    city["City_CPIU_Proxy"] = (
        city["National_CPIU"] * city["House_Price"] / city["UK_Mean_City_House_Price"]
    )

    city["Region"] = city["GEOGRAPHY_CODE"].map(map_broad_region_from_code)

    regional = (
        city.groupby(["Year", "Region"], as_index=False)
        .agg(
            Regional_CPIU_Proxy=("City_CPIU_Proxy", "mean"),
            National_CPIU=("National_CPIU", "first"),
            Region_City_Count=("GEOGRAPHY_CODE", "nunique"),
        )
        .sort_values(["Region", "Year"])
        .reset_index(drop=True)
    )

    regional["Regional_CPIU_YoY_Change_Pct"] = (
        regional.groupby("Region")["Regional_CPIU_Proxy"].pct_change() * 100
    )
    regional["National_CPIU_YoY_Change_Pct"] = (
        regional.groupby("Region")["National_CPIU"].pct_change() * 100
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    regional.to_csv(OUTPUT_PATH, index=False)

    print(f"Saved: {OUTPUT_PATH}")
    print(f"Rows: {len(regional)}")
    print(f"Years: {regional['Year'].min()} to {regional['Year'].max()}")
    print(f"Regions: {', '.join(sorted(regional['Region'].unique()))}")


if __name__ == "__main__":
    main()
