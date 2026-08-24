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

Note: your request listed sex twice. This implementation assumes the intended third demographic file is ethnicity and includes ethnicity_with_city.csv.

## Output Files

- scar_schema.sql: City-focused schema (dimensions, facts, raw staging tables, indexes, constraints).
- scar_ingestion_validation.sql: `LOAD DATA` statements, upserts, and validation checks.
- ingest_city_data_orm.py: Python SQLAlchemy ORM ingestion/upsert script (recommended path).

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
