import os, re, boto3

MINIO_ENDPOINT = "http://localhost:9005"
MINIO_ACCESS_KEY = "admin"
MINIO_SECRET_KEY = "annapurna123"
BUCKET_NAME = "annapurna"
LOCAL_SALES_DIR = r"C:\Users\ub02-glab-002\Desktop\data\data_1\sales"

FNAME_RE = re.compile(r"SALES_(S\d+)_(\d{4})(\d{2})(\d{2})(?:__R\d+)?\.(csv|parquet)")

s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT, aws_access_key_id=MINIO_ACCESS_KEY, aws_secret_access_key=MINIO_SECRET_KEY)

def ensure_bucket():
    existing = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    if BUCKET_NAME not in existing:
        s3.create_bucket(Bucket=BUCKET_NAME)

def partition_key(filename):
    m = FNAME_RE.match(filename)
    if not m:
        return None
    store, year, month, _, _ = m.groups()
    return f"raw/sales/store_id={store}/year={year}/month={month}/{filename}"

def main():
    ensure_bucket()
    uploaded, skipped = 0, 0
    for filename in os.listdir(LOCAL_SALES_DIR):
        key = partition_key(filename)
        if key is None:
            skipped += 1
            continue
        local_path = os.path.join(LOCAL_SALES_DIR, filename)
        try:
            s3.head_object(Bucket=BUCKET_NAME, Key=key)
            continue
        except s3.exceptions.ClientError:
            pass
        s3.upload_file(local_path, BUCKET_NAME, key)
        uploaded += 1
    print(f"Uploaded: {uploaded}, Skipped/unmatched: {skipped}")

if __name__ == "__main__":
    main()