#!/usr/bin/env python3
"""
Load SCAR city CSV datasets into MySQL (scar_city) using SQLAlchemy ORM/Core upserts.

Usage:
  set SCAR_DB_URL=mysql+pymysql://user:pass@host:3306/scar_city?charset=utf8mb4
  python database/ingest_city_data_orm.py

Optional:
  python database/ingest_city_data_orm.py --base-dir C:/path/to/SCAR
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, DECIMAL, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class DimCity(Base):
    __tablename__ = "dim_city"
    city_key = Column(BigInteger, primary_key=True, autoincrement=True)
    city_name = Column(String(128), nullable=False)
    city_code = Column(String(64))
    region_name = Column(String(128))
    __table_args__ = (UniqueConstraint("city_name", name="uq_city_name"),)


class DimYear(Base):
    __tablename__ = "dim_year"
    year_key = Column(BigInteger, primary_key=True, autoincrement=True)
    year_num = Column(Integer, nullable=False, unique=True)


class DimMeasure(Base):
    __tablename__ = "dim_measure"
    measure_key = Column(BigInteger, primary_key=True, autoincrement=True)
    measure_domain = Column(String(32), nullable=False)
    measure_code = Column(String(32), nullable=False)
    measure_name = Column(String(128), nullable=False)
    value_type = Column(String(16), nullable=False)
    __table_args__ = (UniqueConstraint("measure_domain", "measure_code", name="uq_measure"),)


class DimCategory(Base):
    __tablename__ = "dim_category"
    category_key = Column(BigInteger, primary_key=True, autoincrement=True)
    category_domain = Column(String(32), nullable=False)
    category_code = Column(String(64), nullable=False)
    category_name = Column(String(128), nullable=False)
    __table_args__ = (UniqueConstraint("category_domain", "category_code", name="uq_category"),)


class FactCityHousePrices(Base):
    __tablename__ = "fact_city_house_prices"
    fact_city_house_prices_key = Column(BigInteger, primary_key=True, autoincrement=True)
    city_key = Column(BigInteger, nullable=False)
    year_key = Column(BigInteger, nullable=False)
    mean_price = Column(DECIMAL(18, 4))
    median_price = Column(DECIMAL(18, 4))
    sales_count = Column(Integer)
    source_ons_geography_count = Column(Integer)
    source_nomis_geography_count = Column(Integer)
    mapping_source = Column(String(128))
    proxy_flag = Column(Integer)
    proxy_source = Column(String(64))
    load_batch_ts_utc = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    __table_args__ = (UniqueConstraint("city_key", "year_key", name="uq_house_price_city_year"),)


class FactCityCpiuProxy(Base):
    __tablename__ = "fact_city_cpiu_proxy"
    fact_city_cpiu_proxy_key = Column(BigInteger, primary_key=True, autoincrement=True)
    city_key = Column(BigInteger, nullable=False)
    year_key = Column(BigInteger, nullable=False)
    mean_price = Column(DECIMAL(18, 4))
    sales_count = Column(Integer)
    national_cpiu_2022 = Column(DECIMAL(12, 6))
    uk_weighted_mean_city_price_2022 = Column(DECIMAL(18, 6))
    city_cpiu_proxy_2022 = Column(DECIMAL(12, 6))
    load_batch_ts_utc = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    __table_args__ = (UniqueConstraint("city_key", "year_key", name="uq_cpiu_city_year"),)


class FactCityEarnings(Base):
    __tablename__ = "fact_city_earnings"
    fact_city_earnings_key = Column(BigInteger, primary_key=True, autoincrement=True)
    city_key = Column(BigInteger, nullable=False)
    year_key = Column(BigInteger, nullable=False)
    sex_category_key = Column(BigInteger)
    pay_category_key = Column(BigInteger)
    item_category_key = Column(BigInteger)
    measure_key = Column(BigInteger)
    work_residence_basis = Column(String(16), nullable=False)
    obs_value = Column(DECIMAL(14, 4))
    proxy_flag = Column(Integer)
    proxy_source = Column(String(64))
    source_geography_count = Column(Integer)
    geography_code_raw = Column(String(256))
    load_batch_ts_utc = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    __table_args__ = (
        UniqueConstraint(
            "city_key",
            "year_key",
            "sex_category_key",
            "pay_category_key",
            "item_category_key",
            "measure_key",
            "work_residence_basis",
            name="uq_earnings_city_grain",
        ),
    )


class FactCityDemographic(Base):
    __tablename__ = "fact_city_demographic"
    fact_city_demographic_key = Column(BigInteger, primary_key=True, autoincrement=True)
    city_key = Column(BigInteger, nullable=False)
    category_key = Column(BigInteger, nullable=False)
    demographic_domain = Column(String(32), nullable=False)
    observation_value = Column(BigInteger)
    proxy_flag = Column(Integer)
    proxy_source = Column(String(64))
    source_area_count = Column(Integer)
    source_areas = Column(String(512))
    load_batch_ts_utc = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    __table_args__ = (UniqueConstraint("city_key", "category_key", "demographic_domain", name="uq_city_demo_grain"),)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    return int(float(s))


def to_year(value: str | None) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None

    try:
        return int(float(s))
    except ValueError:
        # Handles values like 2022-03-01 by extracting a leading 4-digit year.
        match = re.match(r"^(\d{4})", s)
        if match:
            return int(match.group(1))
        return None


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    return float(s)


def to_bool_int(value: str | None) -> int | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s == "true":
        return 1
    if s == "false":
        return 0
    return None


def upsert_rows(session: Session, table: Any, rows: list[dict[str, Any]], unique_cols: list[str], update_cols: list[str]) -> None:
    if not rows:
        return
    stmt = insert(table).values(rows)
    update_map = {col: stmt.inserted[col] for col in update_cols}
    stmt = stmt.on_duplicate_key_update(**update_map)
    session.execute(stmt)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest SCAR city CSV files into MySQL via SQLAlchemy.")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("SCAR_DB_URL", "mysql+pymysql://root:n3u3da!@localhost:3306/scar_city?charset=utf8mb4"),
        help="SQLAlchemy MySQL URL. Can also be set via SCAR_DB_URL.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Base folder containing data/ and visualisations_data/.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    base_dir = Path(args.base_dir).resolve()

    paths = {
        "house_prices": base_dir / "data" / "city_house_prices_latest.csv",
        "resident": base_dir / "data" / "nomis_data" / "nomis_ashe_resident_cities.csv",
        "workplace": base_dir / "data" / "nomis_data" / "nomis_ashe_workplace_cities.csv",
        "sex": base_dir / "visualisations_data" / "demographic_data" / "sex_with_city.csv",
        "religion": base_dir / "visualisations_data" / "demographic_data" / "religion_with_city.csv",
        "ethnicity": base_dir / "visualisations_data" / "demographic_data" / "ethnicity_with_city.csv",
        "cpiu": base_dir / "visualisations_data" / "city_cpiu_proxy_2022.csv",
    }

    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required files:\n" + "\n".join(missing))

    engine = create_engine(args.db_url, future=True)

    hp_rows = read_csv(paths["house_prices"])
    cpiu_rows = read_csv(paths["cpiu"])
    resident_rows = read_csv(paths["resident"])
    workplace_rows = read_csv(paths["workplace"])
    sex_rows = read_csv(paths["sex"])
    religion_rows = read_csv(paths["religion"])
    ethnicity_rows = read_csv(paths["ethnicity"])

    with Session(engine) as session:
        # 1) Dimensions: city
        city_records: dict[str, dict[str, Any]] = {}

        for r in hp_rows:
            city_records.setdefault(r["City"], {"city_name": r["City"], "city_code": r.get("City_Code") or None, "region_name": None})
        for r in cpiu_rows:
            city_records.setdefault(r["City"], {"city_name": r["City"], "city_code": r.get("City_Code") or None, "region_name": None})
        for r in resident_rows + workplace_rows:
            city_records.setdefault(r["GEOGRAPHY_NAME"], {"city_name": r["GEOGRAPHY_NAME"], "city_code": r.get("GEOGRAPHY_CODE") or None, "region_name": None})
        for r in sex_rows + religion_rows + ethnicity_rows:
            existing = city_records.setdefault(r["City"], {"city_name": r["City"], "city_code": None, "region_name": None})
            if not existing.get("region_name"):
                existing["region_name"] = r.get("geography") or None

        upsert_rows(
            session,
            DimCity.__table__,
            list(city_records.values()),
            ["city_name"],
            ["city_code", "region_name"],
        )

        # 2) Dimensions: year
        years = set()
        for r in hp_rows:
            years.add(to_year(r.get("Date")))
        for r in cpiu_rows:
            years.add(to_year(r.get("Date")))
        for r in resident_rows + workplace_rows:
            years.add(to_year(r.get("DATE")))
        year_rows = [{"year_num": y} for y in sorted(y for y in years if y is not None)]
        upsert_rows(session, DimYear.__table__, year_rows, ["year_num"], ["year_num"])

        # 3) Dimensions: measure and category
        measure_rows = [
            {"measure_domain": "nomis", "measure_code": "20100", "measure_name": "Value", "value_type": "numeric"},
            {"measure_domain": "nomis", "measure_code": "20701", "measure_name": "Confidence", "value_type": "numeric"},
        ]
        upsert_rows(session, DimMeasure.__table__, measure_rows, ["measure_domain", "measure_code"], ["measure_name", "value_type"])

        category_rows: dict[tuple[str, str], dict[str, str]] = {}
        for r in resident_rows + workplace_rows:
            category_rows[("sex", r["SEX"])] = {
                "category_domain": "sex",
                "category_code": r["SEX"],
                "category_name": r["SEX_NAME"],
            }
            category_rows[("pay", r["PAY"])] = {
                "category_domain": "pay",
                "category_code": r["PAY"],
                "category_name": r["PAY_NAME"],
            }
            category_rows[("item", r["ITEM"])] = {
                "category_domain": "item",
                "category_code": r["ITEM"],
                "category_name": r["ITEM_NAME"],
            }

        for r in sex_rows:
            category_rows[("sex", r["Sex (2 categories) Code"])] = {
                "category_domain": "sex",
                "category_code": r["Sex (2 categories) Code"],
                "category_name": r["Sex (2 categories)"],
            }
        for r in religion_rows:
            category_rows[("religion", r["Religion (10 categories) Code"])] = {
                "category_domain": "religion",
                "category_code": r["Religion (10 categories) Code"],
                "category_name": r["Religion (10 categories)"],
            }
        for r in ethnicity_rows:
            category_rows[("ethnicity", r["Ethnic group (20 categories) Code"])] = {
                "category_domain": "ethnicity",
                "category_code": r["Ethnic group (20 categories) Code"],
                "category_name": r["Ethnic group (20 categories)"],
            }

        upsert_rows(
            session,
            DimCategory.__table__,
            list(category_rows.values()),
            ["category_domain", "category_code"],
            ["category_name"],
        )

        session.commit()

        # 4) Lookup maps for facts
        city_map = {name: key for key, name in session.execute(select(DimCity.city_key, DimCity.city_name)).all()}
        year_map = {year: key for key, year in session.execute(select(DimYear.year_key, DimYear.year_num)).all()}
        measure_map = {
            (domain, code): key
            for key, domain, code in session.execute(select(DimMeasure.measure_key, DimMeasure.measure_domain, DimMeasure.measure_code)).all()
        }
        category_map = {
            (domain, code): key
            for key, domain, code in session.execute(select(DimCategory.category_key, DimCategory.category_domain, DimCategory.category_code)).all()
        }

        # 5) Facts: city house prices
        house_fact_rows = []
        for r in hp_rows:
            city_key = city_map.get(r["City"])
            year_key = year_map.get(to_year(r.get("Date")))
            if not city_key or not year_key:
                continue
            house_fact_rows.append(
                {
                    "city_key": city_key,
                    "year_key": year_key,
                    "mean_price": to_float(r.get("Mean_Price")),
                    "median_price": to_float(r.get("Median_Price")),
                    "sales_count": to_int(r.get("Sales_Count")),
                    "source_ons_geography_count": to_int(r.get("Source_ONS_Geography_Count")),
                    "source_nomis_geography_count": to_int(r.get("Source_Nomis_Geography_Count")),
                    "mapping_source": r.get("Mapping_Source") or None,
                    "proxy_flag": to_bool_int(r.get("Proxy_Flag")),
                    "proxy_source": r.get("Proxy_Source") or None,
                }
            )

        upsert_rows(
            session,
            FactCityHousePrices.__table__,
            house_fact_rows,
            ["city_key", "year_key"],
            [
                "mean_price",
                "median_price",
                "sales_count",
                "source_ons_geography_count",
                "source_nomis_geography_count",
                "mapping_source",
                "proxy_flag",
                "proxy_source",
            ],
        )

        # 6) Facts: city cpiu proxy
        cpiu_fact_rows = []
        for r in cpiu_rows:
            city_key = city_map.get(r["City"])
            year_key = year_map.get(to_year(r.get("Date")))
            if not city_key or not year_key:
                continue
            cpiu_fact_rows.append(
                {
                    "city_key": city_key,
                    "year_key": year_key,
                    "mean_price": to_float(r.get("Mean_Price")),
                    "sales_count": to_int(r.get("Sales_Count")),
                    "national_cpiu_2022": to_float(r.get("National_CPIU_2022")),
                    "uk_weighted_mean_city_price_2022": to_float(r.get("UK_Weighted_Mean_City_Price_2022")),
                    "city_cpiu_proxy_2022": to_float(r.get("City_CPIU_Proxy_2022")),
                }
            )

        upsert_rows(
            session,
            FactCityCpiuProxy.__table__,
            cpiu_fact_rows,
            ["city_key", "year_key"],
            [
                "mean_price",
                "sales_count",
                "national_cpiu_2022",
                "uk_weighted_mean_city_price_2022",
                "city_cpiu_proxy_2022",
            ],
        )

        # 7) Facts: city earnings
        earnings_fact_rows = []

        def add_earnings(rows: list[dict[str, str]], basis: str) -> None:
            for r in rows:
                city_key = city_map.get(r["GEOGRAPHY_NAME"])
                year_key = year_map.get(to_year(r.get("DATE")))
                if not city_key or not year_key:
                    continue
                earnings_fact_rows.append(
                    {
                        "city_key": city_key,
                        "year_key": year_key,
                        "sex_category_key": category_map.get(("sex", r.get("SEX", ""))),
                        "pay_category_key": category_map.get(("pay", r.get("PAY", ""))),
                        "item_category_key": category_map.get(("item", r.get("ITEM", ""))),
                        "measure_key": measure_map.get(("nomis", r.get("MEASURES", ""))),
                        "work_residence_basis": basis,
                        "obs_value": to_float(r.get("OBS_VALUE")),
                        "proxy_flag": to_bool_int(r.get("Proxy_Flag")),
                        "proxy_source": r.get("Proxy_Source") or None,
                        "source_geography_count": to_int(r.get("Source_Geography_Count")),
                        "geography_code_raw": r.get("GEOGRAPHY_CODE") or None,
                    }
                )

        add_earnings(resident_rows, "resident")
        add_earnings(workplace_rows, "workplace")

        upsert_rows(
            session,
            FactCityEarnings.__table__,
            earnings_fact_rows,
            [
                "city_key",
                "year_key",
                "sex_category_key",
                "pay_category_key",
                "item_category_key",
                "measure_key",
                "work_residence_basis",
            ],
            ["obs_value", "proxy_flag", "proxy_source", "source_geography_count", "geography_code_raw"],
        )

        # 8) Facts: city demographics
        demo_fact_rows = []

        def add_demographic(rows: list[dict[str, str]], domain: str, code_col: str) -> None:
            for r in rows:
                city_key = city_map.get(r["City"])
                cat_key = category_map.get((domain, r.get(code_col, "")))
                if not city_key or not cat_key:
                    continue
                demo_fact_rows.append(
                    {
                        "city_key": city_key,
                        "category_key": cat_key,
                        "demographic_domain": domain,
                        "observation_value": to_int(r.get("Observation")),
                        "proxy_flag": to_bool_int(r.get("Proxy_Flag")),
                        "proxy_source": r.get("Proxy_Source") or None,
                        "source_area_count": to_int(r.get("Source_Area_Count")),
                        "source_areas": r.get("Source_Areas") or None,
                    }
                )

        add_demographic(sex_rows, "sex", "Sex (2 categories) Code")
        add_demographic(religion_rows, "religion", "Religion (10 categories) Code")
        add_demographic(ethnicity_rows, "ethnicity", "Ethnic group (20 categories) Code")

        upsert_rows(
            session,
            FactCityDemographic.__table__,
            demo_fact_rows,
            ["city_key", "category_key", "demographic_domain"],
            ["observation_value", "proxy_flag", "proxy_source", "source_area_count", "source_areas"],
        )

        session.commit()

        print("Ingestion complete.")
        print(f"dim_city: {len(city_map)}")
        print(f"dim_year: {len(year_map)}")
        print(f"fact_city_house_prices upserts: {len(house_fact_rows)}")
        print(f"fact_city_cpiu_proxy upserts: {len(cpiu_fact_rows)}")
        print(f"fact_city_earnings upserts: {len(earnings_fact_rows)}")
        print(f"fact_city_demographic upserts: {len(demo_fact_rows)}")


if __name__ == "__main__":
    main()
