import csv, glob, re, random, hashlib, os, time
import psycopg2

def tokenize(text): return re.findall(r"[a-z0-9]+", text.lower())
def shingles(text, k=5):
    t = tokenize(text)
    return set(" ".join(t[i:i+k]) for i in range(len(t)-k+1)) if len(t) >= k else set()

def load_notices(pattern=r"C:\Users\shree\Desktop\data_2\data_2\notices\part-*.csv"):
    notices = {}
    for f in glob.glob(pattern):
        if not os.path.isfile(f):
            continue
        with open(f, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                notices[row["notice_id"]] = row
    return notices

M = 128
P = (1 << 61) - 1
random.seed(42)
hash_params = [(random.randint(1, P-1), random.randint(0, P-1)) for _ in range(M)]

def minhash_sig(shingle_set):
    if not shingle_set:
        return [P] * M
    hs = [hash(s) & ((1 << 61) - 1) for s in shingle_set]
    return [min((a*h + b) % P for h in hs) for a, b in hash_params]

BANDS, ROWS = 64, 2

def combine_band(values):
    h = hashlib.md5(",".join(map(str, values)).encode()).digest()
    return int.from_bytes(h[:8], byteorder="big", signed=True)

conn = psycopg2.connect(host="localhost", port=5434, dbname="setubid", user="setubid", password="setubid")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS notices (
    notice_id TEXT PRIMARY KEY,
    portal_id TEXT,
    published_at TIMESTAMP,
    title TEXT,
    estimated_value NUMERIC,
    closing_date DATE
);
CREATE TABLE IF NOT EXISTS minhash_bands (
    notice_id TEXT NOT NULL REFERENCES notices(notice_id),
    band_no SMALLINT NOT NULL,
    band_hash BIGINT NOT NULL,
    PRIMARY KEY (notice_id, band_no)
);
""")
conn.commit()

notices = load_notices()
print(f"Loaded {len(notices)} notices from files.")

df = {}
doc_sh = {}
from collections import Counter
dfc = Counter()
for nid, row in notices.items():
    s = shingles(row["body"])
    doc_sh[nid] = s
    for sh in s:
        dfc[sh] += 1
N = len(notices)
thr = 0.01 * N
doc_filt = {nid: {sh for sh in s if dfc[sh] < thr} for nid, s in doc_sh.items()}

for nid, row in notices.items():
    cur.execute(
        "INSERT INTO notices (notice_id, portal_id, published_at, title, estimated_value, closing_date) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (notice_id) DO NOTHING",
        (nid, row.get("portal_id"), row.get("published_at") or None, row.get("title"),
         row.get("estimated_value") or None, row.get("closing_date") or None)
    )
conn.commit()
print("Notices inserted.")

band_rows = []
for nid, s in doc_filt.items():
    sig = minhash_sig(s)
    for band in range(BANDS):
        chunk = sig[band*ROWS:(band+1)*ROWS]
        band_rows.append((nid, band, combine_band(chunk)))

cur.executemany(
    "INSERT INTO minhash_bands (notice_id, band_no, band_hash) VALUES (%s,%s,%s) "
    "ON CONFLICT (notice_id, band_no) DO NOTHING",
    band_rows
)
conn.commit()
print(f"Inserted {len(band_rows)} band rows.")

cur.execute("CREATE INDEX IF NOT EXISTS idx_band_lookup ON minhash_bands (band_no, band_hash);")
conn.commit()
print("Index created.")

cur.close()
conn.close()