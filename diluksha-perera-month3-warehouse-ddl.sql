-- ============================================================
-- Month 3: Star Schema DDL
-- Database : retaildw
-- User     : dataeng
-- ============================================================

-- ─────────────────────────────────────────
-- SCHEMA
-- ─────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS warehouse;
SET search_path TO warehouse;

-- ─────────────────────────────────────────
-- DIM_DATE
-- ─────────────────────────────────────────
CREATE TABLE warehouse.dim_date (
    date_key        INT             NOT NULL PRIMARY KEY,
    full_date       DATE            NOT NULL,
    year_number     INT             NOT NULL,
    quarter_number  INT             NOT NULL,
    month_number    INT             NOT NULL,
    month_name      VARCHAR(20)     NOT NULL,
    day_of_week     INT             NOT NULL,
    day_name        VARCHAR(20)     NOT NULL,
    is_weekend      BOOLEAN         NOT NULL DEFAULT FALSE,
    is_holiday      BOOLEAN         NOT NULL DEFAULT FALSE
);

-- ─────────────────────────────────────────
-- DIM_CUSTOMER (SCD Type 2)
-- ─────────────────────────────────────────
CREATE TABLE warehouse.dim_customer (
    customer_key        INT             NOT NULL,
    customer_id         VARCHAR(20)     NOT NULL,
    customer_name       VARCHAR(100)    NOT NULL,
    email               VARCHAR(100),
    city                VARCHAR(50),
    state               VARCHAR(2),
    zip_code            VARCHAR(10),
    customer_segment    VARCHAR(20),
    effective_date      DATE            NOT NULL,
    expiry_date         DATE            NOT NULL,
    is_current          BOOLEAN         NOT NULL,
    PRIMARY KEY (customer_key, effective_date)
);

-- Unique constraint on surrogate key for current records only
-- Supports lookup of active customer_key during fact load
CREATE UNIQUE INDEX idx_dim_customer_current
    ON warehouse.dim_customer(customer_key)
    WHERE is_current = TRUE;

-- ─────────────────────────────────────────
-- DIM_PRODUCT
-- ─────────────────────────────────────────
CREATE TABLE warehouse.dim_product (
    product_key     INT             NOT NULL PRIMARY KEY,
    product_id      VARCHAR(20)     NOT NULL,
    product_name    VARCHAR(100)    NOT NULL,
    category        VARCHAR(50),
    subcategory     VARCHAR(50),
    brand           VARCHAR(50),
    list_price      DECIMAL(10,2),
    cost_price      DECIMAL(10,2),
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE
);

-- ─────────────────────────────────────────
-- DIM_STORE
-- ─────────────────────────────────────────
CREATE TABLE warehouse.dim_store (
    store_key       INT             NOT NULL PRIMARY KEY,
    store_id        VARCHAR(20)     NOT NULL,
    store_name      VARCHAR(100)    NOT NULL,
    city            VARCHAR(50),
    state           VARCHAR(2),
    region          VARCHAR(30),
    store_type      VARCHAR(20),
    opening_date    DATE
);

-- ─────────────────────────────────────────
-- FACT_SALES
-- ─────────────────────────────────────────
CREATE TABLE warehouse.fact_sales (
    sales_key           BIGINT          NOT NULL PRIMARY KEY,
    date_key            INT             NOT NULL
                            REFERENCES warehouse.dim_date(date_key),
    customer_key        INT             NOT NULL,
    product_key         INT             NOT NULL
                            REFERENCES warehouse.dim_product(product_key),
    store_key           INT             NOT NULL
                            REFERENCES warehouse.dim_store(store_key),
    order_id            VARCHAR(20)     NOT NULL,
    order_line_num      INT             NOT NULL,
    quantity            INT             NOT NULL,
    unit_price          DECIMAL(10,2)   NOT NULL,
    unit_cost           DECIMAL(10,2)   NOT NULL,
    discount_amount     DECIMAL(10,2)   NOT NULL DEFAULT 0,
    net_revenue         DECIMAL(12,2)   NOT NULL,
    gross_profit        DECIMAL(12,2)   NOT NULL,
    tax_amount          DECIMAL(10,2)   NOT NULL DEFAULT 0
);

-- ─────────────────────────────────────────
-- INDEXES ON FACT_SALES
-- ─────────────────────────────────────────
CREATE INDEX idx_fact_sales_date
    ON warehouse.fact_sales(date_key);

CREATE INDEX idx_fact_sales_customer
    ON warehouse.fact_sales(customer_key);

CREATE INDEX idx_fact_sales_product
    ON warehouse.fact_sales(product_key);

CREATE INDEX idx_fact_sales_store
    ON warehouse.fact_sales(store_key);

CREATE INDEX idx_fact_sales_order
    ON warehouse.fact_sales(order_id);