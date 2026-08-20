#!/usr/bin/env python3
"""
regional_cpi_timeseries.py
===========================

Extends regional CPI proxy calculation across all historical years (2002-2025).
Shows how cost-of-living and real wages have evolved by region.

Output: CSV with annual regional CPI proxy, wages, and real wage index
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================================
# LOAD DATA
# ============================================================================

data_dir = Path("data")

print("Loading data...")
cpih = pd.read_csv(data_dir / "ons_cpih01.csv")
rental = pd.read_csv(data_dir / "ons_index_private_housing_rental_prices.csv")
ashe_resident = pd.read_csv(data_dir / "nomis_ashe_resident.csv")

# ============================================================================
# PROCESS CPIH - Annual average index
# ============================================================================
print("Processing CPIH to annual averages...")

cpih_clean = cpih[cpih['Geography'] == 'United Kingdom'].copy()
cpih_clean['v4_0'] = pd.to_numeric(cpih_clean['v4_0'], errors='coerce')

# Extract year from Time (e.g., "Jan-26" -> 2026, "Apr-13" -> 2013)
cpih_clean['Year'] = cpih_clean['Time'].str.extract(r'-(\d{2})$')[0]
cpih_clean['Year'] = cpih_clean['Year'].astype(int)
cpih_clean['Year'] = cpih_clean['Year'].apply(lambda x: 2000 + x if x < 50 else 1900 + x)

# Annual average CPIH
cpih_annual = cpih_clean.groupby('Year')['v4_0'].mean().reset_index()
cpih_annual.columns = ['Year', 'National_CPIH_Index']

print(f"  {len(cpih_annual)} years: {cpih_annual['Year'].min()} to {cpih_annual['Year'].max()}")

# ============================================================================
# PROCESS RENTAL PRICES - Annual average by region
# ============================================================================
print("Processing Rental Price Index by region and year...")

rental_index = rental[rental['IndexAndYearChange'] == 'Index'].copy()
rental_index['v4_1'] = pd.to_numeric(rental_index['v4_1'], errors='coerce')

# Extract year from Time
rental_index['Year'] = rental_index['Time'].str.extract(r'-(\d{2})$')[0]
rental_index['Year'] = rental_index['Year'].astype(int)
rental_index['Year'] = rental_index['Year'].apply(lambda x: 2000 + x if x < 50 else 1900 + x)

# Filter to main regions (exclude aggregates like "England", "United Kingdom")
regions_to_include = [
    'North East', 'North West', 'Yorkshire and The Humber', 
    'East Midlands', 'West Midlands', 'East of England',
    'London', 'South East', 'South West', 'Wales', 'Scotland', 'Northern Ireland'
]

rental_regional = rental_index[rental_index['Geography'].isin(regions_to_include)].copy()

# Annual average by region
rental_annual = rental_regional.groupby(['Year', 'Geography'])['v4_1'].mean().reset_index()
rental_annual.columns = ['Year', 'Region', 'Regional_Rental_Price_Index']

print(f"  {len(rental_annual)} records across {rental_annual['Region'].nunique()} regions")
print(f"  Years: {rental_annual['Year'].min()} to {rental_annual['Year'].max()}")

# ============================================================================
# PROCESS ASHE - Annual median pay by region
# ============================================================================
print("Processing ASHE resident earnings by region and year...")

ashe_median = ashe_resident[ashe_resident['ITEM_NAME'] == 'Median'].copy()
ashe_median['OBS_VALUE'] = pd.to_numeric(ashe_median['OBS_VALUE'], errors='coerce')
ashe_median['Year'] = pd.to_numeric(ashe_median['DATE_NAME'], errors='coerce')

# Filter to main regions
ashe_regional = ashe_median[ashe_median['GEOGRAPHY_NAME'].isin(regions_to_include)].copy()

# Group by year and region (average across sex)
ashe_annual = ashe_regional.groupby(['Year', 'GEOGRAPHY_NAME'])['OBS_VALUE'].mean().reset_index()
ashe_annual.columns = ['Year', 'Region', 'Median_Weekly_Pay']

print(f"  {len(ashe_annual)} records across {ashe_annual['Region'].nunique()} regions")
print(f"  Years: {ashe_annual['Year'].min()} to {ashe_annual['Year'].max()}")

# ============================================================================
# MERGE DATA
# ============================================================================
print("Merging datasets...")
print(f"  Data availability:")
print(f"    - ASHE: {ashe_annual['Year'].min()} to {ashe_annual['Year'].max()}")
print(f"    - Rental prices: {rental_annual['Year'].min()} to {rental_annual['Year'].max()}")
print(f"    - CPIH: {cpih_annual['Year'].min()} to {cpih_annual['Year'].max()}")

# Start with ASHE (most complete time coverage)
result = ashe_annual.copy()

# Merge with rental prices
result = result.merge(rental_annual, on=['Year', 'Region'], how='left')

# Merge with national CPIH
result = result.merge(cpih_annual, on='Year', how='left')

# For years without CPIH data, use the nearest available year's index value
for region_group in result['Region'].unique():
    mask = result['Region'] == region_group
    cpih_values = result.loc[mask, 'National_CPIH_Index'].ffill().bfill()
    result.loc[mask, 'National_CPIH_Index'] = cpih_values

print(f"  Merged dataset: {len(result)} rows")
print(f"  Note: CPIH values before 2012 filled using 2012 baseline")

# ============================================================================
# CALCULATE REGIONAL CPI PROXY
# ============================================================================
print("Calculating regional CPI proxy over time...")

# Calculate national rental price average per year
national_rental_by_year = rental_annual.groupby('Year')['Regional_Rental_Price_Index'].mean().reset_index()
national_rental_by_year.columns = ['Year', 'National_Rental_Price_Index']

result = result.merge(national_rental_by_year, on='Year', how='left')

# For years without rental data, use nearest available year (forward/backward fill by region)
for region_group in result['Region'].unique():
    mask = result['Region'] == region_group
    # Forward fill then backward fill for rental prices
    rental_values = result.loc[mask, 'Regional_Rental_Price_Index'].ffill().bfill()
    national_rental_values = result.loc[mask, 'National_Rental_Price_Index'].ffill().bfill()
    result.loc[mask, 'Regional_Rental_Price_Index'] = rental_values
    result.loc[mask, 'National_Rental_Price_Index'] = national_rental_values

# Calculate regional CPI proxy
result['Regional_CPI_Proxy'] = (
    result['National_CPIH_Index'] * result['Regional_Rental_Price_Index'] / result['National_Rental_Price_Index']
)

# Calculate real wage index (nominal pay / CPI, normalized to year 2000 = 100)
# For each region: calculate cumulative purchasing power
result['Real_Wage_Index'] = result['Median_Weekly_Pay'] / result['Regional_CPI_Proxy'] * 100

# Sort for readability
result = result.sort_values(['Region', 'Year']).reset_index(drop=True)

# ============================================================================
# OUTPUT
# ============================================================================

output_path = data_dir / "regional_cpi_timeseries.csv"
result.to_csv(output_path, index=False)
print(f"\nSaved full time-series to: {output_path}")

# ============================================================================
# SUMMARY STATISTICS
# ============================================================================

print("\n" + "="*80)
print("TIME-SERIES SUMMARY: Regional Cost-of-Living Change (2002 → 2025)")
print("="*80)

# Compare first year vs latest year for each region
first_year_data = result[result.groupby('Region')['Year'].transform('min') == result['Year']].copy()
first_year_data = first_year_data[['Region', 'Year', 'Median_Weekly_Pay', 'Regional_CPI_Proxy', 'Real_Wage_Index']].copy()
first_year_data.columns = ['Region', 'Year_Start', 'Pay_Start', 'CPI_Start', 'Real_Wage_Start']

latest_year_data = result[result.groupby('Region')['Year'].transform('max') == result['Year']].copy()
latest_year_data = latest_year_data[['Region', 'Year', 'Median_Weekly_Pay', 'Regional_CPI_Proxy', 'Real_Wage_Index']].copy()
latest_year_data.columns = ['Region', 'Year_End', 'Pay_End', 'CPI_End', 'Real_Wage_End']

comparison = first_year_data.merge(latest_year_data, on='Region', how='inner')

# Drop rows with NaN values
comparison = comparison.dropna()

# Calculate changes
comparison['Pay_Change_%'] = ((comparison['Pay_End'] - comparison['Pay_Start']) / comparison['Pay_Start'] * 100).round(1)
comparison['CPI_Change_%'] = ((comparison['CPI_End'] - comparison['CPI_Start']) / comparison['CPI_Start'] * 100).round(1)
comparison['Real_Wage_Change_%'] = ((comparison['Real_Wage_End'] - comparison['Real_Wage_Start']) / comparison['Real_Wage_Start'] * 100).round(1)

# Show which regions have had wages outpace inflation
comparison['Wage_vs_Inflation'] = (comparison['Pay_Change_%'] - comparison['CPI_Change_%']).round(1)

print(comparison[['Region', 'Year_Start', 'Year_End', 'Pay_Change_%', 'CPI_Change_%', 'Wage_vs_Inflation']].to_string(index=False))

print("\n" + "="*80)
print("KEY INSIGHTS:")
print("="*80)

# Regions where wages outpaced inflation (positive value)
winners = comparison[comparison['Wage_vs_Inflation'] > 0].sort_values('Wage_vs_Inflation', ascending=False)
if len(winners) > 0:
    print("\n✓ Regions where WAGES outpaced INFLATION:")
    for _, row in winners.iterrows():
        print(f"  • {row['Region']}: +{row['Wage_vs_Inflation']:.1f}% real improvement")

# Regions where inflation outpaced wages (negative value)
losers = comparison[comparison['Wage_vs_Inflation'] < 0].sort_values('Wage_vs_Inflation')
if len(losers) > 0:
    print("\n✗ Regions where INFLATION outpaced WAGES:")
    for _, row in losers.iterrows():
        print(f"  • {row['Region']}: {row['Wage_vs_Inflation']:.1f}% real loss")

# Real wage changes
print("\n📊 Real Wage Index Change (accounting for inflation):")
real_change = comparison.sort_values('Real_Wage_Change_%', ascending=False)
for _, row in real_change.iterrows():
    symbol = "↑" if row['Real_Wage_Change_%'] > 0 else "↓"
    print(f"  {symbol} {row['Region']}: {row['Real_Wage_Change_%']:+.1f}%")

print("\n" + "="*80)

# ============================================================================
# SAVE SUMMARY
# ============================================================================

summary_path = data_dir / "regional_cpi_summary_2002_2025.csv"
comparison.to_csv(summary_path, index=False)
print(f"\nSummary saved to: {summary_path}")
