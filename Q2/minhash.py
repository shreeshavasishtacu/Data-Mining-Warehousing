import csv, glob, re, random, os, time, statistics as st
from collections import Counter, defaultdict

def tokenize(text): return re.findall(r"[a-z0-9]+", text.lower())

def shingles(text, k=5):
    t = tokenize(text)
    return set(" ".join(t[i:i+k]) for i in range(len(t)-k+1)) if len(t) >= k else set()

def jaccard(a, b): return len(a & b) / len(a | b) if a and b else 0.0

def load_notices(pattern=r"C:\Users\shree\Desktop\data_2\data_2\notices\part-*.csv"):
    notices = {}
    files = glob.glob(pattern)
    print(f"Pattern matched {len(files)} files: {files}")
    for f in files:
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

def minhash_jaccard_est(sig_a, sig_b):
    return sum(1 for x, y in zip(sig_a, sig_b) if x == y) / M

BANDS, ROWS = 64, 2  # b*r must equal M=128

def survives(sig_a, sig_b, bands=BANDS, rows=ROWS):
    for band in range(bands):
        if tuple(sig_a[band*rows:(band+1)*rows]) == tuple(sig_b[band*rows:(band+1)*rows]):
            return True
    return False

def build_candidate_pairs(sig_cache, bands=BANDS, rows=ROWS):
    buckets = defaultdict(list)
    for nid, s in sig_cache.items():
        for band in range(bands):
            key = (band, tuple(s[band*rows:(band+1)*rows]))
            buckets[key].append(nid)
    cand_pairs = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort()
        for i in range(len(members)):
            for j in range(i+1, len(members)):
                cand_pairs.add((members[i], members[j]))
    return cand_pairs

if __name__ == "__main__":
    notices = load_notices()
    print(f"Loaded {len(notices)} notices.")

    df = Counter()
    doc_sh = {}
    for nid, row in notices.items():
        s = shingles(row["body"])
        doc_sh[nid] = s
        for sh in s:
            df[sh] += 1

    N = len(notices)
    thr = 0.01 * N
    doc_filt = {nid: {sh for sh in s if df[sh] < thr} for nid, s in doc_sh.items()}
    sig_cache = {nid: minhash_sig(s) for nid, s in doc_filt.items()}

    # --- Part B: estimator error on labeled pairs ---
    errors, same_est, diff_est = [], [], []
    with open(r"C:\Users\shree\Desktop\data_2\data_2\labelled_pairs.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a, b, label = row["notice_id_a"], row["notice_id_b"], row["label"]
            if a not in doc_filt or b not in doc_filt:
                continue
            exact = jaccard(doc_filt[a], doc_filt[b])
            est = minhash_jaccard_est(sig_cache[a], sig_cache[b])
            errors.append(abs(exact - est))
            (same_est if label == "same" else diff_est).append(est)

    print(f"\n--- Part B ---")
    print(f"pairs evaluated: {len(errors)}")
    print(f"mean abs error: {st.mean(errors):.4f}  max abs error: {max(errors):.4f}  stdev: {st.stdev(errors):.4f}")

    all_est = sorted(set(same_est + diff_est))
    best_acc, best_t = 0, 0
    for t in all_est:
        tp = sum(1 for s in same_est if s >= t)
        tn = sum(1 for s in diff_est if s < t)
        acc = (tp + tn) / (len(same_est) + len(diff_est))
        if acc > best_acc:
            best_acc, best_t = acc, t
    print(f"best threshold(estimated)={best_t:.4f}  accuracy(estimated)={best_acc:.4f}")

    # --- Part C: survival probability by true similarity ---
    bins = [(0.0,0.05),(0.05,0.15),(0.15,0.25),(0.25,0.4),(0.4,0.6),(0.6,0.8),(0.8,1.01)]
    pairs_with_j = []
    with open(r"C:\Users\shree\Desktop\data_2\data_2\labelled_pairs.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a, b, label = row["notice_id_a"], row["notice_id_b"], row["label"]
            if a not in doc_filt or b not in doc_filt:
                continue
            j = jaccard(doc_filt[a], doc_filt[b])
            pairs_with_j.append((a, b, label, j))

    print("\n--- Part C: survival probability by true similarity ---")
    for lo, hi in bins:
        subset = [(a,b,l,j) for a,b,l,j in pairs_with_j if lo <= j < hi]
        if not subset:
            continue
        surv = sum(1 for a,b,l,j in subset if survives(sig_cache[a], sig_cache[b]))
        print(f"  J in [{lo:.2f},{hi:.2f}): n={len(subset):3d}  survival={surv/len(subset):.3f}")

    # --- Part C: candidate volume on full corpus ---
    t0 = time.time()
    cand_pairs = build_candidate_pairs(sig_cache)
    t1 = time.time()
    n = len(sig_cache)
    print(f"\nbrute-force pairs: {n*(n-1)//2:,}")
    print(f"candidate pairs: {len(cand_pairs):,}")
    print(f"reduction: {(n*(n-1)//2)/len(cand_pairs):.0f}x")
    print(f"LSH build time: {t1-t0:.2f}s")