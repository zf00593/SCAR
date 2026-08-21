#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
NOMIS_DIR = DATA_DIR / "nomis_data"

HOUSE_PATH = DATA_DIR / "city_house_prices_latest.csv"
RESIDENT_PATH = NOMIS_DIR / "nomis_ashe_resident_cities.csv"
WORKPLACE_PATH = NOMIS_DIR / "nomis_ashe_workplace_cities.csv"
OUTPUT_PATH = DATA_DIR / "city_model_dataset.csv"


def normalize_name(value: str) -> str:
    text = str(value).strip().lower()
    text = text.replace("&", " and ")
    text = text.replace("-", " ")
    text = text.replace(",", " ")
    text = text.replace(".", " ")
    text = text.replace("'", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def latest_salary_frame(path: Path, value_name: str, proxy_prefix: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df = pd.read_csv(path, low_memory=False)
    # Keep the same ASHE measure used in clustering (median full-time gross weekly).
    mask = (
        (df["MEASURES"].astype(str) == "20100")
        & (df["SEX_NAME"].astype(str) == "Full Time Workers")
        & (df["ITEM_NAME"].astype(str) == "Median")
        & (df["PAY_NAME"].astype(str) == "Weekly pay - gross")
    )
    df = df[mask].copy()

    df["DATE"] = pd.to_numeric(df["DATE"], errors="coerce")
    latest_year = int(df["DATE"].max())
    df = df[df["DATE"] == latest_year].copy()

    df["OBS_VALUE"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    df[value_name] = df["OBS_VALUE"] * 52
    df["City"] = df["GEOGRAPHY_NAME"].astype(str).str.strip()
    df["City_Key"] = df["City"].map(normalize_name)

    out = (
        df.groupby(["City", "City_Key"], as_index=False)
        .agg(
            **{
                value_name: (value_name, "mean"),
                f"{proxy_prefix}_Proxy_Flag": ("Proxy_Flag", "max"),
                f"{proxy_prefix}_Proxy_Source": (
                    "Proxy_Source",
                    lambda values: "|".join(sorted({str(v) for v in values if pd.notna(v)})),
                ),
                f"{proxy_prefix}_Source_Geography_Count": ("Source_Geography_Count", "max"),
            }
        )
    )
    out[f"{proxy_prefix}_Year"] = latest_year
    return out


def main() -> None:
    if not HOUSE_PATH.exists():
        raise FileNotFoundError(f"Missing file: {HOUSE_PATH}")

    house = pd.read_csv(HOUSE_PATH, low_memory=False)
    house["City"] = house["City"].astype(str).str.strip()
    house["City_Key"] = house["City"].map(normalize_name)

    resident = latest_salary_frame(RESIDENT_PATH, "Pay_Resident", "Resident")
    workplace = latest_salary_frame(WORKPLACE_PATH, "Pay_Workplace", "Workplace")

    merged = house.merge(
        resident,
        how="left",
        on=["City", "City_Key"],
        validate="one_to_one",
    )
    merged = merged.merge(
        workplace,
        how="left",
        on=["City", "City_Key"],
        validate="one_to_one",
    )

    merged["Pay_Diff_Pct"] = (
        (merged["Pay_Workplace"] - merged["Pay_Resident"]) / merged["Pay_Resident"] * 100
    )

    merged = merged.rename(columns={"Mean_Price": "House_Price"})

    merged["Any_Proxy_Flag"] = (
        merged["Proxy_Flag"].fillna(False)
        | merged["Resident_Proxy_Flag"].fillna(False)
        | merged["Workplace_Proxy_Flag"].fillna(False)
    )

    before = len(house)
    after = len(merged)
    if after != before:
        raise RuntimeError(f"Row count changed unexpectedly: house={before}, merged={after}")

    merged = merged.drop(columns=["City_Key"])
    merged.to_csv(OUTPUT_PATH, index=False)

    print(f"Wrote: {OUTPUT_PATH} ({len(merged):,} rows)")
    print(f"Rows unchanged from house base: {before} -> {after}")
    print(f"Rows with salary available: {int(merged['Pay_Resident'].notna().sum())}")


if __name__ == "__main__":
    main()
