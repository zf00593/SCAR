#!/usr/bin/env python3
"""
Build city CPIH proxy time series and ML forecast.

Formula:
    city_cpih_proxy = national_cpih_year * (city_mean_price_year / uk_weighted_mean_city_price_year)

Inputs:
- data/ons_data/cpih yearly mean.csv
- data/ons_data/ons_house_prices_local_authority.part*.csv
- data/geography_mapping/ons_to_nomis_geography_mapping.csv

Outputs:
- data/city_data/city_cpih_proxy_timeseries.csv
- data/city_data/city_cpih_proxy_forecast.csv
- data/city_data/city_cpih_proxy_full.csv
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
ONS_DATA_DIR = DATA_DIR / "ons_data"
MAPPING_PATH = DATA_DIR / "geography_mapping" / "ons_to_nomis_geography_mapping.csv"
HOUSE_PRICE_GLOB = "ons_house_prices_local_authority.part*.csv"
CPIH_INPUT = ONS_DATA_DIR / "cpih yearly mean.csv"

OUT_TS = DATA_DIR / "city_data" / "city_cpih_proxy_timeseries.csv"
OUT_FORECAST = DATA_DIR / "city_data" / "city_cpih_proxy_forecast.csv"
OUT_FULL = DATA_DIR / "city_data" / "city_cpih_proxy_full.csv"
CITY_UNIVERSE_INPUT = DATA_DIR / "city_house_prices_latest.csv"
CITY_LAT_LON_INPUT = ROOT_DIR / "visualisations_data" / "city_lat_long_lookup.csv"
PLOT_PATH = ROOT_DIR / "plots" / "city_cpih_timeseries_forecast.png"

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


def to_city_name(value: str, city_lookup: dict[str, str]) -> str | None:
    return city_lookup.get(normalize_name(value))


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


def load_house_price_base() -> pd.DataFrame:
    part_files = sorted(ONS_DATA_DIR.glob(HOUSE_PRICE_GLOB))
    if not part_files:
        raise FileNotFoundError(f"No files matched {HOUSE_PRICE_GLOB} in {ONS_DATA_DIR}")

    frames = [pd.read_csv(path, low_memory=False) for path in part_files]
    house_prices = pd.concat(frames, ignore_index=True)

    house_prices = house_prices[
        (house_prices["property-type"] == "all")
        & (house_prices["build-status"] == "all")
        & (house_prices["house-sales-and-prices"].isin(["mean", "sales"]))
    ].copy()

    house_prices["V4_1"] = pd.to_numeric(house_prices["V4_1"], errors="coerce")
    house_prices["Date"] = pd.to_datetime(
        house_prices["mmm"].astype(str).str.title() + "-" + house_prices["calendar-years"].astype(str),
        format="%b-%Y",
        errors="coerce",
    )

    house_prices = house_prices.dropna(subset=["Geography", "administrative-geography", "V4_1", "Date"])

    city_prices = (
        house_prices.pivot_table(
            index=["administrative-geography", "Geography", "Date"],
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
                "sales": "Sales_Count",
            }
        )
    )

    city_prices["Mean_Price"] = pd.to_numeric(city_prices["Mean_Price"], errors="coerce")
    city_prices["Sales_Count"] = pd.to_numeric(city_prices["Sales_Count"], errors="coerce")
    city_prices = city_prices.dropna(subset=["Mean_Price", "Sales_Count"]).copy()
    return city_prices


def map_to_city_aggregates(city_prices: pd.DataFrame) -> pd.DataFrame:
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

        if len(city_candidates) == 0 and is_county_like(str(row["City"])):
            return str(row["City"]).strip()
        return None

    frame["Target_City"] = frame.apply(assign_target, axis=1)
    frame = frame.dropna(subset=["Target_City"]).copy()

    out_rows = []
    for (target_city, date), group in frame.groupby(["Target_City", "Date"], dropna=False):
        weights = group["Sales_Count"].fillna(0).clip(lower=0)
        if float(weights.sum()) > 0:
            mean_price = float(np.average(group["Mean_Price"], weights=weights))
        else:
            mean_price = float(group["Mean_Price"].mean())

        out_rows.append(
            {
                "City": str(target_city),
                "Date": pd.to_datetime(date),
                "Mean_Price": mean_price,
                "Sales_Count": float(weights.sum()),
            }
        )

    out = pd.DataFrame(out_rows)

    # Add London aggregate from borough codes each month/date.
    boroughs = frame[frame["City_Code"].astype(str).str.startswith("E09")].copy()
    if not boroughs.empty:
        london_rows = []
        for date, group in boroughs.groupby("Date", dropna=False):
            weights = group["Sales_Count"].fillna(0).clip(lower=0)
            if float(weights.sum()) > 0:
                mean_price = float(np.average(group["Mean_Price"], weights=weights))
            else:
                mean_price = float(group["Mean_Price"].mean())

            london_rows.append(
                {
                    "City": "London",
                    "Date": pd.to_datetime(date),
                    "Mean_Price": mean_price,
                    "Sales_Count": float(weights.sum()),
                }
            )

        london_df = pd.DataFrame(london_rows)
        out = out[out["City"] != "London"]
        out = pd.concat([out, london_df], ignore_index=True)

    out = out.sort_values(["City", "Date"]).reset_index(drop=True)
    return out


def to_annual_city_prices(monthly: pd.DataFrame) -> pd.DataFrame:
    annual = monthly.copy()
    annual["Year"] = pd.to_datetime(annual["Date"], errors="coerce").dt.year
    annual = annual.dropna(subset=["Year", "Mean_Price"]).copy()
    annual["Year"] = annual["Year"].astype(int)

    rows = []
    for (city, year), group in annual.groupby(["City", "Year"], dropna=False):
        weights = group["Sales_Count"].fillna(0).clip(lower=0)
        if float(weights.sum()) > 0:
            mean_price = float(np.average(group["Mean_Price"], weights=weights))
        else:
            mean_price = float(group["Mean_Price"].mean())
        rows.append(
            {
                "City": str(city),
                "Year": int(year),
                "Mean_Price": mean_price,
                "Sales_Count": float(weights.sum()),
            }
        )

    out = pd.DataFrame(rows)
    return out.sort_values(["Year", "City"]).reset_index(drop=True)


def load_national_cpih() -> pd.DataFrame:
    cpih = pd.read_csv(CPIH_INPUT, low_memory=False)
    required = {"year", "mean_v4_0"}
    if not required.issubset(cpih.columns):
        raise ValueError(f"Missing required columns {required} in {CPIH_INPUT}")

    cpih["Year"] = pd.to_numeric(cpih["year"], errors="coerce")
    cpih["National_CPIH"] = pd.to_numeric(cpih["mean_v4_0"], errors="coerce")
    cpih = cpih.dropna(subset=["Year", "National_CPIH"]).copy()
    cpih["Year"] = cpih["Year"].astype(int)
    return cpih[["Year", "National_CPIH"]].sort_values("Year").reset_index(drop=True)


def build_city_cpih_timeseries() -> pd.DataFrame:
    monthly_city = map_to_city_aggregates(load_house_price_base())
    annual_city = to_annual_city_prices(monthly_city)

    if CITY_UNIVERSE_INPUT.exists():
        city_universe = pd.read_csv(CITY_UNIVERSE_INPUT, low_memory=False)
        if "City" in city_universe.columns:
            allowed = {str(v).strip() for v in city_universe["City"].dropna() if str(v).strip()}
            annual_city = annual_city[annual_city["City"].isin(allowed)].copy()

    cpih = load_national_cpih()

    data = annual_city.merge(cpih, on="Year", how="inner")

    weights_by_year = (
        data.groupby("Year", dropna=False)
        .apply(
            lambda grp: np.average(grp["Mean_Price"], weights=grp["Sales_Count"].fillna(0).clip(lower=0))
            if float(grp["Sales_Count"].fillna(0).clip(lower=0).sum()) > 0
            else grp["Mean_Price"].mean()
        )
        .reset_index(name="UK_Weighted_Mean_City_Price")
    )

    data = data.merge(weights_by_year, on="Year", how="left")
    data["City_CPIH_Proxy"] = data["National_CPIH"] * data["Mean_Price"] / data["UK_Weighted_Mean_City_Price"]
    data["Type"] = "historical"

    return data[[
        "City", "Year", "Mean_Price", "Sales_Count", "National_CPIH", "UK_Weighted_Mean_City_Price", "City_CPIH_Proxy", "Type"
    ]].sort_values(["City", "Year"]).reset_index(drop=True)


def linear_forecast(series: pd.Series, years: pd.Series, forecast_years: list[int]) -> list[float]:
    model = LinearRegression()
    x_train = years.to_numpy().reshape(-1, 1)
    y_train = series.to_numpy()
    model.fit(x_train, y_train)
    x_future = np.array(forecast_years).reshape(-1, 1)
    preds = model.predict(x_future)
    return [float(v) for v in preds]


def city_noise_std_map(history: pd.DataFrame) -> dict[str, float]:
    noise_std: dict[str, float] = {}
    for city, grp in history.groupby("City", dropna=False):
        city_hist = grp.sort_values("Year")
        if city_hist["Year"].nunique() < 3:
            noise_std[str(city)] = 0.0
            continue

        model = LinearRegression()
        x = city_hist["Year"].to_numpy().reshape(-1, 1)
        y = city_hist["City_CPIH_Proxy"].to_numpy()
        model.fit(x, y)
        residuals = y - model.predict(x)
        std_val = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
        noise_std[str(city)] = max(std_val, 0.0)
    return noise_std


def forecast_city_cpih(
    history: pd.DataFrame,
    forecast_start: int,
    forecast_end: int,
    noise_scale: float = 1.0,
    noise_seed: int = 42,
) -> pd.DataFrame:
    forecast_years = list(range(forecast_start, forecast_end + 1))

    nat_hist = (
        history[["Year", "National_CPIH"]]
        .drop_duplicates()
        .sort_values("Year")
        .reset_index(drop=True)
    )
    nat_forecast_vals = linear_forecast(nat_hist["National_CPIH"], nat_hist["Year"], forecast_years)
    nat_forecast = pd.DataFrame({"Year": forecast_years, "National_CPIH": nat_forecast_vals})

    last_sales = (
        history.sort_values("Year")
        .groupby("City", dropna=False)
        .tail(1)[["City", "Sales_Count"]]
        .reset_index(drop=True)
    )

    city_forecast_rows = []
    for city, grp in history.groupby("City", dropna=False):
        city_hist = grp.sort_values("Year")
        if city_hist["Year"].nunique() < 2:
            continue
        price_preds = linear_forecast(city_hist["Mean_Price"], city_hist["Year"], forecast_years)
        sales_weight = float(last_sales[last_sales["City"] == city]["Sales_Count"].iloc[0])
        for year, pred in zip(forecast_years, price_preds):
            city_forecast_rows.append(
                {
                    "City": str(city),
                    "Year": int(year),
                    "Mean_Price": max(float(pred), 1.0),
                    "Sales_Count": max(sales_weight, 0.0),
                }
            )

    city_forecast = pd.DataFrame(city_forecast_rows)
    if city_forecast.empty:
        raise ValueError("No city forecasts produced. Check history size per city.")

    city_forecast = city_forecast.merge(nat_forecast, on="Year", how="left")

    uk_weighted_forecast = (
        city_forecast.groupby("Year", dropna=False)
        .apply(
            lambda grp: np.average(grp["Mean_Price"], weights=grp["Sales_Count"].fillna(0).clip(lower=0))
            if float(grp["Sales_Count"].fillna(0).clip(lower=0).sum()) > 0
            else grp["Mean_Price"].mean()
        )
        .reset_index(name="UK_Weighted_Mean_City_Price")
    )

    city_forecast = city_forecast.merge(uk_weighted_forecast, on="Year", how="left")
    city_forecast["City_CPIH_Proxy"] = (
        city_forecast["National_CPIH"] * city_forecast["Mean_Price"] / city_forecast["UK_Weighted_Mean_City_Price"]
    )

    rng = np.random.default_rng(noise_seed)
    noise_map = city_noise_std_map(history)
    std_series = city_forecast["City"].map(lambda c: noise_map.get(str(c), 0.0)).fillna(0.0)
    noise = rng.normal(loc=0.0, scale=std_series.to_numpy() * max(noise_scale, 0.0), size=len(city_forecast))
    city_forecast["City_CPIH_Proxy"] = (city_forecast["City_CPIH_Proxy"] + noise).clip(lower=1.0)

    city_forecast["Type"] = "forecast"

    return city_forecast[[
        "City", "Year", "Mean_Price", "Sales_Count", "National_CPIH", "UK_Weighted_Mean_City_Price", "City_CPIH_Proxy", "Type"
    ]].sort_values(["City", "Year"]).reset_index(drop=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build city CPIH proxy timeseries and forecast")
    parser.add_argument("--forecast-start", type=int, default=2023)
    parser.add_argument("--forecast-end", type=int, default=2035)
    parser.add_argument("--noise-scale", type=float, default=1.0, help="Scale factor for forecast noise (0 disables noise)")
    parser.add_argument("--noise-seed", type=int, default=42, help="Random seed for reproducible forecast noise")
    return parser


def save_forecast_plot(history: pd.DataFrame, forecast: pd.DataFrame, out_path: Path) -> None:
    history_uk = (
        history.groupby("Year", as_index=False)["City_CPIH_Proxy"]
        .mean()
        .rename(columns={"City_CPIH_Proxy": "UK_Avg_City_CPIH_Proxy"})
    )
    forecast_uk = (
        forecast.groupby("Year", as_index=False)["City_CPIH_Proxy"]
        .mean()
        .rename(columns={"City_CPIH_Proxy": "UK_Avg_City_CPIH_Proxy"})
    )

    top_cities = (
        history[history["Year"] == history["Year"].max()]
        .sort_values("City_CPIH_Proxy", ascending=False)
        .head(6)["City"]
        .tolist()
    )

    # Replace Winchester in legend with the highest northern city.
    highest_northern_city = None
    if CITY_LAT_LON_INPUT.exists():
        geo = pd.read_csv(CITY_LAT_LON_INPUT, low_memory=False)
        if {"city_name", "latitude"}.issubset(geo.columns):
            geo = geo[["city_name", "latitude"]].copy()
            geo["city_name"] = geo["city_name"].astype(str).str.strip()
            geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
            geo = geo.dropna(subset=["city_name", "latitude"])

            ref_lat = geo[geo["city_name"].isin(["Cambridge", "Oxford", "London"])]["latitude"]
            if not ref_lat.empty:
                threshold = float(ref_lat.max())
                latest = history[history["Year"] == history["Year"].max()][["City", "City_CPIH_Proxy"]].copy()
                latest = latest.merge(geo, left_on="City", right_on="city_name", how="left")
                north = latest[latest["latitude"] > threshold].sort_values("City_CPIH_Proxy", ascending=False)
                if not north.empty:
                    highest_northern_city = str(north.iloc[0]["City"])

    if highest_northern_city and highest_northern_city != "Winchester":
        if "Winchester" in top_cities:
            top_cities[top_cities.index("Winchester")] = highest_northern_city
        elif highest_northern_city not in top_cities and top_cities:
            top_cities[-1] = highest_northern_city

    deduped = []
    for city in top_cities:
        if city not in deduped:
            deduped.append(city)
    top_cities = deduped

    plt.figure(figsize=(14, 8))

    # Show all city trajectories lightly for context.
    for city, grp in history.groupby("City"):
        plt.plot(grp["Year"], grp["City_CPIH_Proxy"], color="#c7c7c7", linewidth=0.9, alpha=0.5)
    for city, grp in forecast.groupby("City"):
        plt.plot(grp["Year"], grp["City_CPIH_Proxy"], color="#d9d9d9", linewidth=0.9, alpha=0.45, linestyle="--")

    colors = ["#0b4f6c", "#5f0f40", "#9a031e", "#fb8b24", "#3c6e71", "#2a9d8f"]
    for i, city in enumerate(top_cities):
        h = history[history["City"] == city].sort_values("Year")
        f = forecast[forecast["City"] == city].sort_values("Year")
        color = colors[i % len(colors)]
        plt.plot(h["Year"], h["City_CPIH_Proxy"], color=color, linewidth=2.2, label=f"{city} (hist)")
        if not f.empty:
            plt.plot(f["Year"], f["City_CPIH_Proxy"], color=color, linewidth=2.2, linestyle="--", label=f"{city} (fcst)")

    plt.plot(
        history_uk["Year"],
        history_uk["UK_Avg_City_CPIH_Proxy"],
        color="#1d3557",
        linewidth=3,
        label="UK avg city CPIH metric (hist)",
    )
    plt.plot(
        forecast_uk["Year"],
        forecast_uk["UK_Avg_City_CPIH_Proxy"],
        color="#1d3557",
        linewidth=3,
        linestyle="--",
        label="UK avg city CPIH metric (fcst)",
    )

    split_year = int(forecast["Year"].min()) if not forecast.empty else None
    if split_year is not None:
        plt.axvline(split_year - 0.5, color="#555555", linestyle=":", linewidth=1.5)
        plt.text(split_year - 0.2, plt.ylim()[1] * 0.98, "Forecast starts", fontsize=10, color="#444444")

    plt.title("City CPIH Metric Time Series and Forecast", fontsize=16)
    plt.xlabel("Year")
    plt.ylabel("City CPIH Metric")
    plt.grid(alpha=0.22)
    plt.legend(loc="upper left", ncol=2, fontsize=9)
    plt.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=170)
    plt.close()


def main() -> None:
    args = build_parser().parse_args()
    if args.forecast_end < args.forecast_start:
        raise ValueError("forecast-end must be >= forecast-start")

    history = build_city_cpih_timeseries()
    forecast = forecast_city_cpih(
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
    save_forecast_plot(history, forecast, PLOT_PATH)

    city_count = history["City"].nunique()
    print(f"Historical cities: {city_count}")
    print(f"Historical years: {history['Year'].min()} to {history['Year'].max()}")
    print(f"Forecast years: {args.forecast_start} to {args.forecast_end}")
    print(f"Saved: {OUT_TS}")
    print(f"Saved: {OUT_FORECAST}")
    print(f"Saved: {OUT_FULL}")
    print(f"Saved: {PLOT_PATH}")


if __name__ == "__main__":
    main()
