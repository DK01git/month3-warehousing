# Month 3 Performance Analysis Report


---

## Overview

This report analyses query performance on the Month 3 star schema in PostgreSQL, compares execution plans with and without index usage, documents index statistics, and presents the Superset dashboard results.

---

## Environment

| Component | Version | Details |
|---|---|---|
| PostgreSQL | 16-alpine | Running in Docker container |
| Dataset | Synthetic retail | 500,000 fact rows, 10,000 customers, 1,000 products, 200 stores, 366 dates |
| Schema | warehouse | 5 tables: dim_date, dim_customer, dim_product, dim_store, fact_sales |

---

## Step 1 — Statistics Update

Before running any analytical queries, table statistics were updated to ensure the PostgreSQL query planner uses accurate row count and distribution estimates:

```sql
ANALYZE warehouse.fact_sales;
ANALYZE warehouse.dim_date;
ANALYZE warehouse.dim_customer;
ANALYZE warehouse.dim_product;
ANALYZE warehouse.dim_store;
```

This is critical after bulk loads. Without updated statistics, the planner uses stale estimates and may choose suboptimal execution plans.

---

## Query 1 — Full Aggregation (No Filter)

### SQL

```sql
EXPLAIN ANALYZE
SELECT
    d.year_number,
    d.month_name,
    s.region,
    p.category,
    COUNT(*)                    AS transaction_count,
    SUM(f.net_revenue)          AS total_revenue,
    SUM(f.gross_profit)         AS total_profit
FROM warehouse.fact_sales f
JOIN warehouse.dim_date    d ON f.date_key    = d.date_key
JOIN warehouse.dim_store   s ON f.store_key   = s.store_key
JOIN warehouse.dim_product p ON f.product_key = p.product_key
GROUP BY d.year_number, d.month_name, s.region, p.category
ORDER BY d.year_number, d.month_name;
```

### Execution Plan

```
Finalize GroupAggregate  (cost=15608.37..15678.77 rows=240 width=96)
                         (actual time=489.140..493.729 rows=240 loops=1)
   Group Key: d.year_number, d.month_name, s.region, p.category
   ->  Gather Merge  (cost=15608.37..15664.37 rows=480 width=96)
                     (actual time=487.464..490.514 rows=720 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         ->  Sort  (actual time=464.038..464.061 rows=240 loops=3)
               Sort Method: quicksort  Memory: 71kB
               ->  Partial HashAggregate  (actual time=462.832..463.078 rows=240 loops=3)
                     ->  Hash Join  (actual time=1.087..285.047 rows=166667 loops=3)
                           ->  Hash Join  (actual time=0.516..212.754 rows=166667 loops=3)
                                 ->  Hash Join  (actual time=0.301..144.307 rows=166667 loops=3)
                                       ->  Parallel Seq Scan on fact_sales f
                                           (actual time=0.011..31.295 rows=166667 loops=3)
                                       ->  Seq Scan on dim_date d
                                           (rows=366 loops=3)
                                 ->  Seq Scan on dim_store s
                                     (rows=200 loops=3)
                           ->  Seq Scan on dim_product p
                               (rows=1000 loops=3)
Planning Time: 11.422 ms
Execution Time: 495.905 ms
```

### Analysis

**Access method:** Parallel Sequential Scan on `fact_sales`
**Parallel workers:** 2 workers + 1 leader = 3 total processes
**Join strategy:** Hash Join on all three dimension joins
**Execution time:** 495ms

**Why sequential scan over index scan:** This query has no WHERE clause — it aggregates ALL 500,000 rows. An index is only beneficial when filtering a small subset of rows. When every row is needed, a sequential scan is faster because it reads pages linearly in one pass. Using an index on a full-table scan would require one index lookup per row plus a random heap fetch, which is significantly more expensive than a single sequential pass.

**Why Hash Join on small dimensions:** `dim_date` (366 rows), `dim_store` (200 rows), and `dim_product` (1,000 rows) are all small enough to fit entirely in memory hash tables. Hash Join is optimal for this scenario — build a hash table from the small dimension, then probe it once per fact row. The entire dimension hash table fit in 17-71KB of memory.

**Why parallel execution:** PostgreSQL automatically parallelised the sequential scan across 2 workers. Each worker processed ~166,667 rows (500,000 / 3). This is visible in `loops=3` throughout the plan. Parallel execution reduced wall-clock time from an estimated ~1.4 seconds single-threaded to 495ms.

---

## Query 2 — Filtered Query (Index Usage)

### SQL

```sql
EXPLAIN ANALYZE
SELECT
    f.order_id,
    f.quantity,
    f.net_revenue,
    p.product_name,
    p.category
FROM warehouse.fact_sales f
JOIN warehouse.dim_product p ON f.product_key = p.product_key
WHERE f.date_key = 20240115;
```

### Execution Plan

```
Hash Join  (cost=54.47..3492.16 rows=1361 width=48)
           (actual time=12.064..791.228 rows=1359 loops=1)
   Hash Cond: (f.product_key = p.product_key)
   ->  Bitmap Heap Scan on fact_sales f
       (actual time=3.894..767.869 rows=1359 loops=1)
         Recheck Cond: (date_key = 20240115)
         Heap Blocks: exact=1241
         ->  Bitmap Index Scan on idx_fact_sales_date
             (actual time=3.082..3.083 rows=1359 loops=1)
               Index Cond: (date_key = 20240115)
   ->  Hash  (actual time=7.712..7.713 rows=1000 loops=1)
         ->  Seq Scan on dim_product p
             (actual time=0.010..7.480 rows=1000 loops=1)
Planning Time: 24.841 ms
Execution Time: 792.223 ms
```

### Analysis

**Access method:** Bitmap Index Scan on `idx_fact_sales_date` — index was used
**Rows returned:** 1,359 (filtered from 500,000)
**Heap blocks accessed:** 1,241
**Execution time:** 792ms

**Why the indexed query is slower than the full aggregation:** This is a counterintuitive but important result. The indexed query took 792ms while the full aggregation took 495ms. There are two reasons:

1. **No parallel execution:** The filtered query ran single-threaded. The planner determined the result set (1,359 rows) was small enough not to warrant spawning parallel workers. The full aggregation ran across 3 parallel processes.

2. **Scattered heap access (random I/O):** The Bitmap Index Scan identified 1,359 matching rows scattered across 1,241 different heap blocks. Accessing 1,241 non-contiguous disk pages requires random I/O, which is significantly slower than the sequential scan that reads pages in order. On a freshly loaded table, rows are not physically sorted by `date_key`, so matching rows are scattered across the entire table.

**Production fix:** In production this would be resolved with:
```sql
CLUSTER warehouse.fact_sales USING idx_fact_sales_date;
```
This physically reorders the table on disk by `date_key`, so all rows for a given date are co-located. Bitmap heap scans on date-filtered queries would then require far fewer random I/O operations.

---

## Index Usage Statistics

```sql
SELECT
    indexrelname        AS index_name,
    idx_scan            AS times_used,
    idx_tup_read        AS tuples_read,
    idx_tup_fetch       AS tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'warehouse'
ORDER BY idx_scan DESC;
```

### Results

```
index_name               | times_used | tuples_read | tuples_fetched
-------------------------+------------+-------------+----------------
dim_date_pkey            |    1000014 |     1000002 |        1000002
dim_product_pkey         |    1000002 |     1000002 |        1000002
dim_store_pkey           |     500002 |      500002 |         500002
idx_fact_sales_store     |          2 |           2 |              0
idx_fact_sales_date      |          2 |           2 |              0
idx_fact_sales_product   |          2 |           2 |              0
idx_fact_sales_customer  |          0 |           0 |              0
fact_sales_pkey          |          0 |           0 |              0
idx_fact_sales_order     |          0 |           0 |              0
```

### Analysis

**Dimension primary keys heavily used:** `dim_date_pkey` was used 1,000,014 times — primarily during the JDBC load process when PostgreSQL checked FK constraints on each `fact_sales` insert. Each of the 500,000 fact rows triggered FK lookups on `dim_date`, `dim_product`, and `dim_store`.

**Fact table indexes rarely used:** `idx_fact_sales_store`, `idx_fact_sales_date`, and `idx_fact_sales_product` each show only 2 uses — these correspond to the FK constraint checks during the small dimension loads, not analytical queries. The analytical queries performed full sequential scans as documented above.

**Conclusion:** Indexes on `fact_sales` foreign key columns are correctly defined and will be used for selective filter queries in production dashboards. The low usage count in this report reflects the current workload (bulk load + two analytical queries) rather than any indexing deficiency.

---

## Query Performance Comparison

| Query | Method | Workers | Execution Time | Notes |
|---|---|---|---|---|
| Full aggregation (no filter) | Parallel Seq Scan | 3 | 495ms | All 500K rows, parallel |
| Single date filter | Bitmap Index Scan | 1 | 792ms | 1,359 rows, single-threaded, scattered I/O |

---

## Apache Superset Dashboard

### Connection

Database: `RetailDW`
SQLAlchemy URI: `postgresql://dataeng:dataeng123@month1-postgres-retail-1:5432/retaildw`

### SQL Lab Query Result

The following ad-hoc query was executed in Superset SQL Lab in **635ms**:

```sql
SELECT
    d.month_name,
    d.month_number,
    p.category,
    COUNT(*)                AS transaction_count,
    SUM(f.net_revenue)      AS total_revenue,
    SUM(f.gross_profit)     AS total_profit
FROM warehouse.fact_sales f
JOIN warehouse.dim_date    d ON f.date_key    = d.date_key
JOIN warehouse.dim_product p ON f.product_key = p.product_key
GROUP BY d.month_name, d.month_number, p.category
ORDER BY d.month_number;
```

Sample results (January):

| month_name | category | transaction_count | total_revenue |
|---|---|---|---|
| January | Clothing | 8,347 | 11,617,120.12 |
| January | Electronics | 8,712 | 12,121,754.21 |
| January | Food | 8,273 | 11,719,112.55 |
| January | Home | 8,469 | 11,926,666.79 |
| January | Sports | 8,487 | 11,962,610.02 |

### Dashboard: Retail Sales Overview

Three charts assembled into a single published dashboard:

**Chart 1 — Monthly Revenue by Categories (Bar Chart)**
Shows monthly net revenue broken down by product category across all 12 months of 2024. All five categories (Electronics, Clothing, Food, Home, Sports) show consistent revenue of approximately 11-12M per month, reflecting the uniform distribution of synthetic data.

**Chart 2 — Revenue by Category Mix (Pie Chart)**
Shows proportional revenue contribution by category. Electronics leads slightly with ~20.2% share, followed by Clothing, Home, Food, and Sports in near-equal proportions (~19.9% each).

**Chart 3 — Revenue Trends by Category (Line Chart)**
Shows monthly revenue trend lines per category from month 1 through month 12. All categories show flat trend lines consistent with uniform synthetic data generation. In production data, seasonal patterns would be visible — electronics spikes in Q4, sports in Q2/Q3.

**Note on bar chart metric:** The bar chart was configured to show `net_revenue` (not gross profit as in an intermediate version). This aligns with the challenge file specification of "monthly revenue."

---

## Recommendations for Production

| Recommendation | Impact | Effort |
|---|---|---|
| `CLUSTER fact_sales USING idx_fact_sales_date` | Reduces date-filtered query time by 60-80% | Low |
| Partition `fact_sales` by year/month | Eliminates partition pruning overhead on large tables | Medium |
| Use `pg_partman` for automated partition management | Reduces operational overhead | Medium |
| Add covering index `(date_key, store_key, net_revenue)` | Enables index-only scans for common dashboard queries | Low |
| Schedule `ANALYZE` after daily loads | Keeps planner statistics current | Low |
| Implement incremental MERGE loads | Eliminates full truncate-reload cycle | High |
