import boto3
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import io
import os
from datetime import date, timedelta

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
MINIO_ENDPOINT   = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BRONZE_BUCKET    = "bronze"

NUM_CUSTOMERS    = 10_000
NUM_PRODUCTS     = 1_000
NUM_STORES       = 200
NUM_TRANSACTIONS = 500_000

np.random.seed(42)

# ─────────────────────────────────────────
# MINIO CLIENT
# ─────────────────────────────────────────
s3 = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
)

def upload_csv(df, key):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    s3.put_object(Bucket=BRONZE_BUCKET, Key=key, Body=buf.getvalue())
    print(f"✔ Uploaded CSV  → s3a://bronze/{key}  ({len(df):,} rows)")

def upload_parquet(df, key):
    buf = io.BytesIO()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, buf)
    buf.seek(0)
    s3.put_object(Bucket=BRONZE_BUCKET, Key=key, Body=buf.getvalue())
    print(f"✔ Uploaded Parquet → s3a://bronze/{key}  ({len(df):,} rows)")

# ─────────────────────────────────────────
# DIMENSION: STORES
# ─────────────────────────────────────────
print("\n── Generating stores ──")
cities  = ["New York","Los Angeles","Chicago","Houston","Phoenix",
           "Philadelphia","San Antonio","San Diego","Dallas","San Jose"]
states  = ["NY","CA","IL","TX","AZ","PA","TX","CA","TX","CA"]
regions = ["Northeast","West","Midwest","South","West",
           "Northeast","South","West","South","West"]
types   = ["Flagship","Standard","Express"]

store_ids = [f"STR{str(i).zfill(4)}" for i in range(1, NUM_STORES + 1)]
city_idx  = np.random.randint(0, len(cities), NUM_STORES)

df_stores = pd.DataFrame({
    "store_id"    : store_ids,
    "store_name"  : [f"RetailCo {cities[i]} {j}" for j, i in enumerate(city_idx)],
    "city"        : [cities[i] for i in city_idx],
    "state"       : [states[i] for i in city_idx],
    "region"      : [regions[i] for i in city_idx],
    "store_type"  : np.random.choice(types, NUM_STORES),
    "opening_date": pd.date_range("2015-01-01", periods=NUM_STORES, freq="2D")
                      .strftime("%Y-%m-%d"),
})
upload_csv(df_stores, "raw/stores/store_locations.csv")

# ─────────────────────────────────────────
# DIMENSION: CUSTOMERS
# ─────────────────────────────────────────
print("\n── Generating customers ──")
segments   = ["Premium","Standard","Budget"]
first_names = ["James","Mary","John","Patricia","Robert","Jennifer",
               "Michael","Linda","William","Barbara"]
last_names  = ["Smith","Johnson","Williams","Brown","Jones",
               "Garcia","Miller","Davis","Wilson","Moore"]

df_customers = pd.DataFrame({
    "customer_id"      : [f"CUS{str(i).zfill(6)}" for i in range(1, NUM_CUSTOMERS + 1)],
    "customer_name"    : [
        f"{np.random.choice(first_names)} {np.random.choice(last_names)}"
        for _ in range(NUM_CUSTOMERS)
    ],
    "email"            : [f"customer{i}@email.com" for i in range(1, NUM_CUSTOMERS + 1)],
    "city"             : [cities[i] for i in np.random.randint(0, len(cities), NUM_CUSTOMERS)],
    "state"            : [states[i] for i in np.random.randint(0, len(states), NUM_CUSTOMERS)],
    "zip_code"         : [str(np.random.randint(10000, 99999)) for _ in range(NUM_CUSTOMERS)],
    "customer_segment" : np.random.choice(segments, NUM_CUSTOMERS, p=[0.2, 0.5, 0.3]),
    "created_date"     : pd.date_range("2020-01-01", periods=NUM_CUSTOMERS, freq="1h")
                           .strftime("%Y-%m-%d"),
})
upload_csv(df_customers, "raw/customers/customer_master_full.csv")

# ─────────────────────────────────────────
# DIMENSION: PRODUCTS
# ─────────────────────────────────────────
print("\n── Generating products ──")
categories = {
    "Electronics" : ["Laptops","Phones","Tablets","Accessories"],
    "Clothing"    : ["Shirts","Pants","Shoes","Jackets"],
    "Food"        : ["Snacks","Beverages","Dairy","Produce"],
    "Home"        : ["Furniture","Appliances","Decor","Bedding"],
    "Sports"      : ["Equipment","Apparel","Footwear","Accessories"],
}
brands = ["BrandA","BrandB","BrandC","BrandD","BrandE"]

rows = []
pid  = 1
per_cat = NUM_PRODUCTS // len(categories)
for cat, subs in categories.items():
    for _ in range(per_cat):
        sub        = np.random.choice(subs)
        list_price = round(np.random.uniform(5, 500), 2)
        cost_price = round(list_price * np.random.uniform(0.4, 0.7), 2)
        rows.append({
            "product_id"  : f"PRD{str(pid).zfill(5)}",
            "product_name": f"{np.random.choice(brands)} {sub} {pid}",
            "category"    : cat,
            "subcategory" : sub,
            "brand"       : np.random.choice(brands),
            "list_price"  : list_price,
            "cost_price"  : cost_price,
            "is_active"   : True,
        })
        pid += 1

df_products = pd.DataFrame(rows)
upload_csv(df_products, "raw/products/product_catalog_full.csv")

# ─────────────────────────────────────────
# FACT: TRANSACTIONS (partitioned by year/month)
# ─────────────────────────────────────────
print("\n── Generating transactions ──")
start_date = date(2024, 1, 1)
end_date   = date(2024, 12, 31)
date_range = [start_date + timedelta(days=i)
              for i in range((end_date - start_date).days + 1)]

transaction_dates = np.random.choice(date_range, NUM_TRANSACTIONS)
df_tx = pd.DataFrame({
    "transaction_id"  : [f"TXN{str(i).zfill(9)}" for i in range(1, NUM_TRANSACTIONS + 1)],
    "transaction_date": transaction_dates,
    "customer_id"     : np.random.choice(df_customers["customer_id"], NUM_TRANSACTIONS),
    "product_id"      : np.random.choice(df_products["product_id"],   NUM_TRANSACTIONS),
    "store_id"        : np.random.choice(df_stores["store_id"],       NUM_TRANSACTIONS),
    "order_id"        : [f"ORD{str(np.random.randint(1, 200000)).zfill(8)}"
                         for _ in range(NUM_TRANSACTIONS)],
    "order_line_num"  : np.random.randint(1, 6, NUM_TRANSACTIONS),
    "quantity"        : np.random.randint(1, 11, NUM_TRANSACTIONS),
    "unit_price"      : np.random.choice(df_products["list_price"],   NUM_TRANSACTIONS),
    "unit_cost"       : np.random.choice(df_products["cost_price"],   NUM_TRANSACTIONS),
    "discount_amount" : np.round(np.random.uniform(0, 20, NUM_TRANSACTIONS), 2),
})
df_tx["net_revenue"]  = np.round(
    df_tx["quantity"] * df_tx["unit_price"] - df_tx["discount_amount"], 2)
df_tx["gross_profit"] = np.round(
    df_tx["net_revenue"] - df_tx["quantity"] * df_tx["unit_cost"], 2)
df_tx["tax_amount"]   = np.round(df_tx["net_revenue"] * 0.08, 2)
# df_tx["transaction_date"] = pd.to_datetime(df_tx["transaction_date"])
df_tx["transaction_date"] = pd.to_datetime(df_tx["transaction_date"])
# Cast to microsecond precision — nanoseconds cause INT64(NANOS) in parquet
# which Spark 3.5 rejects by default
df_tx["transaction_date"] = df_tx["transaction_date"].astype("datetime64[us]")

# Upload partitioned by year/month
for (year, month), group in df_tx.groupby([
    df_tx["transaction_date"].dt.year,
    df_tx["transaction_date"].dt.month
]):
    key = f"raw/transactions/year={year}/month={month:02d}/transactions_{year}{month:02d}.parquet"
    # Fix timestamp precision — write as microseconds not nanoseconds
    df_tx["transaction_date"] = df_tx["transaction_date"].astype("datetime64[us]")
    upload_parquet(group.reset_index(drop=True), key)

print(f"\n✅ Data generation complete.")
print(f"   Stores      : {len(df_stores):,}")
print(f"   Customers   : {len(df_customers):,}")
print(f"   Products    : {len(df_products):,}")
print(f"   Transactions: {len(df_tx):,}")