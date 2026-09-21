import csv, glob, re
from collections import Counter

def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())

def shingles(text, k=5):
    toks = tokenize(text)
    if len(toks) < k:
        return set()
    return set(" ".join(toks[i:i+k]) for i in range(len(toks)-k+1))

def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def load_notices(pattern=r"C:\Users\shree\Desktop\data_2\data_2\notices\part-*.csv"):
    notices = {}
    for f in glob.glob(pattern):
        with open(f, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                notices[row["notice_id"]] = row
    return notices

def build_df(notices):
    df = Counter()
    doc_sh = {}
    for nid, row in notices.items():
        s = shingles(row["body"])
        doc_sh[nid] = s
        for sh in s:
            df[sh] += 1
    return doc_sh, df

def filtered(s, df, thr):
    return {sh for sh in s if df[sh] < thr}

if __name__ == "__main__":
    notices = load_notices()
    print(f"Loaded {len(notices)} notices.")

    doc_sh, df = build_df(notices)
    N = len(notices)
    thr = 0.01 * N   # 1% of corpus

    pairs = [("N005451", "N005452", "same"),
             ("N004217", "N007965", "different")]

    for a, b, label in pairs:
        if a not in doc_sh or b not in doc_sh:
            print(f"  {a}/{b}: not found in loaded notices, skipping")
            continue
        sa, sb = doc_sh[a], doc_sh[b]
        naive = jaccard(sa, sb)
        filt = jaccard(filtered(sa, df, thr), filtered(sb, df, thr))
        print(f"{a}/{b} [{label}]  naive={naive:.4f}  filtered={filt:.4f}")