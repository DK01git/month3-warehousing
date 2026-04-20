# Retail Lakehouse & Data Warehouse
**Stack:** Apache Spark · Delta Lake · PostgreSQL · MinIO · Airflow · Apache Superset · Docker

---

## Overview

End-to-end open-source lakehouse and data warehouse implementation for a retail dataset.
Implements medallion architecture (bronze/silver/gold) using Delta Lake on MinIO,
loads a star schema into PostgreSQL, and serves dashboards via Apache Superset.

```
MinIO bronze (raw CSV/Parquet)
    → MinIO silver (Delta Lake — cleaned)
    → MinIO gold   (Delta Lake — aggregated)
    → PostgreSQL   (star schema — serving)
    → Superset     (dashboards + SQL Lab)
```

**Data profile:**
- 500,000 transaction rows (2024 full year)
- 10,000 customers, 1,000 products, 200 stores
- Partitioned parquet files by year/month in bronze

---

## Repository Structure

```
month3/
├── README.md
├── docker-compose.yml                            ← Spark + Superset services
├── generate_data.py                              ← Synthetic data generation + MinIO upload
├── diluksha-perera-month3-warehouse-ddl.sql      ← PostgreSQL star schema DDL
├── notebooks/
│   ├── bronze_to_silver.ipynb                   ← PySpark: raw files → Delta tables
│   ├── silver_to_gold.ipynb                     ← PySpark: clean → aggregated Delta tables
│   └── gold_to_postgres.ipynb                   ← PySpark JDBC: Delta → PostgreSQL
└── docs/
    ├── diluksha-perera-month3-environment-config.md
    ├── diluksha-perera-month3-medallion-architecture.md
    └── diluksha-perera-month3-performance-report.md
```

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Docker Desktop | Latest | Runs all services |
| Python | 3.10+ | Data generation script |
| pip packages | pandas, pyarrow, boto3 | Data generation dependencies |

**Important:** This stack requires Month 1 containers to be running first.
Month 3 attaches to the `month1_default` Docker network.

---

## Quick Start

### Step 1 — Start Month 1 stack first

```bash
cd C:\de-training\month1
docker-compose up -d
```

### Step 2 — Start Month 3 stack

```bash
cd C:\de-training\month3
docker-compose up -d
```

### Step 3 — Create PostgreSQL database

Connect to `localhost:5432` as `retailco/retailco` in DBeaver and run:

```sql
CREATE USER dataeng WITH PASSWORD 'dataeng123';
CREATE DATABASE retaildw OWNER dataeng;
GRANT ALL PRIVILEGES ON DATABASE retaildw TO dataeng;
REVOKE ALL ON DATABASE retaildw FROM PUBLIC;
```

### Step 4 — Create star schema DDL

Connect to `retaildw` as `dataeng/dataeng123` in DBeaver and run:

```
diluksha-perera-month3-warehouse-ddl.sql
```

### Step 5 — Generate and upload synthetic data

```bash
pip install pandas pyarrow boto3
python generate_data.py
```

### Step 6 — Install PostgreSQL JDBC JAR in Spark container

```bash
docker exec month3-spark-1 bash -c "curl -L -o /tmp/postgresql-42.7.3.jar https://jdbc.postgresql.org/download/postgresql-42.7.3.jar"
docker exec -u root month3-spark-1 bash -c "cp /tmp/postgresql-42.7.3.jar /usr/local/spark-3.5.0-bin-hadoop3/jars/"
```

### Step 7 — Run notebooks in order

Open http://localhost:8888 and run in this exact order:

1. `bronze_to_silver.ipynb` — reads raw files from MinIO, writes Delta tables to silver bucket
2. `silver_to_gold.ipynb` — aggregates silver Delta tables, writes gold Delta tables with surrogate keys
3. `gold_to_postgres.ipynb` — truncates star schema tables then loads via JDBC

**Critical:** In `gold_to_postgres.ipynb`, always run the truncate cell before the load cells. Rerunning load cells without truncating first causes duplicate rows.

### Step 8 — Initialize Superset

```bash
cmd /c "docker exec -it month3-superset-1 superset fab create-admin --username admin --firstname Admin --lastname User --email admin@superset.com --password admin"
cmd /c "docker exec -it month3-superset-1 superset db upgrade"
cmd /c "docker exec -it month3-superset-1 superset init"
```

Install psycopg2 driver:

```bash
docker exec -u root month3-superset-1 /app/.venv/bin/python3 -m ensurepip --upgrade
docker exec -u root month3-superset-1 /app/.venv/bin/python3 -m pip install psycopg2-binary
```

Open http://localhost:8088 and connect via SQLAlchemy URI:

```
postgresql://dataeng:dataeng123@month1-postgres-retail-1:5432/retaildw
```

---

## Medallion Architecture

```
SOURCE FILES (CSV + Parquet)
        │
        ▼
┌─────────────────────────────────┐
│  BRONZE BUCKET (MinIO)          │
│  s3a://bronze/raw/              │  Raw files, untouched
└─────────────────────────────────┘
        │  PySpark Notebook 1
        ▼
┌─────────────────────────────────┐
│  SILVER BUCKET (MinIO)          │
│  s3a://silver/delta/            │  Delta tables, cleaned
└─────────────────────────────────┘
        │  PySpark Notebook 2
        ▼
┌─────────────────────────────────┐
│  GOLD BUCKET (MinIO)            │
│  s3a://gold/delta/              │  Delta tables, aggregated
└─────────────────────────────────┘
        │  PySpark Notebook 3 (JDBC)
        ▼
┌─────────────────────────────────┐
│  POSTGRESQL retaildw            │  Star schema serving layer
│  warehouse.dim_date             │
│  warehouse.dim_customer (SCD2)  │
│  warehouse.dim_product          │
│  warehouse.dim_store            │
│  warehouse.fact_sales           │
└─────────────────────────────────┘
        │  SQLAlchemy
        ▼
┌─────────────────────────────────┐
│  APACHE SUPERSET                │  Dashboards + SQL Lab
└─────────────────────────────────┘
```

See `docs/diluksha-perera-month3-medallion-architecture.md` for full documentation.

---

## Known Issues and Resolutions

| Issue | Resolution |
|---|---|
| PyArrow writes nanosecond timestamps rejected by Spark | Cast to `datetime64[us]` before writing parquet in `generate_data.py` |
| PostgreSQL JDBC JAR not available via Maven | Manually download and copy to Spark jars directory |
| Spark `mode("overwrite")` blocked by FK constraints | Truncate via psycopg2 in correct dependency order first |
| Superset missing psycopg2 driver | Install into `/app/.venv` as root |
| PowerShell rejects `--` flags | Wrap commands in `cmd /c "..."` |

---

## Service Credentials

| Service | URL | Username | Password |
|---|---|---|---|
| Jupyter Notebook | http://localhost:8888 | token-based | run `docker exec month3-spark-1 jupyter notebook list` |
| Spark UI | http://localhost:4040 | — | — |
| MinIO Console | http://localhost:9001 | minioadmin | minioadmin |
| Superset | http://localhost:8088 | admin | admin |
| PostgreSQL retaildw | localhost:5432 | dataeng | dataeng123 |

---

## Documentation

| Document | Description |
|---|---|
| `docs/diluksha-perera-month3-environment-config.md` | Full environment setup, Docker architecture, known issues |
| `docs/diluksha-perera-month3-medallion-architecture.md` | Medallion layer definitions, star schema design, SCD2 |
| `docs/diluksha-perera-month3-performance-report.md` | EXPLAIN ANALYZE, index usage, Superset dashboard results |
