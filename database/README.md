# SCAR City Relational Database Plan

This folder now targets only the city-level files you specified.

## Files Used

- data/city_house_prices_latest.csv
- data/nomis_data/nomis_ashe_resident_cities.csv
- data/nomis_data/nomis_ashe_workplace_cities.csv
- visualisations_data/demographic_data/sex_with_city.csv
- visualisations_data/demographic_data/religion_with_city.csv
- visualisations_data/demographic_data/ethnicity_with_city.csv
- visualisations_data/city_cpiu_proxy_2022.csv
- visualisations_data/city_kmeans_clusters.csv (optional, generated)
- visualisations_data/city_lat_long_lookup.csv (optional, user-maintained)

Note: your request listed sex twice. This implementation assumes the intended third demographic file is ethnicity and includes ethnicity_with_city.csv.

## Output Files

- scar_schema.sql: City-focused schema (dimensions, facts, raw staging tables, indexes, constraints).
- scar_ingestion_validation.sql: `LOAD DATA` statements, upserts, and validation checks.
- ingest_city_data_orm.py: Python SQLAlchemy ORM ingestion/upsert script (recommended path).
- build_city_clusters.py: Generates K-means city similarity clusters for BI map coloring.

## Execution Order

1. Create schema and tables:

```sql
SOURCE database/scar_schema.sql;
```

2. Load and transform data:

```sql
SOURCE database/scar_ingestion_validation.sql;
```

## Recommended: ORM Ingestion (instead of SOURCE)

If MySQL `SOURCE`/`LOAD DATA` behavior is unreliable in your environment, use the ORM loader.

1. Install Python dependencies:

```powershell
c:/Users/Administrator/Documents/SCAR/.venv/Scripts/python.exe -m pip install sqlalchemy pymysql
```

2. Set your MySQL connection string:

```powershell
$env:SCAR_DB_URL = "mysql+pymysql://user:password@localhost:3306/scar_city?charset=utf8mb4"
```

3. Run ingestion from repo root:

```powershell
c:/Users/Administrator/Documents/SCAR/.venv/Scripts/python.exe database/ingest_city_data_orm.py
```

Optional explicit base path:

```powershell
c:/Users/Administrator/Documents/SCAR/.venv/Scripts/python.exe database/ingest_city_data_orm.py --base-dir c:/Users/Administrator/Documents/SCAR
```

4. Optional: Build city clusters before ingestion:

```powershell
c:/Users/Administrator/Documents/SCAR/.venv/Scripts/python.exe database/build_city_clusters.py --base-dir c:/Users/Administrator/Documents/SCAR --k 4
```

This writes `visualisations_data/city_kmeans_clusters.csv` and, if present, the ORM loader upserts it into `fact_city_similarity_cluster`.

5. Optional: add stable map coordinates for Power BI geocoding:

Create `visualisations_data/city_lat_long_lookup.csv` with columns:

- city_name
- latitude
- longitude
- geocode_source

If this file is present, rows are upserted into `dim_city_geo`.

## Schema Simplification Applied

- Removed all source count columns from fact tables.
- Removed `proxy_flag` and `proxy_source` columns from fact tables.
- Removed `geography_code_raw` and source area detail columns from fact tables.
- Removed `load_batch_ts_utc` columns from fact tables.
- Removed `city_code` from dimensional and staging city models.
- Moved repeated CPIU constants into `fact_cpiu_reference` (stored once per year).

## Power BI Mapping Approach

1. Connect to MySQL and import `dim_city` and `fact_city_similarity_cluster`.
2. Create relationship: `dim_city.city_key` -> `fact_city_similarity_cluster.city_key`.
3. In map visuals, use `dim_city.city_name` as Location and `fact_city_similarity_cluster.cluster_id` as Legend.
4. Add a slicer for `fact_city_similarity_cluster.model_version` so you can compare different model runs.
5. If geocoding ambiguity appears, add latitude/longitude columns in a separate city lookup and join by city.

## Data Structure Assessment

These city files are structured and fit MySQL relational modeling well.

- Tabular fields are stable with consistent headers.
- The main complexity is city harmonization and proxy metadata, not unstructured text.
- MySQL is suitable for this workload.

## PostgreSQL Consideration

You only need PostgreSQL for this dataset if you specifically want features like PostGIS-heavy geospatial pipelines or JSONB-centric modeling. Otherwise, this MySQL design is appropriate.

## Notes

- `LOAD DATA LOCAL INFILE` requires local-infile enabled and correct file permissions.
- Numeric casting in upserts handles empty strings with `NULLIF`.
- Validation queries at the end of ingestion check row counts and common data quality issues.
