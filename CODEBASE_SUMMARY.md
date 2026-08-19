# SCAR Codebase: Comprehensive Summary

## Project Overview

**SCAR** (UK Earnings & Cost-of-Living Data) is a data aggregation and analysis project that pulls publicly available UK earnings and cost-of-living data from multiple government sources (ONS, Nomis, DWP, Land Registry, etc.) and provides it in a standardized, analysis-ready format.

**Key Principle:** Everything in this project requires NO access requests or institutional affiliation. All data comes from public APIs or free manual downloads (Open Government Licence).

---

## 1. Data Available

### Current Datasets in `/data/` folder (with row counts):

| File | Rows | Type | Content |
|------|------|------|---------|
| `nomis_ashe_workplace.csv` | 696 | Aggregate | ASHE median weekly pay by workplace (where people work) - all years 1997-2025 |
| `nomis_ashe_resident.csv` | 576 | Aggregate | ASHE median weekly pay by residence (where people live) - all years 2002-2025 |
| `ons_cpih01.csv` | 20,000 | Time Series | Consumer Price Index including Housing (inflation index by product category) |
| `ons_index_private_housing_rental_prices.csv` | 6,870 | Time Series | Private rental prices index by region and year-on-year change |
| `ethnic.csv` | - | Census | Ethnic group distribution (20 categories) by local authority |
| `religion.csv` | - | Census | Religious affiliation (10 categories) by local authority |
| `sex.csv` | - | Census | Population split by sex by local authority |
| `location_mapping.csv` | - | Lookup | Maps local areas to high-level regions (e.g., County Durham → North East) |
| `religion_with_region.csv` | - | Derived | Religion + region lookup (merged from religion.csv + location_mapping.csv) |
| `religion_per_region.csv` | - | Derived | Aggregated religion data by region |
| `nomis_ashe_resident_dates.csv` | 24 | Lookup | Time periods available in resident dataset (2002-2025) |
| `nomis_ashe_workplace_dates.csv` | 29 | Lookup | Time periods available in workplace dataset (1997-2025) |
| `_manifest.csv` | 7 | Metadata | Source tracking, row counts, and fetch timestamps |

---

## 2. Data Features/Variables by Dataset

### A. NOMIS ASHE Earnings Data

**Workplace & Resident datasets contain:**

```
Variables: 45+ columns including:
  - DATE, DATE_NAME, DATE_CODE (Year, e.g., 2002)
  - GEOGRAPHY_NAME, GEOGRAPHY_CODE (Region/Local Authority name and code)
  - GEOGRAPHY_TYPE (e.g., "regions", "TYPE480" = local authorities)
  - SEX, SEX_NAME (1=Full Time Workers, 8=All workers, etc.)
  - PAY, PAY_NAME (1=Weekly pay - gross, 2=Weekly pay - net, etc.)
  - ITEM, ITEM_NAME (1=Mean, 2=Median, 3=Percentiles, etc.)
  - MEASURES, MEASURES_NAME (20100=Value, 20701=Confidence interval)
  - OBS_VALUE (The actual numerical value - median weekly pay, typically)
  - OBS_STATUS (Data quality flags: "A"=Normal, etc.)
  - OBS_CONF, OBS_CONF_NAME (Confidence intervals)
```

**Key Insight:** Contains both WORKPLACE (where people work) and RESIDENT (where people live) dimensions - useful for identifying commuter patterns and regional income disparities.

### B. ONS CPIH01 (Consumer Price Index)

```
Variables:
  - Time (e.g., "Jan-26")
  - Geography (e.g., "United Kingdom")
  - cpih1dim1aggid (Category code, e.g., "CP055")
  - Aggregate (Product category name)
  - v4_0, mmm-yy, uk-only (Index values and metadata)
```

**Coverage:** 20,000 rows covering ~500+ product categories from Jan 2023 onwards

### C. ONS Private Rental Price Index

```
Variables:
  - Time (e.g., "Jul-17")
  - administrative-geography (Region code, e.g., "E92000001")
  - Geography (Region name, e.g., "England")
  - index-and-year-change (Index or Year-on-year % change)
  - v4_1 (Numerical value)
```

**Coverage:** Monthly data from 2014 onwards across UK regions and nations

### D. Census Data (Ethnic, Religion, Sex)

**Each dataset structure:**
```
Columns:
  - Lower tier local authorities Code (e.g., "E06000001")
  - Lower tier local authorities (Name, e.g., "Hartlepool")
  - [Category] Code (numeric code for category)
  - [Category] (Category name, e.g., "Christian", "Female")
  - Observation (Count of people in that category)
```

**Coverage:** 
- **Ethnic:** 20 detailed ethnic group categories
- **Religion:** 10 religious categories + "Does not apply" code
- **Sex:** Male/Female binary split

### E. Location Mapping Lookup

```
Columns:
  - Local area (e.g., "County Durham")
  - High-level region (e.g., "North East")
```

**Purpose:** Links local authorities to broader regional groupings for aggregation

---

## 3. Python Scripts Functionality

### A. `fetch_data.py` (Data Collection Pipeline)

**Purpose:** Pulls data from 6 public data sources via APIs and saves to CSV

**Sources Fetched:**

1. **ONS API** (no key required)
   - Pulls: ONS catalogue + CPIH inflation + private rental price index
   - Functions: `fetch_ons_catalogue()`, `fetch_ons_dataset()`
   
2. **Nomis** (optional free key for higher row caps)
   - Pulls: ASHE earnings by workplace + residence, all available years
   - Handles year-by-year batching (Nomis has row limits: 25k guest/100k with key)
   - Functions: `fetch_nomis_all_years()`, `fetch_nomis_dates()`
   
3. **DWP Stat-Xplore** (optional free key)
   - Pulls: Dataset schema index for benefits and pensioner income
   
4. **Adzuna** (free instant key)
   - Pulls: Job adverts with salary, location, lat/lon, employer
   - ⚠️ Note: Includes predicted salaries (flag: `salary_is_predicted`)
   
5. **Reed** (free instant key)
   - Pulls: Job adverts with salary range and location
   
6. **HM Land Registry** (no key)
   - Pulls: All residential sales in England & Wales (price, date, postcode)

**Output:**
- One CSV per source in `data/` folder
- `data/_manifest.csv` records row counts and fetch timestamps
- Includes dimension code lookups for Nomis (e.g., `nomis_ashe_resident_dates.csv`)

**Usage Examples:**
```bash
python fetch_data.py --list              # Show all sources and key requirements
python fetch_data.py                     # Fetch everything (no keys needed)
python fetch_data.py --only ons nomis    # Only specific sources
python fetch_data.py --rows 5000         # Increase sample cap per source
```

### B. `merge_locations.py` (Data Enrichment)

**Purpose:** Joins religion data with regional geography lookup

**Process:**
1. Reads `data/religion.csv` (religion counts by local authority)
2. Reads `LA_region_lookup.xlsx` (maps local authorities to regions)
3. Cleans and renames columns for matching
4. Merges on local authority code
5. Identifies any unmatched records
6. Outputs: `data/religion_with_region.csv`

**Result:** Religion data enhanced with regional grouping for regional analysis

**Note:** Could be extended to merge other datasets (ethnic, sex) with region

### C. `statxplore.py` (DWP Stat-Xplore Client)

**Purpose:** Provides a Python client for querying the DWP Stat-Xplore REST API

**Key Classes/Functions:**
- `StatXploreClient` class with methods:
  - `get(path)` - Generic API requests
  - `get_schema(schema_id)` - Fetch dataset schema
  - `query_table(database, dimensions, measures)` - POST table queries

**Functionality:**
- Lists available datasets
- Retrieves schema information (fields, measures, dimensions)
- Constructs and executes `/table` queries
- Saves outputs as JSON files in `data/statxplore/`

**Note:** Only retrieves schema index; building actual table queries requires dataset-specific IDs

---

## 4. Libraries & Dependencies

### Installed Packages (Python 3.12.10 venv):

**Core Data/Scientific:**
- `pandas==3.0.5` - Data manipulation and analysis
- `numpy==2.5.2` - Numerical computing
- `requests==2.34.2` - HTTP requests (API calls)

**Jupyter/Interactive:**
- `jupyter_client==8.9.1` - Jupyter kernel communication
- `ipykernel==7.3.0` - IPython kernel for Jupyter
- `ipython==9.16.1` - Interactive Python shell

**Development/Utilities:**
- `matplotlib-inline==0.2.2` - Inline matplotlib in notebooks
- `python-dateutil==2.9.0.post0` - Date utilities
- `certifi==2026.7.22` - SSL certificates
- `urllib3==2.7.0` - HTTP library (used by requests)

**Total:** 33 packages installed

---

## 5. Jupyter Notebook: `catalogue.ipynb`

### Purpose
Demonstrates data cleaning and comparison of workplace vs resident earnings

### Cells:

**Cell 1: `clean_pay_data()` Function + Comparison**
- Function: Extracts median pay from raw Nomis data
- Filters: Keeps only actual pay values (MEASURES==20100), removes confidence intervals
- Conversion: Weekly pay → Annual pay (×52)
- Outputs: 
  - `Pay_Workplace` vs `Pay_Resident` by region
  - `Pay_Difference` and `Pay_Difference_Percent`
  - Saves: `pay_workplace_vs_resident.csv`

**Cell 2: Single Workplace Pay Analysis**
- Cleans `nomis_ashe_workplace.csv`
- Converts weekly to annual pay
- Displays unique regions count
- Saves: `cleaned_pay_data_working_there.csv`

**Cell 3:** Empty (placeholder)

### Insights Demonstrated
- How to extract actionable data from dimension-coded government data
- Workplace/resident distinction reveals commuter patterns
- Regional pay disparities can be quantified

---

## 6. Key Data Characteristics

### Temporal Coverage
- **ASHE Workplace:** 1997-2025 (29 years)
- **ASHE Resident:** 2002-2025 (24 years)
- **CPIH:** From Jan 2023 onwards
- **Rental Prices:** From 2014 onwards
- **Census:** 2021 (latest snapshot)

### Geographic Levels
- **Standard Regions:** 9 (North East, North West, East Midlands, etc.)
- **Local Authorities:** ~380 (unitary authorities, districts, boroughs)
- **Country Level:** UK (all datasets)

### Data Quality
- All data is **Open Government Licence v3.0** (free, citable reuse)
- Confidence intervals included with ASHE data
- Missing values handled with appropriate codes (e.g., -8 = "Does not apply")

---

## 7. ML Model Opportunities

### Supervised Learning Models:

1. **Regression Models**
   - Predict weekly/annual pay based on:
     - Region + year
     - Census demographics (ethnicity, religion, sex distribution)
     - Inflation & housing costs as features
   - Output: Median earnings forecast

2. **Time Series Forecasting**
   - Predict future inflation (CPIH)
   - Forecast rental price indices
   - Predict regional earnings trends
   - Methods: ARIMA, Prophet, LSTM

3. **Classification Models**
   - Predict high/low earnings regions
   - Classify local authorities by wage levels
   - Earnings impact classification based on demographics

### Unsupervised Learning:

4. **Clustering**
   - Cluster regions/local authorities by earnings profile
   - Identify commuter patterns (workplace vs resident divergence)
   - Group areas by demographic similarity

5. **Anomaly Detection**
   - Detect unusual wage/price spikes
   - Identify outlier regions

### Correlation & Feature Engineering:

6. **Multivariate Analysis**
   - Correlation between:
     - Regional demographics ↔ earnings levels
     - Inflation ↔ rental prices
     - Commuting intensity (workplace-resident gap) ↔ regional characteristics
   - Cross-tab analysis: earnings by ethnicity, religion, sex

### Predictive Models:

7. **Earnings Gap Analysis**
   - Predict workplace/resident earnings ratio (commuter intensity)
   - Identify which regions are net importers/exporters of labor

---

## 8. Current State & Limitations

### What You Have:
✅ Aggregated earnings by region/local authority (median pay)  
✅ Inflation and housing cost indices  
✅ Demographic distribution (age, ethnicity, religion, sex)  
✅ Long time series (29 years of workplace earnings)  
✅ Workplace vs residence split (commuter analysis)  

### What You DON'T Have (by design):
❌ **Person-level income data** (requires UK Data Service access request)  
❌ **Individual earnings records** (only aggregates)  
❌ **Occupation detail** (only broad sectors in Nomis)  
❌ **Employer data** (only job adverts, not census)  
❌ **Time-series demographics** (only 2021 census snapshot)  

### Data Ready for ML:
- Already normalized and cleaned (earnings in £/week or £/year)
- Dimension codes provided with lookups
- Confidence intervals included
- No person-level privacy concerns
- Suitable for publication of all analysis

---

## 9. Project Structure Reference

```
SCAR/
├── fetch_data.py           # API data collection pipeline
├── merge_locations.py      # Data enrichment/joining
├── statxplore.py          # DWP Stat-Xplore client
├── catalogue.ipynb        # Example: earnings comparison analysis
├── gp.ps1                 # PowerShell helper script
├── requirements.txt       # Python dependencies
├── README.md              # Full documentation (sources, caveats)
├── CODEBASE_SUMMARY.md   # This file
└── data/                  # Output folder (CSVs + lookup tables)
    ├── _manifest.csv
    ├── nomis_ashe_*.csv
    ├── ons_*.csv
    ├── ethnic.csv
    ├── religion*.csv
    ├── sex.csv
    ├── location_mapping.csv
    └── *_dates.csv        # Time period lookups
```

---

## 10. Next Steps for ML Projects

1. **Data Expansion**
   - Run `python fetch_data.py` to get job advert data (Adzuna, Reed) for salary/location patterns
   - Download manual datasets from README Part 2 (ASHE detail tables, housing costs)

2. **Feature Engineering**
   - Aggregate demographics by region
   - Calculate earnings volatility (year-over-year change)
   - Create region-pair distance metrics

3. **Model Development**
   - Start with time series models on earnings/inflation
   - Build regional clustering on earnings + demographics
   - Predict earnings based on census data + inflation

4. **Analysis**
   - Investigate commuter patterns (workplace/resident gap)
   - Regional earnings disparities
   - Inflation impact on regional wages

---

**Project Owner:** github.com/AmirH32  
**Last Updated:** 2026-02-18 (based on data timestamps)  
**All data:** Open Government Licence v3.0
