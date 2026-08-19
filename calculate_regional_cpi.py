#!/usr/bin/env python3
"""
calculate_regional_cpi.py
=========================

Constructs a regional cost-of-living proxy by combining:
  1. UK-wide CPIH inflation index
  2. Regional rental price indexes
  3. Regional earnings (Nomis ASHE)

Formula:
    regional_cpi_proxy = (national_cpih_index * regional_rental_price_index) / national_rental_price_index

Output: CSV with regional cost-of-living estimates over time
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================================
# LOAD DATA
# ============================================================================

data_dir = Path("data")

# 1. Load CPIH (national inflation by category)
print("Loading CPIH...")
cpih = pd.read_csv(data_dir / "ons_cpih01.csv")
print(f"  {len(cpih)} rows, {cpih['Time'].nunique()} time periods")

# 2. Load Rental Price Index (regional)
print("Loading Rental Price Index...")
rental = pd.read_csv(data_dir / "ons_index_private_housing_rental_prices.csv")
print(f"  {len(rental)} rows, {rental['Geography'].nunique()} regions")

# 3. Load ASHE Earnings (regional)
print("Loading ASHE Resident Earnings...")
ashe_resident = pd.read_csv(data_dir / "nomis_ashe_resident.csv")
print(f"  {len(ashe_resident)} rows, {ashe_resident['GEOGRAPHY_NAME'].nunique()} regions")

# ============================================================================
# PROCESS CPIH - Get overall index by time period
# ============================================================================
print("\nProcessing CPIH...")

# Filter to UK-wide aggregate only, extract numeric values
cpih_clean = cpih[cpih['Geography'] == 'United Kingdom'].copy()
cpih_clean['v4_0'] = pd.to_numeric(cpih_clean['v4_0'], errors='coerce')

# Calculate average CPIH index per time period (unweighted average across categories)
cpih_by_time = cpih_clean.groupby('Time')['v4_0'].agg(['mean', 'median', 'count']).reset_index()
cpih_by_time.columns = ['Time', 'cpih_mean', 'cpih_median', 'cpih_count']
print(f"  Aggregated to {len(cpih_by_time)} time periods")
print(f"  Time range: {cpih_by_time['Time'].min()} to {cpih_by_time['Time'].max()}")
print(f"\n  CPIH Summary (mean index):\n{cpih_by_time.head(10)}")

# ============================================================================
# PROCESS RENTAL PRICES - Filter to index values only
# ============================================================================
print("\nProcessing Rental Price Index...")

# Keep only "index" rows, not year-on-year changes
rental_index = rental[rental['IndexAndYearChange'] == 'Index'].copy()
rental_index['v4_1'] = pd.to_numeric(rental_index['v4_1'], errors='coerce')

# Get the most recent time period with full regional coverage
latest_time = rental_index['Time'].max()
rental_latest = rental_index[rental_index['Time'] == latest_time].copy()

print(f"  Latest time period: {latest_time}")
print(f"  Regions available: {rental_latest['Geography'].nunique()}")
print(f"\n  Regional Rental Price Index ({latest_time}):\n{rental_latest[['Geography', 'v4_1']].sort_values('v4_1', ascending=False)}")

# ============================================================================
# PROCESS ASHE - Get latest median weekly pay by region
# ============================================================================
print("\nProcessing ASHE Earnings...")

# Filter to median pay values only
ashe_median = ashe_resident[ashe_resident['ITEM_NAME'] == 'Median'].copy()
ashe_median['OBS_VALUE'] = pd.to_numeric(ashe_median['OBS_VALUE'], errors='coerce')

# Get latest year with full data
latest_year = ashe_median['DATE_NAME'].max()
ashe_latest = ashe_median[ashe_median['DATE_NAME'] == latest_year].copy()

# Group by region (take mean across sex categories if duplicates)
ashe_by_region = ashe_latest.groupby('GEOGRAPHY_NAME')['OBS_VALUE'].mean().reset_index()
ashe_by_region.columns = ['Region', 'median_weekly_pay']

print(f"  Latest year: {latest_year}")
print(f"  Regions available: {len(ashe_by_region)}")
print(f"\n  Regional Median Weekly Pay ({latest_year}):\n{ashe_by_region.sort_values('median_weekly_pay', ascending=False)}")

# ============================================================================
# CALCULATE REGIONAL CPI PROXY
# ============================================================================
print("\nCalculating Regional CPI Proxy...")

# Get national rental price average (base for comparison)
national_rental_price = rental_latest[
    rental_latest['Geography'].isin(['United Kingdom', 'England', 'Great Britain'])
]['v4_1'].mean()

print(f"  National rental price index (base): {national_rental_price:.2f}")

# Get national CPIH mean
national_cpih = cpih_by_time['cpih_mean'].mean()
print(f"  National CPIH mean: {national_cpih:.2f}")

# Calculate regional proxy
result = rental_latest[['Geography', 'Time', 'v4_1']].copy()
result.columns = ['Region', 'Time', 'Regional_Rental_Price_Index']

# Add national CPIH
result['National_CPIH_Index'] = national_cpih

# Calculate proxy: (national_cpih * regional_rental) / national_rental
result['Regional_CPI_Proxy'] = (
    result['National_CPIH_Index'] * result['Regional_Rental_Price_Index'] / national_rental_price
)

# Merge with earnings data
result = result.merge(
    ashe_by_region,
    left_on='Region',
    right_on='Region',
    how='left'
)

# Calculate real wages (nominal pay / CPI proxy, normalized to 100)
result['Real_Wage_Index'] = (result['median_weekly_pay'] / result['Regional_CPI_Proxy'] * 100)

print(f"\n  Result: {len(result)} regions")

# ============================================================================
# OUTPUT
# ============================================================================

output_path = data_dir / "regional_cpi_proxy.csv"
result.to_csv(output_path, index=False)
print(f"\nSaved to: {output_path}")

# Summary statistics
print("\n" + "="*70)
print("REGIONAL COST-OF-LIVING PROXY (ranked by real wage index)")
print("="*70)
summary = result[['Region', 'Regional_CPI_Proxy', 'median_weekly_pay', 'Real_Wage_Index']].copy()
summary = summary.sort_values('Real_Wage_Index', ascending=False)
summary.columns = ['Region', 'CPI Proxy', 'Weekly Pay (£)', 'Real Wage Index']

# Format for readability
pd.options.display.float_format = '{:.2f}'.format
print(summary.to_string(index=False))

print("\n" + "="*70)
print("INTERPRETATION:")
print("="*70)
print("• CPI Proxy: Regional cost-of-living estimate (higher = more expensive)")
print("• Weekly Pay: Median gross weekly earnings")
print("• Real Wage Index: Purchasing power adjusted for regional inflation")
print("  (higher = better real purchasing power after accounting for cost-of-living)")
print("="*70)
