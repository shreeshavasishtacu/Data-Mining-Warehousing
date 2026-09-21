import duckdb

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute("INSTALL postgres; LOAD postgres;")
con.execute("SET s3_endpoint='localhost:9005';")
con.execute("SET s3_access_key_id='admin';")
con.execute("SET s3_secret_access_key='annapurna123';")
con.execute("SET s3_use_ssl=false;")
con.execute("SET s3_url_style='path';")

con.execute("ATTACH 'host=localhost port=5435 dbname=annapurna user=annapurna password=annapurna' AS pg (TYPE postgres);")

con.execute("""
CREATE OR REPLACE VIEW fact_resolved AS
SELECT
  f.*,
  p.product_sk,
  p.category_id,
  pr.selling_price AS asof_price
FROM read_parquet('s3://annapurna/curated/fact_sales.parquet') f
JOIN pg.public.products p
  ON f.product_code = p.product_code
 AND f.business_date::DATE >= p.valid_from
 AND f.business_date::DATE < COALESCE(p.valid_to, DATE '9999-12-31')
JOIN pg.public.price_revisions pr
  ON p.product_sk = pr.product_sk
 AND f.business_date::DATE >= pr.effective_from
 AND f.business_date::DATE < COALESCE(pr.effective_to, DATE '9999-12-31');
""")

print("=== by store ===")
print(con.execute("""
SELECT store_id, ROUND(SUM(line_amount),2) AS revenue
FROM fact_resolved GROUP BY store_id ORDER BY store_id;
""").df())

print("=== by category ===")
print(con.execute("""
SELECT pc.category_name, ROUND(SUM(f.line_amount),2) AS revenue
FROM fact_resolved f JOIN pg.public.product_categories pc ON f.category_id = pc.category_id
GROUP BY pc.category_name ORDER BY revenue DESC;
""").df())

print("=== by day of week ===")
print(con.execute("""
SELECT dayname(business_date::DATE) AS dow, ROUND(SUM(line_amount),2) AS revenue
FROM fact_resolved GROUP BY dow ORDER BY revenue DESC;
""").df())

print("=== by month ===")
print(con.execute("""
SELECT strftime(business_date::DATE, '%Y-%m') AS month, ROUND(SUM(line_amount),2) AS revenue
FROM fact_resolved GROUP BY month ORDER BY month;
""").df())

def period_query(period_start, period_end):
    return con.execute(f"""
        SELECT ROUND(SUM(qty * asof_price),2) AS revenue_at_period_price
        FROM fact_resolved
        WHERE business_date::DATE >= DATE '{period_start}' AND business_date::DATE < DATE '{period_end}';
    """).df()

print("=== March 2024 (period-priced) ===")
print(period_query("2024-03-01", "2024-04-01"))
print("=== Dec 2024 (period-priced) ===")
print(period_query("2024-12-01", "2025-01-01"))

print("=== EXPLAIN ANALYZE federated query ===")
print(con.execute("""
EXPLAIN ANALYZE
SELECT s.store_id, pc.category_name, ROUND(SUM(f.line_amount),2) AS revenue
FROM read_parquet('s3://annapurna/curated/fact_sales.parquet') f
JOIN pg.public.stores s ON f.store_id = s.store_id
JOIN pg.public.products p ON f.product_code = p.product_code
  AND f.business_date::DATE >= p.valid_from AND f.business_date::DATE < COALESCE(p.valid_to, DATE '9999-12-31')
JOIN pg.public.product_categories pc ON p.category_id = pc.category_id
GROUP BY s.store_id, pc.category_name;
""").fetchall())

# --- Reconciliation: use finance_monthly.csv's own month column directly ---
print("=== finance_monthly.csv raw columns check ===")
print(con.execute("""
SELECT * FROM read_csv_auto('C:/Users/ub02-glab-002/Desktop/data/data_1/finance_monthly.csv') LIMIT 3;
""").df())

print("=== reconciliation ===")
print(con.execute("""
WITH pipeline AS (
  SELECT strftime(business_date::DATE, '%Y-%m') AS month, ROUND(SUM(line_amount),2) AS pipeline_revenue
  FROM fact_resolved GROUP BY month
),
finance AS (
  SELECT month, revenue_inr
  FROM read_csv_auto('C:/Users/ub02-glab-002/Desktop/data/data_1/finance_monthly.csv')
)
SELECT f.month, f.revenue_inr AS finance_revenue, p.pipeline_revenue,
       ROUND(f.revenue_inr - p.pipeline_revenue, 2) AS difference,
       ROUND(100.0*(f.revenue_inr - p.pipeline_revenue)/f.revenue_inr, 2) AS pct
FROM finance f LEFT JOIN pipeline p ON f.month = p.month
ORDER BY f.month;
""").df())