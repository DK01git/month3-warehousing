# Month 3 Environment Configuration
**Author:** Diluksha Perera | Bistec Global Services
**Track:** Data Engineering Training — Month 3
**Date:** April 2026

---

## Stack Overview

| Component | Image | Port | Purpose |
|---|---|---|---|
| Apache Spark + Jupyter | jupyter/pyspark-notebook:latest | 8888, 4040 | PySpark notebooks, Delta Lake compute |
| Apache Superset | apache/superset:latest | 8088 | BI dashboards, SQL Lab |
| PostgreSQL (retail) | postgres:16-alpine | 5432 | Star schema warehouse (retaildw) |
| MinIO | minio/minio:latest | 9000, 9001 | S3-compatible object storage |
| Apache Airflow | apache/airflow:2.9.0-python3.11 | 8080 | Pipeline orchestration (Month 1) |

---

## Docker Compose Architecture

Month 3 uses a **two-stack strategy** to avoid disrupting the Month 1 environment:

- **Month 1 stack** (`C:\de-training\month1\docker-compose.yml`): Runs PostgreSQL, MinIO, Airflow
- **Month 3 stack** (`C:\de-training\month3\docker-compose.yml`): Runs Spark and Superset only

Both stacks share the `month1_default` Docker bridge network, enabling container-name resolution between all services.

### Month 3 docker-compose.yml

```yaml
version: "3.8"

services:

  spark:
    image: jupyter/pyspark-notebook:latest
    ports:
      - "8888:8888"
      - "4040:4040"
    environment:
      - PYSPARK_SUBMIT_ARGS=--packages io.delta:delta-spark_2.12:3.1.0,org.apache.hadoop:hadoop-aws:3.3.4 pyspark-shell
    volumes:
      - ./notebooks:/home/jovyan/work
    networks:
      - month1_default

  superset:
    image: apache/superset:latest
    ports:
      - "8088:8088"
    environment:
      - SUPERSET_SECRET_KEY=supersecretkey123
    volumes:
      - superset_home:/app/superset_home
    networks:
      - month1_default

networks:
  month1_default:
    external: true

volumes:
  superset_home:
```

**Key design decision:** `month1_default: external: true` instructs Docker Compose to attach to the existing Month 1 network rather than creating a new isolated network. Without this, Spark and Superset cannot resolve `minio:9000` or `month1-postgres-retail-1:5432` by container name.

---

## PostgreSQL Configuration

### Databases

| Database | Owner | Purpose |
|---|---|---|
| retailco | retailco | Month 1 retail pipeline data |
| retaildw | dataeng | Month 3 star schema warehouse |
| airflow | airflow | Airflow metadata backend |

### Month 3 Database Setup

```sql
CREATE USER dataeng WITH PASSWORD 'dataeng123';
CREATE DATABASE retaildw OWNER dataeng;
GRANT ALL PRIVILEGES ON DATABASE retaildw TO dataeng;
REVOKE ALL ON DATABASE retaildw FROM PUBLIC;
```

**Security note:** `PUBLIC` role access was explicitly revoked from `retaildw` to prevent cross-database access from `airflow` and `retailco` users.

---

## MinIO Bucket Structure

| Bucket | Purpose | Contents |
|---|---|---|
| bronze | Raw landing zone | `raw/customers/`, `raw/products/`, `raw/stores/`, `raw/transactions/` |
| silver | Cleaned Delta tables | `delta/customers/`, `delta/products/`, `delta/stores/`, `delta/transactions/` |
| gold | Aggregated Delta tables | `delta/fact_sales/`, `delta/customers/`, `delta/products/`, `delta/stores/` |
| raw-data | Month 1 source files | Month 1 pipeline inputs |
| archive-data | Month 1 archived files | Month 1 pipeline outputs |

### Bronze Bucket Raw Structure

```
s3a://bronze/
└── raw/
    ├── customers/
    │   └── customer_master_full.csv        (10,000 rows)
    ├── products/
    │   └── product_catalog_full.csv        (1,000 rows)
    ├── stores/
    │   └── store_locations.csv             (200 rows)
    └── transactions/
        └── year=2024/
            ├── month=01/transactions_202401.parquet
            ├── month=02/transactions_202402.parquet
            └── ... (12 monthly partitions, 500,000 rows total)
```

---

## PySpark S3A Configuration

```python
spark = SparkSession.builder \
    .appName("RetailLakehouse") \
    .config("spark.jars.packages",
            "io.delta:delta-spark_2.12:3.1.0,org.apache.hadoop:hadoop-aws:3.3.4") \
    .config("spark.sql.extensions",
            "io.delta.sql.DeltaSparkSessionExtension") \
    .config("spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
    .config("spark.hadoop.fs.s3a.endpoint",          "http://minio:9000") \
    .config("spark.hadoop.fs.s3a.access.key",        "minioadmin") \
    .config("spark.hadoop.fs.s3a.secret.key",        "minioadmin") \
    .config("spark.hadoop.fs.s3a.path.style.access", "true") \
    .config("spark.hadoop.fs.s3a.impl",
            "org.apache.hadoop.fs.s3a.S3AFileSystem") \
    .getOrCreate()
```

**path.style.access = true** is required for MinIO. MinIO uses path-style URLs (`http://minio:9000/bucket/key`) whereas AWS S3 uses virtual-hosted style (`http://bucket.s3.amazonaws.com/key`). Without this setting, Spark attempts to resolve `bronze.minio:9000` as a hostname, which fails.

---

## PostgreSQL JDBC Configuration (Spark to PostgreSQL)

```python
JDBC_URL = "jdbc:postgresql://month1-postgres-retail-1:5432/retaildw"
JDBC_PROPS = {
    "user":     "dataeng",
    "password": "dataeng123",
    "driver":   "org.postgresql.Driver"
}
```

**PostgreSQL JDBC JAR:** `postgresql-42.7.3.jar` was manually downloaded and placed in `/usr/local/spark-3.5.0-bin-hadoop3/jars/` inside the Spark container. The Maven download via `spark.jars.packages` was blocked by network restrictions in the container environment.

---

## Superset Configuration

**Database connection:** SQLAlchemy URI
```
postgresql://dataeng:dataeng123@month1-postgres-retail-1:5432/retaildw
```

**psycopg2-binary** was manually installed into Superset's venv:
```bash
docker exec -u root month3-superset-1 /app/.venv/bin/python3 -m pip install psycopg2-binary
```

---

## Service Verification Checklist

| Service | URL | Credentials | Status |
|---|---|---|---|
| Jupyter Notebook | http://localhost:8888 | Token-based | Verified |
| Spark UI | http://localhost:4040 | None | Verified |
| MinIO Console | http://localhost:9001 | minioadmin/minioadmin | Verified |
| Superset | http://localhost:8088 | admin/admin | Verified |
| PostgreSQL | localhost:5432 | dataeng/dataeng123 | Verified |
| Airflow | http://localhost:8080 | airflow/airflow | Verified (Month 1) |

---

## Known Issues and Resolutions

| Issue | Root Cause | Resolution |
|---|---|---|
| `INT64 (TIMESTAMP(NANOS))` parquet error | PyArrow writes nanosecond timestamps by default; Spark 3.5 rejects them | Cast `transaction_date` to `datetime64[us]` before writing parquet |
| `ClassNotFoundException: org.postgresql.Driver` | PostgreSQL JDBC JAR not downloaded via Maven due to network restrictions | Manually downloaded JAR and placed in Spark's jars directory |
| `Cannot drop table due to FK constraint` | Spark `mode("overwrite")` attempts DROP TABLE which PostgreSQL blocks due to FK dependencies | Truncate tables in correct dependency order (fact first, then dimensions) using psycopg2 before JDBC append load |
| `20,000 rows in dim_customer` | Cell re-ran without truncating first due to partial pipeline failure | Always run truncate cell before load cells; never rerun load cells independently |
| Superset `PostgresEngineSpec` error | psycopg2 not installed in Superset venv | Installed psycopg2-binary into `/app/.venv` as root |
