#!/usr/bin/env python3
"""
forecast_regional_cpi.py
========================

Forecasts city-level (local-authority) cost-of-living and wages for 2026-2035.

Data sources:
    - Nomis ASHE resident city earnings (data/nomis_data/nomis_ashe_resident_cities.csv)
    - ONS local-authority house prices (data/ons_data/ons_house_prices_local_authority*.csv)

One model per city for:
    - Median weekly pay
    - City house-price index (proxy for cost-of-living)
    - Real wage index

Saves forecast results and visualizes trends.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import glob
import warnings
warnings.filterwarnings('ignore')

# Try to import statsmodels for ARIMA
try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
    ARIMA_AVAILABLE = True
except ImportError:
    print("Warning: statsmodels not installed. Using simple trend extrapolation instead.")
    ARIMA_AVAILABLE = False

# ============================================================================
# LOAD CITY-LEVEL INPUTS
# ============================================================================

data_dir = Path("data")

ons_pattern = str(data_dir / "ons_data" / "ons_house_prices_local_authority*.csv")
ons_files = sorted(glob.glob(ons_pattern))
if not ons_files:
    raise FileNotFoundError("No ONS local-authority house price files found under data/ons_data")

ons = pd.concat([pd.read_csv(f, low_memory=False) for f in ons_files], ignore_index=True)

# ONS city-year house prices.
ons["Year"] = pd.to_numeric(ons.get("calendar-years"), errors="coerce")
ons["House_Price"] = pd.to_numeric(ons.get("V4_1"), errors="coerce")

# Current ONS extracts commonly use "Mean price" (and sometimes "Average").
price_mask = ons.get("HouseSalesAndPrices", pd.Series(index=ons.index, dtype=object)).astype(str).str.lower().str.contains("mean|average", na=False)
if "PropertyType" in ons.columns:
    price_mask &= ons["PropertyType"].astype(str).str.lower().eq("all")
if "BuildStatus" in ons.columns:
    price_mask &= ons["BuildStatus"].astype(str).str.lower().eq("all")

ons_price = ons[price_mask].copy()
ons_price = ons_price.dropna(subset=["Year", "House_Price", "administrative-geography", "Geography"])
ons_price["Year"] = ons_price["Year"].astype(int)

price_city = (
    ons_price.groupby(["administrative-geography", "Geography", "Year"], as_index=False)["House_Price"]
    .mean()
    .rename(columns={
        "administrative-geography": "GEOGRAPHY_CODE",
        "Geography": "City"
    })
)

# Rebase each city's house prices to first available year = 100.
price_base = (
    price_city.sort_values("Year")
    .groupby("GEOGRAPHY_CODE", as_index=False)
    .first()[["GEOGRAPHY_CODE", "House_Price"]]
    .rename(columns={"House_Price": "Base_House_Price"})
)
price_city = price_city.merge(price_base, on="GEOGRAPHY_CODE", how="left")
price_city = price_city[price_city["Base_House_Price"] > 0].copy()
price_city["City_House_Price_Index"] = price_city["House_Price"] / price_city["Base_House_Price"] * 100

ons_years = set(price_city["Year"].dropna().astype(int).tolist())

# Choose the Nomis resident file with the strongest year overlap to ONS data.
nomis_candidates = [
    data_dir / "nomis_data" / "nomis_ashe_resident_cities.csv",
    data_dir / "nomis_data" / "nomis_ashe_resident.csv",
]
nomis_candidates = [p for p in nomis_candidates if p.exists()]
if not nomis_candidates:
    raise FileNotFoundError("No Nomis resident earnings file found under data/nomis_data")

best_nomis_path = None
best_overlap = -1
best_nomis = None

for candidate in nomis_candidates:
    tmp = pd.read_csv(candidate, low_memory=False)
    tmp = tmp[tmp["MEASURES_NAME"].astype(str) == "Value"].copy()
    tmp["Year"] = pd.to_numeric(tmp["DATE_NAME"], errors="coerce")
    tmp["Median_Weekly_Pay"] = pd.to_numeric(tmp["OBS_VALUE"], errors="coerce")
    tmp = tmp.dropna(subset=["Year", "Median_Weekly_Pay", "GEOGRAPHY_CODE", "GEOGRAPHY_NAME"])
    if tmp.empty:
        continue
    tmp["Year"] = tmp["Year"].astype(int)
    overlap = len(set(tmp["Year"].unique()) & ons_years)
    if overlap > best_overlap:
        best_overlap = overlap
        best_nomis_path = candidate
        best_nomis = tmp

if best_nomis is None:
    raise RuntimeError("Nomis resident file(s) found but no usable pay rows were available.")

print(f"Using Nomis input: {best_nomis_path}")

pay_city = (
    best_nomis.groupby(["GEOGRAPHY_CODE", "GEOGRAPHY_NAME", "Year"], as_index=False)["Median_Weekly_Pay"]
    .mean()
)

# Build a combined city panel for output/inspection.
pay_city_named = pay_city.rename(columns={"GEOGRAPHY_NAME": "City"})
ts_data = pay_city_named.merge(
    price_city[["GEOGRAPHY_CODE", "City", "Year", "House_Price", "City_House_Price_Index"]],
    on=["GEOGRAPHY_CODE", "City", "Year"],
    how="outer"
)
ts_data["Real_Wage_Index"] = ts_data["Median_Weekly_Pay"] / ts_data["City_House_Price_Index"] * 100
ts_data = ts_data[[
    "Year", "GEOGRAPHY_CODE", "City", "Median_Weekly_Pay",
    "House_Price", "City_House_Price_Index", "Real_Wage_Index"
]]

overlap_count = len(
    pay_city[["GEOGRAPHY_CODE", "Year"]].drop_duplicates().merge(
        price_city[["GEOGRAPHY_CODE", "Year"]].drop_duplicates(),
        on=["GEOGRAPHY_CODE", "Year"],
        how="inner",
    )
)

print("="*80)
print("CITY-LEVEL COST-OF-LIVING FORECASTS (2026-2035)")
print("="*80)
print(f"\nLoaded city panel: {len(ts_data)} records across {ts_data['City'].nunique()} cities")
print(f"Panel period: {int(ts_data['Year'].min())} to {int(ts_data['Year'].max())}")
print(f"Overlapping city-year records (pay + price): {overlap_count}\n")

# ============================================================================
# PREPARE DATA FOR FORECASTING
# ============================================================================

# Forecast cities that have both pay and price histories by geography code.
cities = sorted(
    set(pay_city['GEOGRAPHY_CODE'].dropna().unique()) &
    set(price_city['GEOGRAPHY_CODE'].dropna().unique())
)

forecast_results = []
city_baselines = []
forecast_years = list(range(2026, 2036))  # 2026-2035

print(f"Forecasting {len(cities)} cities for {len(forecast_years)} years...\n")

# ============================================================================
# FORECAST BY CITY
# ============================================================================

for city_code in cities:
    city_pay = pay_city[pay_city['GEOGRAPHY_CODE'] == city_code].sort_values('Year').copy()
    city_price = price_city[price_city['GEOGRAPHY_CODE'] == city_code].sort_values('Year').copy()
    city_name = (
        city_price['City'].iloc[0]
        if not city_price.empty
        else (city_pay['GEOGRAPHY_NAME'].iloc[0] if not city_pay.empty else city_code)
    )

    if len(city_pay) < 2 or len(city_price) < 2:
        print(
            f"  ⚠ {city_name}: insufficient data "
            f"(pay={len(city_pay)} years, price={len(city_price)} years), skipping"
        )
        continue
    
    # Extract time series
    years_pay = city_pay['Year'].values
    pay = city_pay['Median_Weekly_Pay'].values
    years_cpi = city_price['Year'].values
    cpi = city_price['City_House_Price_Index'].values
    
    # ========================================================================
    # FORECAST PAY
    # ========================================================================
    
    if ARIMA_AVAILABLE:
        try:
            # Fit ARIMA(1,1,1) to weekly pay
            model_pay = ARIMA(pay, order=(1, 1, 1))
            fitted_pay = model_pay.fit()
            forecast_pay = fitted_pay.forecast(steps=len(forecast_years))
        except:
            # Fallback to linear trend
            z = np.polyfit(years_pay, pay, 1)
            forecast_pay = np.polyval(z, forecast_years)
    else:
        # Linear trend extrapolation
        z = np.polyfit(years_pay, pay, 1)
        forecast_pay = np.polyval(z, forecast_years)
    
    # ========================================================================
    # FORECAST CPI
    # ========================================================================
    
    if ARIMA_AVAILABLE:
        try:
            # Fit ARIMA(1,1,1) to city house-price index proxy
            model_cpi = ARIMA(cpi, order=(1, 1, 1))
            fitted_cpi = model_cpi.fit()
            forecast_cpi = fitted_cpi.forecast(steps=len(forecast_years))
        except:
            z = np.polyfit(years_cpi, cpi, 1)
            forecast_cpi = np.polyval(z, forecast_years)
    else:
        z = np.polyfit(years_cpi, cpi, 1)
        forecast_cpi = np.polyval(z, forecast_years)

    # Keep forecasted levels positive when trends from sparse history become unstable.
    forecast_pay = np.maximum(forecast_pay, 1e-6)
    forecast_cpi = np.maximum(forecast_cpi, 1e-6)
    
    # ========================================================================
    # CALCULATE FORECASTED REAL WAGE INDEX
    # ========================================================================
    
    forecast_real_wage = forecast_pay / forecast_cpi * 100
    
    # ========================================================================
    # STORE RESULTS
    # ========================================================================

    pay_base_year = int(city_pay['Year'].max())
    pay_base_value = float(city_pay.loc[city_pay['Year'] == pay_base_year, 'Median_Weekly_Pay'].iloc[0])
    cpi_base_year = int(city_price['Year'].max())
    cpi_base_value = float(city_price.loc[city_price['Year'] == cpi_base_year, 'City_House_Price_Index'].iloc[0])
    real_base_value = pay_base_value / cpi_base_value * 100 if cpi_base_value != 0 else np.nan

    city_baselines.append({
        'GEOGRAPHY_CODE': city_code,
        'City': city_name,
        'Pay_Base_Year': pay_base_year,
        'Pay_Base': pay_base_value,
        'CPI_Base_Year': cpi_base_year,
        'CPI_Base': cpi_base_value,
        'Real_Wage_Base': real_base_value,
    })
    
    for i, year in enumerate(forecast_years):
        forecast_results.append({
            'GEOGRAPHY_CODE': city_code,
            'City': city_name,
            'Year': year,
            'Forecast_Weekly_Pay': forecast_pay[i],
            'Forecast_City_House_Price_Index': forecast_cpi[i],
            'Forecast_Real_Wage_Index': forecast_real_wage[i]
        })

# Convert to DataFrame
forecast_df = pd.DataFrame(forecast_results)

# ============================================================================
# SAVE FORECAST
# ============================================================================

city_out_dir = data_dir / "city_data"
city_out_dir.mkdir(parents=True, exist_ok=True)

city_ts_path = city_out_dir / "city_cost_timeseries.csv"
ts_data.to_csv(city_ts_path, index=False)

forecast_path = city_out_dir / "forecast_city_cost_2026_2035.csv"
forecast_df.to_csv(forecast_path, index=False)
print(f"✓ City timeseries saved to: {city_ts_path}")
print(f"✓ Forecast saved to: {forecast_path}")

# ============================================================================
# ANALYSIS: IDENTIFY EMERGING PATTERNS
# ============================================================================

print("\n" + "="*80)
print("FORECAST SUMMARY (2026-2035 averages)")
print("="*80)

if forecast_df.empty:
    raise RuntimeError("No city forecasts were generated. Check data coverage and filtering settings.")

baseline = pd.DataFrame(city_baselines)

forecast_2035_avg = forecast_df.groupby(['GEOGRAPHY_CODE', 'City']).agg({
    'Forecast_Weekly_Pay': 'mean',
    'Forecast_City_House_Price_Index': 'mean',
    'Forecast_Real_Wage_Index': 'mean'
}).reset_index()
forecast_2035_avg.columns = [
    'GEOGRAPHY_CODE', 'City', 'Avg_Pay_2026_2035',
    'Avg_CPI_2026_2035', 'Avg_Real_Wage_2026_2035'
]

# Get 2035 endpoint values
forecast_2035_final = forecast_df[forecast_df['Year'] == 2035].copy()[
    ['GEOGRAPHY_CODE', 'City', 'Forecast_Weekly_Pay',
     'Forecast_City_House_Price_Index', 'Forecast_Real_Wage_Index']
]
forecast_2035_final.columns = ['GEOGRAPHY_CODE', 'City', 'Pay_2035', 'CPI_2035', 'Real_Wage_2035']

summary = baseline.merge(forecast_2035_avg, on=['GEOGRAPHY_CODE', 'City']).merge(
    forecast_2035_final, on=['GEOGRAPHY_CODE', 'City']
)

# Calculate changes
summary['Pay_Growth_Base_2035_%'] = ((summary['Pay_2035'] - summary['Pay_Base']) / summary['Pay_Base'] * 100).round(1)
summary['CPI_Growth_Base_2035_%'] = ((summary['Avg_CPI_2026_2035'] - summary['CPI_Base']) / summary['CPI_Base'] * 100).round(1)
summary['Real_Wage_Change_%'] = ((summary['Real_Wage_2035'] - summary['Real_Wage_Base']) / summary['Real_Wage_Base'] * 100).round(1)

# Sort by real wage change
summary_sorted = summary.sort_values('Real_Wage_Change_%', ascending=False)

# Display results
pd.options.display.float_format = '{:.1f}'.format
print("\nExpected Changes (Latest observed pay/price baseline → 2035):")
print("-" * 80)
display_cols = [
    'City', 'Pay_Base', 'Pay_2035', 'Pay_Growth_Base_2035_%',
    'CPI_Base', 'Avg_CPI_2026_2035', 'CPI_Growth_Base_2035_%',
    'Real_Wage_Change_%'
]
print(summary_sorted[display_cols].to_string(index=False))

# ============================================================================
# FORECAST TRENDS
# ============================================================================

print("\n" + "="*80)
print("FORECAST INSIGHTS")
print("="*80)

# Regions with strongest real wage growth forecast
strong_growth = summary_sorted[summary_sorted['Real_Wage_Change_%'] > 5].sort_values('Real_Wage_Change_%', ascending=False)
if len(strong_growth) > 0:
    print(f"\n✓ Cities with STRONG real wage growth (>5%):")
    for _, row in strong_growth.iterrows():
        print(
            f"  • {row['City']}: +{row['Real_Wage_Change_%']:.1f}% "
            f"(wages +{row['Pay_Growth_Base_2035_%']:.1f}%, inflation +{row['CPI_Growth_Base_2035_%']:.1f}%)"
        )

# Regions at risk (inflation catching up to wages)
at_risk = summary_sorted[summary_sorted['Real_Wage_Change_%'] < 0].sort_values('Real_Wage_Change_%')
if len(at_risk) > 0:
    print(f"\n⚠ Cities at risk (real wage DECLINE forecast):")
    for _, row in at_risk.iterrows():
        print(
            f"  • {row['City']}: {row['Real_Wage_Change_%']:.1f}% "
            f"(wages +{row['Pay_Growth_Base_2035_%']:.1f}%, inflation +{row['CPI_Growth_Base_2035_%']:.1f}%)"
        )

# Stable regions
stable = summary_sorted[(summary_sorted['Real_Wage_Change_%'] >= 0) & (summary_sorted['Real_Wage_Change_%'] <= 5)].sort_values('Real_Wage_Change_%')
if len(stable) > 0:
    print(f"\n→ Cities with STABLE real wages (0-5% growth):")
    for _, row in stable.iterrows():
        print(
            f"  • {row['City']}: +{row['Real_Wage_Change_%']:.1f}% "
            f"(wages +{row['Pay_Growth_Base_2035_%']:.1f}%, inflation +{row['CPI_Growth_Base_2035_%']:.1f}%)"
        )

# ============================================================================
# REGIONAL RANKINGS
# ============================================================================

print("\n" + "="*80)
print("2035 CITY RANKINGS")
print("="*80)

print("\nBy Nominal Wages (2035):")
pay_rank = summary_sorted.sort_values('Pay_2035', ascending=False)[['City', 'Pay_2035']]
for i, (_, row) in enumerate(pay_rank.iterrows(), 1):
    print(f"  {i:2d}. {row['City']:35s} £{row['Pay_2035']:.2f}/week")

print("\nBy Cost-of-Living (2035, higher = more expensive):")
cpi_rank = summary_sorted.sort_values('CPI_2035', ascending=False)[['City', 'CPI_2035']]
for i, (_, row) in enumerate(cpi_rank.iterrows(), 1):
    print(f"  {i:2d}. {row['City']:35s} Index: {row['CPI_2035']:.1f}")

print("\nBy Real Purchasing Power (2035):")
real_rank = summary_sorted.sort_values('Real_Wage_2035', ascending=False)[['City', 'Real_Wage_2035']]
for i, (_, row) in enumerate(real_rank.iterrows(), 1):
    print(f"  {i:2d}. {row['City']:35s} Real Wage Index: {row['Real_Wage_2035']:.1f}")

print("\n" + "="*80)

summary_path = city_out_dir / "forecast_city_summary_2035.csv"
summary_sorted.to_csv(summary_path, index=False)
print(f"Summary saved to: {summary_path}")
