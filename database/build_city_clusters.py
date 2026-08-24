#!/usr/bin/env python3
"""
Build city similarity clusters (K-means) and export to CSV for database ingestion.

Usage:
  python database/build_city_clusters.py --base-dir . --k 4
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


OUTPUT_REL_PATH = Path("visualisations_data") / "city_kmeans_clusters.csv"


def to_year(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    try:
        return int(float(text))
    except ValueError:
        return None


def read_city_pay(path: Path, pay_col_name: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df = df[
        (df["MEASURES"].astype(str) == "20100")
        & (df["SEX_NAME"].astype(str) == "Full Time Workers")
        & (df["ITEM_NAME"].astype(str) == "Median")
        & (df["PAY_NAME"].astype(str) == "Weekly pay - gross")
    ].copy()

    df["_year"] = df["DATE"].map(to_year)
    latest_year = int(df["_year"].dropna().max())
    df = df[df["_year"] == latest_year].copy()

    out = df[["GEOGRAPHY_NAME", "OBS_VALUE"]].copy()
    out[pay_col_name] = pd.to_numeric(out["OBS_VALUE"], errors="coerce") * 52.0
    out = out.dropna(subset=[pay_col_name])

    return out.groupby("GEOGRAPHY_NAME", as_index=False)[pay_col_name].mean(), latest_year


def read_city_house_prices(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    out = df[["City", "Mean_Price"]].copy()
    out = out.rename(columns={"City": "GEOGRAPHY_NAME", "Mean_Price": "House_Price"})
    out["House_Price"] = pd.to_numeric(out["House_Price"], errors="coerce")
    return out.dropna(subset=["GEOGRAPHY_NAME", "House_Price"])


def build_clusters(base_dir: Path, k_value: int) -> pd.DataFrame:
    resident_path = base_dir / "data" / "nomis_data" / "nomis_ashe_resident_cities.csv"
    workplace_path = base_dir / "data" / "nomis_data" / "nomis_ashe_workplace_cities.csv"
    house_price_path = base_dir / "data" / "city_house_prices_latest.csv"

    for path in (resident_path, workplace_path, house_price_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing required file: {path}")

    resident, resident_year = read_city_pay(resident_path, "Pay_Resident")
    workplace, workplace_year = read_city_pay(workplace_path, "Pay_Workplace")
    salary_year = resident_year if resident_year <= workplace_year else workplace_year

    pay = resident.merge(workplace, on="GEOGRAPHY_NAME", how="inner")
    pay["Pay_Diff_Pct"] = (pay["Pay_Workplace"] - pay["Pay_Resident"]) / pay["Pay_Resident"] * 100.0

    house = read_city_house_prices(house_price_path)

    model_df = pay.merge(house, on="GEOGRAPHY_NAME", how="inner").dropna().reset_index(drop=True)
    if len(model_df) < k_value:
        raise ValueError(f"Not enough rows ({len(model_df)}) for k={k_value} clustering")

    feature_cols = ["Pay_Resident", "Pay_Workplace", "Pay_Diff_Pct", "House_Price"]
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(model_df[feature_cols])

    km = KMeans(n_clusters=k_value, random_state=42, n_init=20)
    model_df["cluster_id"] = km.fit_predict(x_scaled)

    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(x_scaled)
    model_df["pca_x"] = coords[:, 0]
    model_df["pca_y"] = coords[:, 1]

    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    model_df["year_num"] = salary_year
    model_df["model_version"] = f"kmeans_city_power_v1_k{k_value}"
    model_df["k_value"] = k_value
    model_df["run_ts_utc"] = now_utc

    return model_df[
        [
            "GEOGRAPHY_NAME",
            "year_num",
            "model_version",
            "k_value",
            "cluster_id",
            "Pay_Resident",
            "Pay_Workplace",
            "Pay_Diff_Pct",
            "House_Price",
            "pca_x",
            "pca_y",
            "run_ts_utc",
        ]
    ].rename(columns={"GEOGRAPHY_NAME": "city_name"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build city K-means cluster CSV for DB ingestion")
    parser.add_argument("--base-dir", default=".", help="Repo root containing data/ and visualisations_data/")
    parser.add_argument("--k", type=int, default=4, help="Number of clusters")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    base_dir = Path(args.base_dir).resolve()

    clusters = build_clusters(base_dir, args.k)

    out_path = base_dir / OUTPUT_REL_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clusters.to_csv(out_path, index=False)

    print(f"Wrote {len(clusters):,} rows to {out_path}")
    print(clusters.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
