import psycopg2, time

conn = psycopg2.connect(host="localhost", port=5434, dbname="setubid", user="setubid", password="setubid")
cur = conn.cursor()

TARGET = "N005451"  # any real notice_id from your corpus

query = """
SELECT DISTINCT b2.notice_id
FROM minhash_bands b1
JOIN minhash_bands b2 ON b1.band_no = b2.band_no AND b1.band_hash = b2.band_hash
WHERE b1.notice_id = %s AND b2.notice_id <> %s;
"""

print("=== WITH index (chosen access method) ===")
cur.execute("SET enable_seqscan = off;")
t0 = time.time()
cur.execute("EXPLAIN ANALYZE " + query, (TARGET, TARGET))
for row in cur.fetchall():
    print(row[0])
print(f"wall time: {time.time()-t0:.4f}s")

print("\n=== WITHOUT index (rejected alternative: forced seq scan) ===")
cur.execute("SET enable_seqscan = on;")
cur.execute("SET enable_indexscan = off;")
cur.execute("SET enable_bitmapscan = off;")
t0 = time.time()
cur.execute("EXPLAIN ANALYZE " + query, (TARGET, TARGET))
for row in cur.fetchall():
    print(row[0])
print(f"wall time: {time.time()-t0:.4f}s")

cur.close()
conn.close()