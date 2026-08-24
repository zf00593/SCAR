CREATE DATABASE IF NOT EXISTS scar_city
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE scar_city;

CREATE TABLE IF NOT EXISTS dim_city (
  city_key BIGINT NOT NULL AUTO_INCREMENT,
  city_name VARCHAR(128) NOT NULL,
  region_name VARCHAR(128) NULL,
  PRIMARY KEY (city_key),
  UNIQUE KEY uq_city_name (city_name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_city_geo (
  city_geo_key BIGINT NOT NULL AUTO_INCREMENT,
  city_key BIGINT NOT NULL,
  latitude DECIMAL(10, 7) NOT NULL,
  longitude DECIMAL(10, 7) NOT NULL,
  geocode_source VARCHAR(64) NULL,
  PRIMARY KEY (city_geo_key),
  UNIQUE KEY uq_city_geo_city (city_key),
  KEY ix_city_geo_lat_lon (latitude, longitude),
  CONSTRAINT fk_city_geo_city FOREIGN KEY (city_key) REFERENCES dim_city(city_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_year (
  year_key BIGINT NOT NULL AUTO_INCREMENT,
  year_num SMALLINT NOT NULL,
  PRIMARY KEY (year_key),
  UNIQUE KEY uq_year_num (year_num)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_measure (
  measure_key BIGINT NOT NULL AUTO_INCREMENT,
  measure_domain VARCHAR(32) NOT NULL,
  measure_code VARCHAR(32) NOT NULL,
  measure_name VARCHAR(128) NOT NULL,
  value_type VARCHAR(16) NOT NULL,
  PRIMARY KEY (measure_key),
  UNIQUE KEY uq_measure (measure_domain, measure_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_category (
  category_key BIGINT NOT NULL AUTO_INCREMENT,
  category_domain VARCHAR(32) NOT NULL,
  category_code VARCHAR(64) NOT NULL,
  category_name VARCHAR(128) NOT NULL,
  PRIMARY KEY (category_key),
  UNIQUE KEY uq_category (category_domain, category_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS raw_city_house_prices_latest (
  city_name VARCHAR(128),
  date_label VARCHAR(32),
  mapping_source VARCHAR(128),
  mean_price VARCHAR(64),
  median_price VARCHAR(64),
  sales_count VARCHAR(64)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS raw_city_cpiu_proxy_2022 (
  city_name VARCHAR(128),
  date_label VARCHAR(32),
  mean_price VARCHAR(64),
  sales_count VARCHAR(64),
  city_cpiu_proxy_2022 VARCHAR(64)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS raw_nomis_city_earnings (
  nomis_dataset VARCHAR(64),
  date_code VARCHAR(16),
  date_name VARCHAR(32),
  sex_code VARCHAR(16),
  sex_name VARCHAR(64),
  pay_code VARCHAR(16),
  pay_name VARCHAR(64),
  item_code VARCHAR(16),
  item_name VARCHAR(64),
  measures_code VARCHAR(16),
  measures_name VARCHAR(64),
  geography_name VARCHAR(128),
  obs_value VARCHAR(64),
  geography_code VARCHAR(256),
  geography_city_name VARCHAR(128),
  work_residence_basis VARCHAR(16)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS raw_city_demographics (
  city_name VARCHAR(128),
  region_name VARCHAR(128),
  category_code VARCHAR(64),
  category_name VARCHAR(128),
  observation_value VARCHAR(64),
  demographic_domain VARCHAR(32)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_city_house_prices (
  fact_city_house_prices_key BIGINT NOT NULL AUTO_INCREMENT,
  city_key BIGINT NOT NULL,
  year_key BIGINT NOT NULL,
  mean_price DECIMAL(18,4) NULL,
  median_price DECIMAL(18,4) NULL,
  sales_count INT NULL,
  mapping_source VARCHAR(128) NULL,
  PRIMARY KEY (fact_city_house_prices_key),
  UNIQUE KEY uq_house_price_city_year (city_key, year_key),
  KEY ix_house_prices_city_year (city_key, year_key),
  CONSTRAINT fk_chp_city FOREIGN KEY (city_key) REFERENCES dim_city(city_key),
  CONSTRAINT fk_chp_year FOREIGN KEY (year_key) REFERENCES dim_year(year_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_city_cpiu_proxy (
  fact_city_cpiu_proxy_key BIGINT NOT NULL AUTO_INCREMENT,
  city_key BIGINT NOT NULL,
  year_key BIGINT NOT NULL,
  mean_price DECIMAL(18,4) NULL,
  sales_count INT NULL,
  city_cpiu_proxy_2022 DECIMAL(12,6) NULL,
  PRIMARY KEY (fact_city_cpiu_proxy_key),
  UNIQUE KEY uq_cpiu_city_year (city_key, year_key),
  KEY ix_cpiu_city_year (city_key, year_key),
  CONSTRAINT fk_cpiu_city FOREIGN KEY (city_key) REFERENCES dim_city(city_key),
  CONSTRAINT fk_cpiu_year FOREIGN KEY (year_key) REFERENCES dim_year(year_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_cpiu_reference (
  fact_cpiu_reference_key BIGINT NOT NULL AUTO_INCREMENT,
  year_key BIGINT NOT NULL,
  national_cpiu DECIMAL(12,6) NOT NULL,
  uk_weighted_mean_city_price DECIMAL(18,6) NOT NULL,
  PRIMARY KEY (fact_cpiu_reference_key),
  UNIQUE KEY uq_cpiu_reference_year (year_key),
  CONSTRAINT fk_cpiu_ref_year FOREIGN KEY (year_key) REFERENCES dim_year(year_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_city_earnings (
  fact_city_earnings_key BIGINT NOT NULL AUTO_INCREMENT,
  city_key BIGINT NOT NULL,
  year_key BIGINT NOT NULL,
  sex_category_key BIGINT NULL,
  pay_category_key BIGINT NULL,
  item_category_key BIGINT NULL,
  measure_key BIGINT NULL,
  work_residence_basis VARCHAR(16) NOT NULL,
  obs_value DECIMAL(14,4) NULL,
  PRIMARY KEY (fact_city_earnings_key),
  UNIQUE KEY uq_earnings_city_grain (
    city_key, year_key, sex_category_key, pay_category_key, item_category_key, measure_key, work_residence_basis
  ),
  KEY ix_earnings_city_year (city_key, year_key),
  CONSTRAINT fk_ce_city FOREIGN KEY (city_key) REFERENCES dim_city(city_key),
  CONSTRAINT fk_ce_year FOREIGN KEY (year_key) REFERENCES dim_year(year_key),
  CONSTRAINT fk_ce_sex FOREIGN KEY (sex_category_key) REFERENCES dim_category(category_key),
  CONSTRAINT fk_ce_pay FOREIGN KEY (pay_category_key) REFERENCES dim_category(category_key),
  CONSTRAINT fk_ce_item FOREIGN KEY (item_category_key) REFERENCES dim_category(category_key),
  CONSTRAINT fk_ce_measure FOREIGN KEY (measure_key) REFERENCES dim_measure(measure_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_city_demographic (
  fact_city_demographic_key BIGINT NOT NULL AUTO_INCREMENT,
  city_key BIGINT NOT NULL,
  category_key BIGINT NOT NULL,
  demographic_domain VARCHAR(32) NOT NULL,
  observation_value BIGINT NULL,
  PRIMARY KEY (fact_city_demographic_key),
  UNIQUE KEY uq_city_demo_grain (city_key, category_key, demographic_domain),
  KEY ix_city_demo_city_domain (city_key, demographic_domain),
  CONSTRAINT fk_cd_city FOREIGN KEY (city_key) REFERENCES dim_city(city_key),
  CONSTRAINT fk_cd_category FOREIGN KEY (category_key) REFERENCES dim_category(category_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_city_similarity_cluster (
  fact_city_similarity_cluster_key BIGINT NOT NULL AUTO_INCREMENT,
  city_key BIGINT NOT NULL,
  year_key BIGINT NULL,
  model_version VARCHAR(64) NOT NULL,
  k_value SMALLINT NOT NULL,
  cluster_id SMALLINT NOT NULL,
  pay_resident DECIMAL(14,4) NULL,
  pay_workplace DECIMAL(14,4) NULL,
  pay_diff_pct DECIMAL(10,4) NULL,
  house_price DECIMAL(18,4) NULL,
  pca_x DECIMAL(16,8) NULL,
  pca_y DECIMAL(16,8) NULL,
  PRIMARY KEY (fact_city_similarity_cluster_key),
  UNIQUE KEY uq_city_cluster_model (city_key, model_version),
  KEY ix_cluster_city (city_key),
  KEY ix_cluster_id (cluster_id),
  CONSTRAINT fk_fcs_city FOREIGN KEY (city_key) REFERENCES dim_city(city_key),
  CONSTRAINT fk_fcs_year FOREIGN KEY (year_key) REFERENCES dim_year(year_key)
) ENGINE=InnoDB;
