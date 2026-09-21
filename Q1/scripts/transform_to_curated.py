import os, re, hashlib
import pandas as pd
import boto3

LOCAL_SALES_DIR = r"C:\Users\ub02-glab-002\Desktop\data\data_1\sales"
OUT_LOCAL = r"C:\Users\ub02-glab-002\Desktop\data\data_1\curated_fact_sales.parquet"

MINIO_ENDPOINT = "http://localhost:9005"
MINIO_ACCESS_KEY = "admin"
MINIO_SECRET_KEY = "annapurna123"
BUCKET_NAME = "annapurna"

FNAME_RE = re.compile(r"SALES_(S\d+)_(\d{4})(\d{2})(\d{2})(?:__R\d+)?\.(csv|parquet)")

REVENUE_TYPES = {"SALE", "RETURN", "DISCOUNT", "VOID"}

def store_group(store_id):
    n = int(store_id[1:])
    if 1 <= n <= 5: return "A"
    if 6 <= n <= 9: return "B"
    return "C"

def read_one(path, store_id):
    ext = path.split(".")[-1].lower()
    grp = store_group(store_id)
    if ext == "parquet":
        df = pd.read_parquet(path)
        if "bill_no" not in df.columns and "item_code" in df.columns:
            df = df.rename(columns={"item_code":"product_code","quantity":"qty","rate":"unit_price","type":"line_type","txn_time":"ts"})
        return df
    if grp == "B":
        df = pd.read_csv(path, sep=";", encoding="utf-8")
        df = df.rename(columns={"item_code":"product_code","quantity":"qty","rate":"unit_price","type":"line_type","txn_time":"ts"})
        return df
    if grp == "C":
        df = pd.read_csv(path, sep=",", encoding="utf-8-sig")
        return df
    return pd.read_csv(path, sep=",", encoding="utf-8")

def main():
    files = os.listdir(LOCAL_SALES_DIR)
    seen_keys = set()
    rows = []

    for filename in files:
        m = FNAME_RE.match(filename)
        if not m:
            continue
        store_id, year, month, day, ext = m.groups()
        business_date = f"{year}-{month}-{day}"
        path = os.path.join(LOCAL_SALES_DIR, filename)
        try:
            df = read_one(path, store_id)
        except Exception as e:
            print(f"skip {filename}: {e}")
            continue

        df.columns = [c.strip().lower() for c in df.columns]
        required = {"bill_no","line_no","product_code","qty","unit_price","line_type"}
        if not required.issubset(set(df.columns)):
            print(f"skip {filename}: missing columns {required - set(df.columns)}")
            continue

        df = df[df["line_type"].isin(REVENUE_TYPES)]

        for _, r in df.iterrows():
            key = (str(r["bill_no"]), str(r["line_no"]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append({
                "bill_no": str(r["bill_no"]),
                "line_no": str(r["line_no"]),
                "store_id": store_id,
                "business_date": business_date,
                "product_code": str(r["product_code"]),
                "qty": float(r["qty"]),
                "unit_price": float(r["unit_price"]),
                "line_type": r["line_type"],
                "line_amount": float(r["qty"]) * float(r["unit_price"]),
            })

    out = pd.DataFrame(rows)
    out.to_parquet(OUT_LOCAL, index=False)

    row_count = len(out)
    checksum = hashlib.sha256(
        "".join(sorted(f"{r.bill_no}:{r.line_no}" for r in out.itertuples())).encode()
    ).hexdigest()
    print(f"rows={row_count} checksum={checksum}")

    s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT, aws_access_key_id=MINIO_ACCESS_KEY, aws_secret_access_key=MINIO_SECRET_KEY)
    existing = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    if BUCKET_NAME not in existing:
        s3.create_bucket(Bucket=BUCKET_NAME)
    s3.upload_file(OUT_LOCAL, BUCKET_NAME, "curated/fact_sales.parquet")
    print("uploaded curated/fact_sales.parquet")

if __name__ == "__main__":
    main()