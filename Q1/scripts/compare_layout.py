import boto3

MINIO_ENDPOINT = "http://localhost:9005"
MINIO_ACCESS_KEY = "admin"
MINIO_SECRET_KEY = "annapurna123"
BUCKET_NAME = "annapurna"

s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT, aws_access_key_id=MINIO_ACCESS_KEY, aws_secret_access_key=MINIO_SECRET_KEY)

def list_all(prefix=""):
    files, total_bytes = 0, 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            files += 1
            total_bytes += obj["Size"]
    return files, total_bytes

STORE, YEAR, MONTH = "S03", "2024", "10"

part_files, part_bytes = list_all(f"raw/sales/store_id={STORE}/year={YEAR}/month={MONTH}/")
flat_files, flat_bytes = list_all("raw/sales/")

print(f"Partitioned: {part_files} files, {part_bytes:,} bytes")
print(f"Flat: {flat_files} files, {flat_bytes:,} bytes")
print(f"Reduction: {flat_files-part_files} fewer files, {flat_bytes-part_bytes:,} fewer bytes")