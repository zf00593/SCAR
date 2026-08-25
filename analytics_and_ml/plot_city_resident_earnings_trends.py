#!/usr/bin/env python3
"""
Plot resident earnings trends for SCAR cities over time.

This script mirrors the highlighting logic used in forecast_city_cpih.py:
- Context lines for all cities
- Highlight top X cities by latest-year earnings
- Always highlight best northern city and Sheffield (if present)
- Plot UK average across included cities

Inputs:
- data/city_house_prices_latest.csv
- data/nomis_data/nomis_ashe_resident_cities.csv
- visualisations_data/city_lat_long_lookup.csv (optional, for northern-city detection)

Output:
- plots/city_resident_earnings_trends.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
NOMIS_PATH = DATA_DIR / "nomis_data" / "nomis_ashe_resident_cities.csv"
CITY_UNIVERSE_PATH = DATA_DIR / "city_house_prices_latest.csv"
CITY_LAT_LON_PATH = ROOT_DIR / "visualisations_data" / "city_lat_long_lookup.csv"
DEFAULT_OUTPUT = ROOT_DIR / "plots" / "city_resident_earnings_trends.png"
OUT_TS = DATA_DIR / "city_data" / "city_resident_earnings_timeseries.csv"
OUT_FORECAST = DATA_DIR / "city_data" / "city_resident_earnings_forecast.csv"
OUT_FULL = DATA_DIR / "city_data" / "city_resident_earnings_full.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plot city resident earnings trends over time")
    parser.add_argument("--top-x", type=int, default=6, help="How many latest-year top-paying cities to highlight")
    parser.add_argument("--forecast-start", type=int, default=2023, help="First forecast year")
    parser.add_argument("--forecast-end", type=int, default=2035, help="Last forecast year")
    parser.add_argument(
        "--item",
        choices=["mean", "median"],
        default="mean",
        help="Use Mean or Median weekly pay from Nomis resident dataset",
    )
    parser.add_argument(
        "--noise-scale",
        type=float,
        default=1.0,
        help="Scale factor for forecast noise (0 disables noise)",
    )
    parser.add_argument("--noise-seed", type=int, default=42, help="Random seed for reproducible forecast noise")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output image path")
    return parser


def load_city_universe(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing city universe file: {path}")

    cities = pd.read_csv(path, low_memory=False)
    if "City" not in cities.columns:
        raise ValueError("city_house_prices_latest.csv must contain a 'City' column")

    return set(cities["City"].dropna().astype(str).str.strip().unique())


def load_resident_earnings(path: Path, city_universe: set[str], item_choice: str) -> tuple[pd.DataFrame, str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing resident earnings file: {path}")

    df = pd.read_csv(path, low_memory=False)

    required = {
        "DATE_NAME",
        "GEOGRAPHY_NAME",
        "OBS_VALUE",
        "SEX_NAME",
        "PAY_NAME",
        "ITEM_NAME",
        "MEASURES_NAME",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"nomis_ashe_resident_cities.csv missing columns: {sorted(missing)}")

    requested_item_name = "Mean" if item_choice.lower() == "mean" else "Median"
    item_name = requested_item_name

    value = df[
        (df["SEX_NAME"] == "Full Time Workers")
        & (df["PAY_NAME"] == "Weekly pay - gross")
        & (df["ITEM_NAME"] == item_name)
        & (df["MEASURES_NAME"] == "Value")
    ].copy()

    if value.empty and requested_item_name == "Mean":
        # Some extracts are median-only. Fall back so the pipeline still runs.
        item_name = "Median"
        value = df[
            (df["SEX_NAME"] == "Full Time Workers")
            & (df["PAY_NAME"] == "Weekly pay - gross")
            & (df["ITEM_NAME"] == item_name)
            & (df["MEASURES_NAME"] == "Value")
        ].copy()

    if value.empty:
        available = sorted(
            set(
                df[
                    (df["SEX_NAME"] == "Full Time Workers")
                    & (df["PAY_NAME"] == "Weekly pay - gross")
                    & (df["MEASURES_NAME"] == "Value")
                ]["ITEM_NAME"].dropna().astype(str)
            )
        )
        raise ValueError(
            f"No rows found for ITEM_NAME='{item_name}'. Available weekly-pay item values: {available}"
        )

    value["Year"] = pd.to_numeric(value["DATE_NAME"], errors="coerce")
    value["Weekly_Pay"] = pd.to_numeric(value["OBS_VALUE"], errors="coerce")
    value["City"] = value["GEOGRAPHY_NAME"].astype(str).str.strip()

    value = value.dropna(subset=["Year", "Weekly_Pay", "City"])
    value = value[value["City"].isin(city_universe)].copy()

    ts = (
        value.groupby(["City", "Year"], as_index=False)["Weekly_Pay"]
        .mean()
        .sort_values(["City", "Year"])
        .reset_index(drop=True)
    )
    ts["Year"] = ts["Year"].astype(int)
    return ts, item_name


def get_highest_northern_city(ts: pd.DataFrame) -> str | None:
    if not CITY_LAT_LON_PATH.exists():
        return None

    geo = pd.read_csv(CITY_LAT_LON_PATH, low_memory=False)
    if not {"city_name", "latitude"}.issubset(geo.columns):
        return None

    geo = geo[["city_name", "latitude"]].copy()
    geo["city_name"] = geo["city_name"].astype(str).str.strip()
    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
    geo = geo.dropna(subset=["city_name", "latitude"])

    ref_lat = geo[geo["city_name"].isin(["Cambridge", "Oxford", "London"])]["latitude"]
    if ref_lat.empty:
        return None

    threshold = float(ref_lat.max())
    latest_year = int(ts["Year"].max())
    latest = ts[ts["Year"] == latest_year].copy()
    latest = latest.merge(geo, left_on="City", right_on="city_name", how="left")

    north = latest[latest["latitude"] > threshold].sort_values("Weekly_Pay", ascending=False)
    if north.empty:
        return None
    return str(north.iloc[0]["City"])


def pick_highlight_cities(ts: pd.DataFrame, top_x: int) -> list[str]:
    latest_year = int(ts["Year"].max())
    latest = ts[ts["Year"] == latest_year].sort_values("Weekly_Pay", ascending=False)

    top_cities = latest.head(max(top_x, 1))["City"].tolist()

    highest_northern_city = get_highest_northern_city(ts)
    if highest_northern_city and highest_northern_city != "Winchester":
        if "Winchester" in top_cities:
            top_cities[top_cities.index("Winchester")] = highest_northern_city
        elif highest_northern_city not in top_cities and top_cities:
            top_cities[-1] = highest_northern_city

    must_highlight = []
    if highest_northern_city and highest_northern_city in ts["City"].values:
        must_highlight.append(highest_northern_city)
    if "Sheffield" in ts["City"].values:
        must_highlight.append("Sheffield")

    for city in must_highlight:
        if city not in top_cities:
            top_cities.append(city)

    deduped: list[str] = []
    for city in top_cities:
        if city not in deduped:
            deduped.append(city)

    return deduped


def city_noise_std_map(ts: pd.DataFrame) -> dict[str, float]:
    noise: dict[str, float] = {}
    for city, grp in ts.groupby("City"):
        s = grp.sort_values("Year")["Weekly_Pay"].astype(float)
        diffs = s.diff().dropna()
        if len(diffs) >= 2:
            std = float(diffs.std(ddof=1))
        elif len(s) >= 2:
            std = float(s.std(ddof=1) * 0.03)
        else:
            std = 0.0
        noise[str(city)] = max(std, 0.0)
    return noise


def forecast_city_earnings(
    ts: pd.DataFrame,
    forecast_start: int,
    forecast_end: int,
    noise_scale: float,
    noise_seed: int,
) -> pd.DataFrame:
    years = list(range(int(forecast_start), int(forecast_end) + 1))
    rows: list[dict[str, object]] = []
    rng = np.random.default_rng(noise_seed)
    noise_map = city_noise_std_map(ts)

    for city, grp in ts.groupby("City"):
        grp = grp.sort_values("Year")
        x = grp[["Year"]]
        y = grp["Weekly_Pay"].to_numpy()
        if len(grp) >= 2:
            model = LinearRegression().fit(x, y)
            pred = model.predict(pd.DataFrame({"Year": years}))
        else:
            pred = [float(y[0])] * len(years)

        city_std = float(noise_map.get(str(city), 0.0))
        noise = rng.normal(loc=0.0, scale=city_std * max(noise_scale, 0.0), size=len(years))
        pred = np.asarray(pred, dtype=float) + noise

        for year, value in zip(years, pred):
            rows.append(
                {
                    "City": city,
                    "Year": int(year),
                    "Weekly_Pay": max(float(value), 1.0),
                    "Type": "forecast",
                }
            )

    forecast = pd.DataFrame(rows)
    if forecast.empty:
        raise ValueError("No earnings forecasts produced.")

    return forecast.sort_values(["City", "Year"]).reset_index(drop=True)


def plot_earnings_trends(
    history: pd.DataFrame,
    forecast: pd.DataFrame,
    top_cities: list[str],
    output_path: Path,
    item_label: str,
) -> None:
    history_uk = (
        history.groupby("Year", as_index=False)["Weekly_Pay"]
        .mean()
        .rename(columns={"Weekly_Pay": "UK_Avg_Weekly_Pay"})
    )
    forecast_uk = (
        forecast.groupby("Year", as_index=False)["Weekly_Pay"]
        .mean()
        .rename(columns={"Weekly_Pay": "UK_Avg_Weekly_Pay"})
    )

    plt.figure(figsize=(14, 8))

    for city, grp in history.groupby("City"):
        plt.plot(grp["Year"], grp["Weekly_Pay"], color="#c7c7c7", linewidth=0.9, alpha=0.5)
    for city, grp in forecast.groupby("City"):
        plt.plot(grp["Year"], grp["Weekly_Pay"], color="#d9d9d9", linewidth=0.9, alpha=0.45, linestyle="--")

    colors = ["#0b4f6c", "#5f0f40", "#9a031e", "#fb8b24", "#3c6e71", "#2a9d8f"]
    sheffield_color = "#6a00f4"

    for i, city in enumerate(top_cities):
        h = history[history["City"] == city].sort_values("Year")
        f = forecast[forecast["City"] == city].sort_values("Year")
        if h.empty:
            continue
        color = sheffield_color if city == "Sheffield" else colors[i % len(colors)]
        plt.plot(h["Year"], h["Weekly_Pay"], color=color, linewidth=2.2, label=f"{city} (hist)")
        if not f.empty:
            plt.plot(f["Year"], f["Weekly_Pay"], color=color, linewidth=2.2, linestyle="--", label=f"{city} (fcst)")

    plt.plot(
        history_uk["Year"],
        history_uk["UK_Avg_Weekly_Pay"],
        color="#1d3557",
        linewidth=3,
        label="UK avg city resident weekly pay (hist)",
    )
    plt.plot(
        forecast_uk["Year"],
        forecast_uk["UK_Avg_Weekly_Pay"],
        color="#1d3557",
        linewidth=3,
        linestyle="--",
        label="UK avg city resident weekly pay (fcst)",
    )

    split_year = int(forecast["Year"].min()) if not forecast.empty else None
    if split_year is not None:
        plt.axvline(split_year - 0.5, color="#555555", linestyle=":", linewidth=1.5)
        plt.text(split_year - 0.2, plt.ylim()[1] * 0.98, "Forecast starts", fontsize=10, color="#444444")

    plt.title(f"Resident {item_label} Weekly Earnings by City Over Time", fontsize=16)
    plt.xlabel("Year")
    plt.ylabel(f"{item_label} Weekly Pay (£)")
    plt.grid(alpha=0.22)
    plt.legend(loc="upper left", ncol=2, fontsize=9)
    plt.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=170)
    plt.close()


def main() -> None:
    args = build_parser().parse_args()
    if args.forecast_end < args.forecast_start:
        raise ValueError("forecast-end must be >= forecast-start")

    city_universe = load_city_universe(CITY_UNIVERSE_PATH)
    history, actual_item = load_resident_earnings(NOMIS_PATH, city_universe, args.item)
    item_label = str(actual_item)

    if history.empty:
        raise ValueError("No resident earnings data available after filtering to city universe")

    history = history.copy()
    history["Type"] = "historical"
    forecast = forecast_city_earnings(
        history,
        args.forecast_start,
        args.forecast_end,
        noise_scale=args.noise_scale,
        noise_seed=args.noise_seed,
    )
    full = pd.concat([history, forecast], ignore_index=True).sort_values(["City", "Year"]).reset_index(drop=True)

    OUT_TS.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(OUT_TS, index=False)
    forecast.to_csv(OUT_FORECAST, index=False)
    full.to_csv(OUT_FULL, index=False)

    top_cities = pick_highlight_cities(history, args.top_x)
    plot_earnings_trends(history, forecast, top_cities, args.output, item_label)

    print(f"Pay metric requested: {'Mean' if args.item.lower() == 'mean' else 'Median'}")
    print(f"Pay metric used: {item_label}")
    if args.item.lower() == "mean" and item_label == "Median":
        print("Warning: Mean weekly-pay rows were not present in this resident-city extract, so Median was used.")
    print(f"Forecast noise scale: {args.noise_scale}")
    print(f"Forecast noise seed: {args.noise_seed}")
    print(f"Historical cities: {history['City'].nunique()}")
    print(f"Historical years: {history['Year'].min()} to {history['Year'].max()}")
    print(f"Forecast years: {args.forecast_start} to {args.forecast_end}")
    print(f"Highlighted cities: {', '.join(top_cities)}")
    print(f"Saved timeseries: {OUT_TS}")
    print(f"Saved forecast: {OUT_FORECAST}")
    print(f"Saved full: {OUT_FULL}")
    print(f"Saved plot: {args.output}")


if __name__ == "__main__":
    main()
