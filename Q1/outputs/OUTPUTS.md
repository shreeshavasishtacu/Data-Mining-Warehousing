# Question 1 — Annapurna Stores — Captured Outputs

## Part (a) — Land the data, partitioned layout
See: a_compare_layout.png

```
Uploaded: 4457, Skipped/unmatched: 0
Partitioned (this store+month only): 31 files, 872,458 bytes
Flat folder (must open everything):   4457 files, 68,706,877 bytes
Reduction: 4426 fewer files, 67,834,419 fewer bytes
```

## Part (b) — Idempotent loading (3 runs)
See: b_load_progress.png

Run 1: rows=789516 checksum=7cbf3be2108be8594cca64fa56f8ea6fd094ce8d51d0f0d4fb4ef20d8cf0ee1c
Run 2: rows=789516 checksum=7cbf3be2108be8594cca64fa56f8ea6fd094ce8d51d0f0d4fb4ef20d8cf0ee1c
Run 3: rows=789516 checksum=7cbf3be2108be8594cca64fa56f8ea6fd094ce8d51d0f0d4fb4ef20d8cf0ee1c

All three runs produced identical row counts and checksums, confirming
idempotency of the ON CONFLICT (bill_no, line_no) DO NOTHING load logic.

## Part (c) — Star schema, dashboard slicing
See: c_by_store_category_day.png, c_product_sample_1.png, c_product_sample_2.png

Revenue sliceable by store_id, category_name, day_name, month/year —
confirmed via dim_store, dim_date, dim_product, fact_sales.

## Part (d) — Point-in-time pricing
March 2024 (period-priced): revenue_at_period_price = 42,209,951.56
December 2024 (period-priced): revenue_at_period_price = 51,247,862.94

Same query, only the reporting period changed — no code change between runs.

## Part (e) — Federated DuckDB + PostgreSQL query
See: e_explain_analyze_1.png through e_explain_analyze_4.png

Total Time: 0.110s (also observed 0.230s-0.296s on later runs)
Final grouped rows: 112

TABLE_SCAN fact_sales (Parquet, MinIO): 562,754-787,751 rows
TABLE_SCAN stores (PostgreSQL): 12 rows
TABLE_SCAN products (PostgreSQL): 1,224 rows
TABLE_SCAN product_categories (PostgreSQL): 14 rows
HASH_JOIN store_id = store_id
HASH_JOIN product_sk/product_code = product_sk/product_code
HASH_JOIN category_id = category_id
HASH_GROUP_BY -> 112 rows
ORDER_BY -> 112 rows

## Part (f) — Reconciliation (CORRECTED)
See: f_line_type_breakdown.png

NOTE: f_STALE_*.png files are from BEFORE a bug fix (reconciliation was
joining on finance's closed_on date instead of the month column, causing
false ~29% differences). Do not use those three files. Corrected result:

```
      month  finance_revenue  pipeline_revenue  difference   pct
0   2024-01      38446071.33       38717550.59  -271479.26 -0.71
1   2024-02      34887085.55       35126365.31  -239279.76 -0.69
2   2024-03      42457899.09       42209669.20   248229.89  0.58
3   2024-04      37958457.37       38156724.39  -198267.02 -0.52
4   2024-05      41764716.40       41943742.27  -179025.87 -0.43
5   2024-06      38987082.82       39189001.01  -201918.19 -0.52
6   2024-07      40527291.81       40512093.48    15198.33  0.04
7   2024-08      45252181.75       45490537.91  -238356.16 -0.53
8   2024-09      44615037.46       44875490.85  -260453.39 -0.58
9   2024-10      56359195.92       56620712.39  -261516.47 -0.46
10  2024-11      51583838.47       51974080.02  -390241.55 -0.76
11  2024-12      50745209.00       51256695.71  -511486.71 -1.01
```

Classification:
- Jan-Nov: source-data noise, all within ~0.7%
- Mar: source-data (partially explained by documented bulk institutional
  invoice outside the till system)
- Dec: definitional difference (finance rounds each bill to the nearest
  rupee before totaling; pipeline keeps exact decimal precision)

Nothing here indicates a pipeline bug. Item to escalate to finance:
December's per-bill rounding convention, to decide whether the pipeline
should match it going forward.

## Also captured: line-type breakdown
See: f_line_type_breakdown.png
```
line_type   rows      amount
DISCOUNT    16185   -3798963.49
RETURN      11557   -8345572.27
SALE       531594  387059355.94
VOID         3418   -2309129.78
```
