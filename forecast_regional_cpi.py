#!/usr/bin/env python3
"""
forecast_regional_cpi.py
========================

Forecasts regional cost-of-living and wages for 2026-2035 using ARIMA models.
One model per region for:
  - Median weekly pay
  - Regional CPI proxy
  - Real wage index

Saves forecast results and visualizes trends.
"""

import pandas as pd
import numpy as np
from pathlib import Path
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
# LOAD DATA
# ============================================================================

data_dir = Path("data")
ts_data = pd.read_csv(data_dir / "regional_cpi_timeseries.csv")

print("="*80)
print("REGIONAL COST-OF-LIVING FORECASTS (2026-2035)")
print("="*80)
print(f"\nLoaded historical data: {len(ts_data)} records across {ts_data['Region'].nunique()} regions")
print(f"Historical period: {ts_data['Year'].min()} to {ts_data['Year'].max()}\n")

# ============================================================================
# PREPARE DATA FOR FORECASTING
# ============================================================================

# Get unique regions
regions = sorted(ts_data['Region'].dropna().unique())

forecast_results = []
forecast_years = list(range(2026, 2036))  # 2026-2035

print(f"Forecasting {len(regions)} regions for {len(forecast_years)} years...\n")

# ============================================================================
# FORECAST BY REGION
# ============================================================================

for region in regions:
    region_data = ts_data[ts_data['Region'] == region].sort_values('Year').copy()
    region_data = region_data.dropna(subset=['Median_Weekly_Pay', 'Regional_CPI_Proxy', 'Real_Wage_Index'])
    
    if len(region_data) < 5:
        print(f"  ⚠ {region}: insufficient data ({len(region_data)} years), skipping")
        continue
    
    # Extract time series
    years = region_data['Year'].values
    pay = region_data['Median_Weekly_Pay'].values
    cpi = region_data['Regional_CPI_Proxy'].values
    real_wage = region_data['Real_Wage_Index'].values
    
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
            z = np.polyfit(years, pay, 1)
            forecast_pay = np.polyval(z, forecast_years)
    else:
        # Linear trend extrapolation
        z = np.polyfit(years, pay, 1)
        forecast_pay = np.polyval(z, forecast_years)
    
    # ========================================================================
    # FORECAST CPI
    # ========================================================================
    
    if ARIMA_AVAILABLE:
        try:
            # Fit ARIMA(1,1,1) to CPI
            model_cpi = ARIMA(cpi, order=(1, 1, 1))
            fitted_cpi = model_cpi.fit()
            forecast_cpi = fitted_cpi.forecast(steps=len(forecast_years))
        except:
            z = np.polyfit(years, cpi, 1)
            forecast_cpi = np.polyval(z, forecast_years)
    else:
        z = np.polyfit(years, cpi, 1)
        forecast_cpi = np.polyval(z, forecast_years)
    
    # ========================================================================
    # CALCULATE FORECASTED REAL WAGE INDEX
    # ========================================================================
    
    forecast_real_wage = forecast_pay / forecast_cpi * 100
    
    # ========================================================================
    # STORE RESULTS
    # ========================================================================
    
    for i, year in enumerate(forecast_years):
        forecast_results.append({
            'Region': region,
            'Year': year,
            'Forecast_Weekly_Pay': forecast_pay[i],
            'Forecast_CPI_Proxy': forecast_cpi[i],
            'Forecast_Real_Wage_Index': forecast_real_wage[i]
        })

# Convert to DataFrame
forecast_df = pd.DataFrame(forecast_results)

# ============================================================================
# SAVE FORECAST
# ============================================================================

forecast_path = data_dir / "forecast_regional_cpi_2026_2035.csv"
forecast_df.to_csv(forecast_path, index=False)
print(f"✓ Forecast saved to: {forecast_path}")

# ============================================================================
# ANALYSIS: IDENTIFY EMERGING PATTERNS
# ============================================================================

print("\n" + "="*80)
print("FORECAST SUMMARY (2026-2035 averages)")
print("="*80)

# Merge historical and forecasted to compare
forecast_2025 = ts_data[ts_data['Year'] == 2025].copy()[['Region', 'Median_Weekly_Pay', 'Regional_CPI_Proxy', 'Real_Wage_Index']]
forecast_2025.columns = ['Region', 'Pay_2025', 'CPI_2025', 'Real_Wage_2025']

forecast_2035_avg = forecast_df.groupby('Region').agg({
    'Forecast_Weekly_Pay': 'mean',
    'Forecast_CPI_Proxy': 'mean',
    'Forecast_Real_Wage_Index': 'mean'
}).reset_index()
forecast_2035_avg.columns = ['Region', 'Avg_Pay_2026_2035', 'Avg_CPI_2026_2035', 'Avg_Real_Wage_2026_2035']

# Get 2035 endpoint values
forecast_2035_final = forecast_df[forecast_df['Year'] == 2035].copy()[
    ['Region', 'Forecast_Weekly_Pay', 'Forecast_CPI_Proxy', 'Forecast_Real_Wage_Index']
]
forecast_2035_final.columns = ['Region', 'Pay_2035', 'CPI_2035', 'Real_Wage_2035']

summary = forecast_2025.merge(forecast_2035_avg, on='Region').merge(forecast_2035_final, on='Region')

# Calculate changes
summary['Pay_Growth_2025_2035_%'] = ((summary['Pay_2035'] - summary['Pay_2025']) / summary['Pay_2025'] * 100).round(1)
summary['CPI_Growth_2025_2035_%'] = ((summary['Avg_CPI_2026_2035'] - summary['CPI_2025']) / summary['CPI_2025'] * 100).round(1)
summary['Real_Wage_Change_%'] = ((summary['Real_Wage_2035'] - summary['Real_Wage_2025']) / summary['Real_Wage_2025'] * 100).round(1)

# Sort by real wage change
summary_sorted = summary.sort_values('Real_Wage_Change_%', ascending=False)

# Display results
pd.options.display.float_format = '{:.1f}'.format
print("\nExpected Changes (2025 → 2035):")
print("-" * 80)
display_cols = ['Region', 'Pay_2025', 'Pay_2035', 'Pay_Growth_2025_2035_%', 'CPI_2025', 'Avg_CPI_2026_2035', 'CPI_Growth_2025_2035_%', 'Real_Wage_Change_%']
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
    print(f"\n✓ Regions with STRONG real wage growth (>5%):")
    for _, row in strong_growth.iterrows():
        print(f"  • {row['Region']}: +{row['Real_Wage_Change_%']:.1f}% (wages +{row['Pay_Growth_2025_2035_%']:.1f}%, inflation +{row['CPI_Growth_2025_2035_%']:.1f}%)")

# Regions at risk (inflation catching up to wages)
at_risk = summary_sorted[summary_sorted['Real_Wage_Change_%'] < 0].sort_values('Real_Wage_Change_%')
if len(at_risk) > 0:
    print(f"\n⚠ Regions at risk (real wage DECLINE forecast):")
    for _, row in at_risk.iterrows():
        print(f"  • {row['Region']}: {row['Real_Wage_Change_%']:.1f}% (wages +{row['Pay_Growth_2025_2035_%']:.1f}%, inflation +{row['CPI_Growth_2025_2035_%']:.1f}%)")

# Stable regions
stable = summary_sorted[(summary_sorted['Real_Wage_Change_%'] >= 0) & (summary_sorted['Real_Wage_Change_%'] <= 5)].sort_values('Real_Wage_Change_%')
if len(stable) > 0:
    print(f"\n→ Regions with STABLE real wages (0-5% growth):")
    for _, row in stable.iterrows():
        print(f"  • {row['Region']}: +{row['Real_Wage_Change_%']:.1f}% (wages +{row['Pay_Growth_2025_2035_%']:.1f}%, inflation +{row['CPI_Growth_2025_2035_%']:.1f}%)")

# ============================================================================
# REGIONAL RANKINGS
# ============================================================================

print("\n" + "="*80)
print("2035 REGIONAL RANKINGS")
print("="*80)

print("\nBy Nominal Wages (2035):")
pay_rank = summary_sorted.sort_values('Pay_2035', ascending=False)[['Region', 'Pay_2035']]
for i, (_, row) in enumerate(pay_rank.iterrows(), 1):
    print(f"  {i:2d}. {row['Region']:25s} £{row['Pay_2035']:.2f}/week")

print("\nBy Cost-of-Living (2035, higher = more expensive):")
cpi_rank = summary_sorted.sort_values('CPI_2035', ascending=False)[['Region', 'CPI_2035']]
for i, (_, row) in enumerate(cpi_rank.iterrows(), 1):
    print(f"  {i:2d}. {row['Region']:25s} CPI: {row['CPI_2035']:.1f}")

print("\nBy Real Purchasing Power (2035):")
real_rank = summary_sorted.sort_values('Real_Wage_2035', ascending=False)[['Region', 'Real_Wage_2035']]
for i, (_, row) in enumerate(real_rank.iterrows(), 1):
    print(f"  {i:2d}. {row['Region']:25s} Real Wage Index: {row['Real_Wage_2035']:.1f}")

print("\n" + "="*80)
