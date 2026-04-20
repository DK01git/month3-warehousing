# Month 3 Medallion Architecture Documentation


---

## Architecture Overview

This document describes the medallion architecture implemented for the Month 3 retail lakehouse and data warehouse. The architecture separates raw data ingestion, data cleaning, aggregation, and serving into distinct layers, each with a specific responsibility and storage location.

```
SOURCE FILES (CSV + Parquet)
        │
        ▼
┌─────────────────────────────────┐
│  BRONZE BUCKET (MinIO)          │
│  s3a://bronze/raw/              │  Raw files, untouched
│  s3a://bronze/staging/daily/    │  Daily incremental drops
└─────────────────────────────────┘
        │  PySpark reads raw files
        │  Validates and cleans
        ▼
┌─────────────────────────────────┐
│  SILVER BUCKET (MinIO)          │
│  s3a://silver/delta/            │  Delta tables
│    transactions/                │  Cleaned, deduplicated
│    customers/                   │  Standardized
│    products/                    │  Conformed
│    stores/                      │
└─────────────────────────────────┘
        │  PySpark aggregates
        │  Joins dimensions
        ▼
┌─────────────────────────────────┐
│  GOLD BUCKET (MinIO)            │
│  s3a://gold/delta/              │  Aggregated Delta tables
│    fact_sales/                  │  Business-ready
│    customers/                   │  With surrogate keys
│    products/                    │  With surrogate keys
│    stores/                      │  With surrogate keys
└─────────────────────────────────┘
        │  PySpark JDBC write
        ▼
┌─────────────────────────────────┐
│  POSTGRESQL (retaildw)          │  Star schema serving layer
│  warehouse.dim_date             │  Date dimension
│  warehouse.dim_customer (SCD2)  │  Customer dimension
│  warehouse.dim_product          │  Product dimension
│  warehouse.dim_store            │  Store dimension
│  warehouse.fact_sales           │  Fact table
└─────────────────────────────────┘
        │  SQLAlchemy connection
        ▼
┌─────────────────────────────────┐
│  APACHE SUPERSET                │  BI dashboards
│  Monthly Revenue by Category    │  Bar chart
│  Revenue by Category Mix        │  Pie chart
│  Revenue Trends by Category     │  Line chart
└─────────────────────────────────┘
```

---

## Layer Definitions

### Bronze Layer

**Location:** `s3a://bronze/`
**Format:** Original source files (CSV, Parquet)
**Load pattern:** Append only — raw files are never modified
**Retention:** Permanent

The bronze layer is the raw landing zone. Data arrives exactly as produced by the source system. No transformations are applied. The purpose is to preserve the original data for reprocessing, auditing, and debugging.

Sub-structure within bronze:
- `raw/` — Full historical dimension and fact files
- `staging/daily/` — Daily incremental transaction drops

**Deviation from challenge file:** The challenge file code writes Delta tables to `s3a://bronze/delta/transactions` — inside the bronze bucket. This implementation deliberately separates raw files (bronze) from Delta tables (silver). The challenge file comment itself says "Write as Delta table to silver bucket" but the path says bronze — this is a contradiction in the challenge file. The architecturally correct implementation writes Delta tables to the silver bucket only.

---

### Silver Layer

**Location:** `s3a://silver/delta/`
**Format:** Delta Lake tables
**Load pattern:** Overwrite for initial load; MERGE for incremental updates
**Retention:** Permanent

The silver layer contains cleaned, validated, and conformed data. Raw files from bronze are read by PySpark, transformed, and written as Delta tables. Delta Lake provides ACID transactions, schema enforcement, and time travel capabilities.

Transformations applied at silver:
- Customers: `customer_name` uppercased and trimmed, `email` lowercased, `created_date` cast to date, duplicates removed on `customer_id`
- Products: strings trimmed, `list_price` and `cost_price` cast to decimal, duplicates removed on `product_id`
- Stores: strings trimmed, `opening_date` cast to date, duplicates removed on `store_id`
- Transactions: `transaction_date` cast to date, rows with `quantity <= 0` or `unit_price <= 0` filtered, duplicates removed on `transaction_id`

**Why Delta Lake for silver:** Delta Lake provides the `_delta_log/` transaction log which records every write operation. This enables time travel (`VERSION AS OF`, `TIMESTAMP AS OF`) for debugging and reprocessing. Schema enforcement prevents corrupt data from silently landing in the table.

---

### Gold Layer

**Location:** `s3a://gold/delta/`
**Format:** Delta Lake tables
**Load pattern:** Overwrite for full historical load; MERGE for incremental
**Retention:** Permanent

The gold layer contains business-ready aggregations and dimension tables with surrogate keys assigned. Gold tables are the direct source for loading into PostgreSQL.

Tables in gold:
- `fact_sales` — Transaction-level fact table joined with dimension business keys
- `customers` — SCD2-structured customer dimension with `customer_key`, `effective_date`, `expiry_date`, `is_current`
- `products` — Product dimension with `product_key` surrogate
- `stores` — Store dimension with `store_key` surrogate

---

### PostgreSQL Serving Layer

**Location:** `retaildw` database, `warehouse` schema
**Format:** Relational star schema
**Load pattern:** Truncate-then-append via PySpark JDBC
**Retention:** Permanent

PostgreSQL serves as the analytical query engine for BI tools. The star schema is optimised for analytical queries with indexes on all foreign key columns in `fact_sales`.

**Why PostgreSQL for serving:** Spark SQL on Delta Lake is optimised for large-scale distributed processing but has higher query latency for interactive BI queries. PostgreSQL with a properly indexed star schema serves dashboard queries in milliseconds. Superset connects to PostgreSQL directly via SQLAlchemy — not to the Delta Lake lakehouse.

---

## Star Schema Design

### Dimension Tables

| Table | Type | Rows | Primary Key |
|---|---|---|---|
| dim_date | Static | 366 | date_key (INT) |
| dim_customer | SCD Type 2 | 10,000 | (customer_key, effective_date) |
| dim_product | Static | 1,000 | product_key (INT) |
| dim_store | Static | 200 | store_key (INT) |

### Fact Table

| Table | Grain | Rows | Foreign Keys |
|---|---|---|---|
| fact_sales | One row per transaction line item | 500,000 | date_key, customer_key, product_key, store_key |

**Grain definition:** Each row in `fact_sales` represents a single order line item — one product sold in one transaction at one store on one date.

### SCD Type 2 Implementation

`dim_customer` implements Slowly Changing Dimension Type 2 to track historical customer attribute changes. Each version of a customer record has:
- `effective_date` — date the record became active
- `expiry_date` — date the record was superseded (9999-12-31 for current records)
- `is_current` — boolean flag for the active version

**Partial unique index added (deviation from challenge file):**
```sql
CREATE UNIQUE INDEX idx_dim_customer_current
    ON warehouse.dim_customer(customer_key)
    WHERE is_current = TRUE;
```
This enforces that only one row per `customer_key` can have `is_current = TRUE` at any time. The challenge file omits this index. Without it, duplicate current records are possible and would cause double-counted revenue in analytics queries.

### Foreign Key Design Note

`fact_sales` references `dim_date`, `dim_product`, and `dim_store` via standard foreign keys. It does NOT have a foreign key to `dim_customer` despite having a `customer_key` column.

This is intentional. `dim_customer` has a composite primary key `(customer_key, effective_date)`. PostgreSQL foreign keys must reference a complete candidate key — a single `customer_key` column cannot reference half of a composite primary key. In a full SCD2 production implementation, a single-column surrogate key would be added to `dim_customer` to support this FK.

---

## Data Flow Summary

| Stage | Tool | Source | Target | Format |
|---|---|---|---|---|
| Data generation | Python + PyArrow | Synthetic | MinIO bronze | CSV, Parquet |
| Bronze to Silver | PySpark (Notebook 1) | s3a://bronze/raw/ | s3a://silver/delta/ | Delta Lake |
| Silver to Gold | PySpark (Notebook 2) | s3a://silver/delta/ | s3a://gold/delta/ | Delta Lake |
| Gold to PostgreSQL | PySpark JDBC (Notebook 3) | s3a://gold/delta/ | retaildw.warehouse.* | PostgreSQL |
| Serving | Apache Superset | retaildw | Dashboard | SQL + Charts |

---

## Notebook Pipeline

| Notebook | Purpose | Input | Output |
|---|---|---|---|
| 01_bronze_to_silver.ipynb | Ingest and clean raw data | s3a://bronze/raw/ | s3a://silver/delta/ |
| 02_silver_to_gold.ipynb | Aggregate and assign surrogate keys | s3a://silver/delta/ | s3a://gold/delta/ |
| 03_gold_to_postgres.ipynb | Load star schema | s3a://gold/delta/ | warehouse.* in retaildw |

---

## Technology Decisions

| Decision | Choice | Justification |
|---|---|---|
| Object storage | MinIO | S3-compatible, runs locally in Docker, no cloud dependency |
| Table format | Delta Lake | ACID transactions, schema enforcement, time travel, MERGE support |
| Distributed compute | Apache Spark 3.5 | Handles 500K+ rows with parallel execution, native Delta Lake support |
| Serving database | PostgreSQL 16 | Mature RDBMS, strong indexing, SQLAlchemy support for Superset |
| BI tool | Apache Superset | Open source, PostgreSQL native, SQL Lab for ad-hoc queries |
| Orchestration | Apache Airflow | Reused from Month 1, DAG-based pipeline scheduling |

---

## Deviations from Challenge File

| Deviation | Challenge File | This Implementation | Justification |
|---|---|---|---|
| Bronze Delta tables | Written to `s3a://bronze/delta/` | Written to `s3a://silver/delta/` | Challenge file code contradicts its own comment; silver is the correct layer for Delta tables |
| Partial unique index on dim_customer | Not present | Added `idx_dim_customer_current WHERE is_current = TRUE` | Enforces data quality constraint at DB level; prevents duplicate current records |
| Data volume | 100M rows historical | 500K rows | Local development environment memory constraints |
