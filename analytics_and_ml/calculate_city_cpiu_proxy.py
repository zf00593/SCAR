#!/usr/bin/env python3
"""
calculate_city_cpiu_proxy.py
============================

Builds a city-level CPIU proxy for 2022 using:
  1. National CPIU index (2022) from a yearly mean dataset.
  2. City mean house prices (2022).

Proxy formula:
    city_cpiu_proxy_2022 = national_cpiu_2022 * (city_mean_price / uk_weighted_mean_city_price_2022)

Output:
    data/city_data/city_cpiu_proxy_2022.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"

CPIU_INPUT = DATA_DIR / "ons_data" / "cpih yearly mean.csv"
CITY_PRICE_INPUT = DATA_DIR / "city_house_prices_latest.csv"
OUTPUT_PATH = DATA_DIR / "city_data" / "city_cpiu_proxy_2022.csv"

TARGET_YEAR = 2022


def load_national_cpiu_2022(path: Path, year: int) -> float:
    frame = pd.read_csv(path)
    required = {"year", "mean_v4_0"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing required columns {required} in {path}")

    frame["year"] = pd.to_numeric(frame["year"], errors="coerce")
    frame["mean_v4_0"] = pd.to_numeric(frame["mean_v4_0"], errors="coerce")

    row = frame[frame["year"] == year]
    if row.empty:
        raise ValueError(f"No national CPIU value found for year {year} in {path}")

    value = row["mean_v4_0"].iloc[0]
    if pd.isna(value):
        raise ValueError(f"National CPIU value for year {year} is missing in {path}")
    return float(value)


def calculate_city_proxy(city_path: Path, national_cpiu_2022: float) -> pd.DataFrame:
    city = pd.read_csv(city_path)
    required = {"City_Code", "City", "Date", "Mean_Price", "Sales_Count"}
    if not required.issubset(city.columns):
        raise ValueError(f"Missing required columns {required} in {city_path}")

    city["Date"] = pd.to_datetime(city["Date"], errors="coerce")
    city["Year"] = city["Date"].dt.year
    city["Mean_Price"] = pd.to_numeric(city["Mean_Price"], errors="coerce")
    city["Sales_Count"] = pd.to_numeric(city["Sales_Count"], errors="coerce")

    city_2022 = city[(city["Year"] == TARGET_YEAR) & city["Mean_Price"].notna()].copy()
    if city_2022.empty:
        raise ValueError(f"No city house price rows found for year {TARGET_YEAR} in {city_path}")

    valid_weights = city_2022["Sales_Count"].fillna(0).clip(lower=0)
    if float(valid_weights.sum()) > 0:
        uk_weighted_mean = float(np.average(city_2022["Mean_Price"], weights=valid_weights))
    else:
        uk_weighted_mean = float(city_2022["Mean_Price"].mean())

    city_2022["National_CPIU_2022"] = national_cpiu_2022
    city_2022["UK_Weighted_Mean_City_Price_2022"] = uk_weighted_mean
    city_2022["City_CPIU_Proxy_2022"] = (
        city_2022["National_CPIU_2022"] * city_2022["Mean_Price"] / city_2022["UK_Weighted_Mean_City_Price_2022"]
    )

    output = city_2022[
        [
            "City_Code",
            "City",
            "Date",
            "Mean_Price",
            "Sales_Count",
            "National_CPIU_2022",
            "UK_Weighted_Mean_City_Price_2022",
            "City_CPIU_Proxy_2022",
        ]
    ].copy()
    output = output.sort_values("City_CPIU_Proxy_2022", ascending=False).reset_index(drop=True)
    return output


def main() -> None:
    national_cpiu_2022 = load_national_cpiu_2022(CPIU_INPUT, TARGET_YEAR)
    result = calculate_city_proxy(CITY_PRICE_INPUT, national_cpiu_2022)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)

    print(f"Saved city CPIU proxy dataset: {OUTPUT_PATH}")
    print(f"Rows: {len(result)}")
    print(f"National CPIU 2022 used: {national_cpiu_2022:.4f}")
    print(f"Top 10 cities by CPIU proxy:\n{result[['City', 'City_CPIU_Proxy_2022']].head(10).to_string(index=False)}")


if __name__ == "__main__":
    main()
