from pathlib import Path
import csv
import statistics
import time
import psycopg2


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

# Your actual file is spelled "labelled"
LABEL_FILE = BASE_DIR / "labelled_pairs.csv"

REPORT_FILE = BASE_DIR / "Q2_E_REPORT.txt"

DB = {
    "host": "localhost",
    "port": 5434,
    "dbname": "setubid",
    "user": "setubid",
    "password": "setubid",
}

# Frequency thresholds for the mitigation experiment.
# A band occurring in more than this many notices is ignored.
THRESHOLDS = [1000, 500, 250, 150, 100, 75, 50, 25, 10]


# ============================================================
# SMALL HELPERS
# ============================================================

def percentile(values, p):
    if not values:
        return 0.0

    values = sorted(values)

    position = (len(values) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(values))

    if lower == upper:
        return float(values[lower])

    fraction = position - lower

    return (
        values[lower]
        + (values[upper] - values[lower]) * fraction
    )


def fmt_number(value):
    return f"{int(value):,}"


# ============================================================
# CHECK INPUTS
# ============================================================

def check_inputs():
    if not LABEL_FILE.exists():
        raise FileNotFoundError(
            f"\nCould not find:\n{LABEL_FILE}\n\n"
            f"Expected:\n{BASE_DIR / 'labelled_pairs.csv'}"
        )

    print("=" * 70)
    print("Q2 PART E")
    print("=" * 70)
    print(f"Project directory : {BASE_DIR}")
    print(f"Label file        : {LABEL_FILE}")
    print()


# ============================================================
# LOAD LABELLED PAIRS
# ============================================================

def find_column(columns, candidates):
    lower_map = {
        c.strip().lower(): c
        for c in columns
    }

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]

    return None


def load_labels():
    with open(
        LABEL_FILE,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise RuntimeError(
                "labelled_pairs.csv has no header."
            )

        columns = reader.fieldnames

        print("Labelled-pair columns:", columns)

        a_col = find_column(
            columns,
            [
                "notice_id_a",
                "notice_a",
                "id_a",
                "notice1",
                "notice_id_1",
                "a",
            ],
        )

        b_col = find_column(
            columns,
            [
                "notice_id_b",
                "notice_b",
                "id_b",
                "notice2",
                "notice_id_2",
                "b",
            ],
        )

        label_col = find_column(
            columns,
            [
                "label",
                "same",
                "match",
                "is_same",
                "duplicate",
                "y",
            ],
        )

        if not a_col or not b_col or not label_col:
            raise RuntimeError(
                "\nCould not identify labelled-pair columns.\n"
                f"Columns found: {columns}\n"
                f"Detected A: {a_col}\n"
                f"Detected B: {b_col}\n"
                f"Detected label: {label_col}"
            )

        labels = []

        for row in reader:
            raw = str(row[label_col]).strip().lower()

            if raw in {
                "same",
                "1",
                "true",
                "yes",
                "duplicate",
                "match",
            }:
                same = True

            elif raw in {
                "different",
                "0",
                "false",
                "no",
                "nonduplicate",
                "non-match",
            }:
                same = False

            else:
                continue

            labels.append(
                (
                    row[a_col].strip(),
                    row[b_col].strip(),
                    same,
                )
            )

    if not labels:
        raise RuntimeError(
            "No usable labelled pairs were found."
        )

    print(f"Loaded {len(labels)} labelled pairs.")

    same_count = sum(
        1 for _, _, same in labels if same
    )

    different_count = len(labels) - same_count

    print(f"SAME      : {same_count}")
    print(f"DIFFERENT : {different_count}")
    print()

    return labels


# ============================================================
# DATABASE CHECK
# ============================================================

def check_database(cur):
    print("Checking PostgreSQL schema...")

    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)

    tables = [r[0] for r in cur.fetchall()]

    print("Tables:", ", ".join(tables))

    required = {
        "notices",
        "minhash_bands",
    }

    missing = required - set(tables)

    if missing:
        raise RuntimeError(
            "Required PostgreSQL tables are missing: "
            + ", ".join(sorted(missing))
        )

    cur.execute("""
        SELECT COUNT(*)
        FROM notices
    """)

    notice_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM minhash_bands
    """)

    band_count = cur.fetchone()[0]

    print(f"Notices       : {notice_count:,}")
    print(f"MinHash bands : {band_count:,}")

    print()

    return notice_count, band_count


# ============================================================
# BAND FREQUENCY TABLE
# ============================================================

def create_frequency_table(cur):
    print("Building temporary band-frequency table...")

    cur.execute("""
        DROP TABLE IF EXISTS tmp_band_frequency
    """)

    cur.execute("""
        CREATE TEMP TABLE tmp_band_frequency AS
        SELECT
            band_no,
            band_hash,
            COUNT(DISTINCT notice_id)::bigint AS document_frequency
        FROM minhash_bands
        GROUP BY
            band_no,
            band_hash
    """)

    cur.execute("""
        CREATE INDEX tmp_band_frequency_idx
        ON tmp_band_frequency (
            band_no,
            band_hash
        )
    """)

    cur.execute("""
        SELECT
            COUNT(*),
            MAX(document_frequency)
        FROM tmp_band_frequency
    """)

    band_count, max_frequency = cur.fetchone()

    print(
        f"Unique bands: {band_count:,}"
    )

    print(
        f"Maximum band document frequency: "
        f"{max_frequency:,}"
    )

    print()

    return band_count, max_frequency


# ============================================================
# BAND FREQUENCY HOTSPOTS
# ============================================================

def get_top_bands(cur, limit=20):
    cur.execute("""
        SELECT
            band_no,
            band_hash,
            document_frequency
        FROM tmp_band_frequency
        ORDER BY document_frequency DESC
        LIMIT %s
    """, (limit,))

    return cur.fetchall()


# ============================================================
# CANDIDATE WORK DISTRIBUTION
#
# This measures the actual amount of candidate work generated
# by LSH band collisions.
#
# For every notice:
#
#     sum(document_frequency - 1)
#
# across its bands.
#
# This intentionally measures work before duplicate candidate
# IDs are collapsed, because E asks where the retrieval work
# is being spent.
# ============================================================

def workload_distribution(cur, threshold=None):
    if threshold is None:

        sql = """
            SELECT
                b.notice_id,
                COALESCE(
                    SUM(
                        f.document_frequency - 1
                    ),
                    0
                )::bigint AS candidate_work
            FROM minhash_bands b
            JOIN tmp_band_frequency f
              ON f.band_no = b.band_no
             AND f.band_hash = b.band_hash
            GROUP BY b.notice_id
        """

        cur.execute(sql)

    else:

        sql = """
            SELECT
                b.notice_id,
                COALESCE(
                    SUM(
                        f.document_frequency - 1
                    ),
                    0
                )::bigint AS candidate_work
            FROM minhash_bands b
            JOIN tmp_band_frequency f
              ON f.band_no = b.band_no
             AND f.band_hash = b.band_hash
            WHERE f.document_frequency <= %s
            GROUP BY b.notice_id
        """

        cur.execute(sql, (threshold,))

    return dict(cur.fetchall())


def workload_stats(distribution):
    values = list(distribution.values())

    if not values:
        return {
            "notices": 0,
            "total": 0,
            "mean": 0,
            "median": 0,
            "p95": 0,
            "p99": 0,
            "max": 0,
        }

    return {
        "notices": len(values),
        "total": sum(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


# ============================================================
# TOP NOTICE HOTSPOTS
# ============================================================

def get_notice_hotspots(
    cur,
    distribution,
    limit=20
):
    if not distribution:
        return []

    top_ids = sorted(
        distribution,
        key=distribution.get,
        reverse=True
    )[:limit]

    cur.execute("""
        SELECT
            notice_id,
            portal_id
        FROM notices
        WHERE notice_id = ANY(%s)
    """, (top_ids,))

    portal_map = {
        notice_id: portal_id
        for notice_id, portal_id in cur.fetchall()
    }

    result = []

    for notice_id in top_ids:
        result.append(
            (
                notice_id,
                portal_map.get(
                    notice_id,
                    "UNKNOWN"
                ),
                distribution[notice_id],
            )
        )

    return result


# ============================================================
# PORTAL WORK DISTRIBUTION
# ============================================================

def portal_work_distribution(
    cur,
    distribution
):
    if not distribution:
        return []

    items = list(distribution.items())

    cur.execute("""
        SELECT
            notice_id,
            portal_id
        FROM notices
        WHERE notice_id = ANY(%s)
    """, (
        [x[0] for x in items],
    ))

    portal_map = {
        notice_id: portal_id
        for notice_id, portal_id in cur.fetchall()
    }

    totals = {}

    for notice_id, work in items:

        portal = portal_map.get(
            notice_id,
            "UNKNOWN"
        )

        if portal not in totals:
            totals[portal] = {
                "notices": 0,
                "work": 0,
            }

        totals[portal]["notices"] += 1
        totals[portal]["work"] += work

    total_work = sum(
        x["work"]
        for x in totals.values()
    )

    result = []

    for portal, data in totals.items():

        percentage = (
            100.0 * data["work"] / total_work
            if total_work
            else 0
        )

        result.append(
            (
                portal,
                data["notices"],
                data["work"],
                percentage,
            )
        )

    result.sort(
        key=lambda x: x[2],
        reverse=True
    )

    return result


# ============================================================
# LABELLED-PAIR RETRIEVAL
# ============================================================

def pair_survives(
    cur,
    a,
    b,
    threshold=None
):
    if threshold is None:

        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM minhash_bands x
                JOIN minhash_bands y
                  ON x.band_no = y.band_no
                 AND x.band_hash = y.band_hash
                WHERE x.notice_id = %s
                  AND y.notice_id = %s
            )
        """, (a, b))

    else:

        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM minhash_bands x
                JOIN tmp_band_frequency f
                  ON f.band_no = x.band_no
                 AND f.band_hash = x.band_hash
                JOIN minhash_bands y
                  ON y.band_no = x.band_no
                 AND y.band_hash = x.band_hash
                WHERE x.notice_id = %s
                  AND y.notice_id = %s
                  AND f.document_frequency <= %s
            )
        """, (
            a,
            b,
            threshold,
        ))

    return bool(cur.fetchone()[0])


def labelled_quality(
    cur,
    labels,
    threshold=None
):
    same_total = 0
    same_survived = 0

    different_total = 0
    different_survived = 0

    for a, b, same in labels:

        survives = pair_survives(
            cur,
            a,
            b,
            threshold
        )

        if same:

            same_total += 1

            if survives:
                same_survived += 1

        else:

            different_total += 1

            if survives:
                different_survived += 1

    same_recall = (
        same_survived / same_total
        if same_total
        else 0
    )

    different_candidate_rate = (
        different_survived / different_total
        if different_total
        else 0
    )

    return {
        "same_total": same_total,
        "same_survived": same_survived,
        "same_recall": same_recall,
        "different_total": different_total,
        "different_survived": different_survived,
        "different_candidate_rate":
            different_candidate_rate,
    }


# ============================================================
# REPORT WRITER
# ============================================================

def main():

    check_inputs()

    labels = load_labels()

    print(
        f"Connecting to PostgreSQL "
        f"localhost:{DB['port']}..."
    )

    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    print("Connected.")
    print()

    notice_count, band_count = check_database(cur)

    create_frequency_table(cur)

    report = []

    report.append(
        "QUESTION 2 - PART E"
    )
    report.append(
        "RETRIEVAL WORKLOAD SKEW AND MITIGATION"
    )
    report.append("=" * 70)
    report.append("")

    report.append(
        f"Corpus notices: {notice_count:,}"
    )

    report.append(
        f"MinHash band rows: {band_count:,}"
    )

    report.append(
        f"Labelled pairs: {len(labels):,}"
    )

    report.append(
        f"Labelled SAME pairs: "
        f"{sum(1 for x in labels if x[2]):,}"
    )

    report.append(
        f"Labelled DIFFERENT pairs: "
        f"{sum(1 for x in labels if not x[2]):,}"
    )

    report.append("")

    # ========================================================
    # BASELINE
    # ========================================================

    print("=" * 70)
    print("BASELINE FULL-CORPUS WORKLOAD")
    print("=" * 70)

    start = time.perf_counter()

    baseline_distribution = workload_distribution(
        cur
    )

    baseline_runtime = (
        time.perf_counter() - start
    )

    baseline = workload_stats(
        baseline_distribution
    )

    print(
        f"Runtime: {baseline_runtime:.4f}s"
    )

    print(
        f"Candidate work: "
        f"{baseline['total']:,}"
    )

    print(
        f"Median: "
        f"{baseline['median']:.0f}"
    )

    print(
        f"P95: "
        f"{baseline['p95']:.0f}"
    )

    print(
        f"P99: "
        f"{baseline['p99']:.0f}"
    )

    print(
        f"Maximum: "
        f"{baseline['max']:,}"
    )

    print()

    report.append(
        "A. BASELINE"
    )
    report.append("-" * 70)

    report.append(
        f"Runtime: {baseline_runtime:.4f} seconds"
    )

    report.append(
        f"Notices measured: "
        f"{baseline['notices']:,}"
    )

    report.append(
        f"Total candidate work: "
        f"{baseline['total']:,}"
    )

    report.append(
        f"Mean candidate work/notice: "
        f"{baseline['mean']:.2f}"
    )

    report.append(
        f"Median: {baseline['median']:.2f}"
    )

    report.append(
        f"P95: {baseline['p95']:.2f}"
    )

    report.append(
        f"P99: {baseline['p99']:.2f}"
    )

    report.append(
        f"Maximum: {baseline['max']:,}"
    )

    report.append("")

    # ========================================================
    # TOP HOTSPOTS
    # ========================================================

    hotspots = get_notice_hotspots(
        cur,
        baseline_distribution,
        20
    )

    report.append(
        "B. TOP NOTICE HOTSPOTS"
    )
    report.append("-" * 70)

    report.append(
        "notice_id\tportal_id\tcandidate_work"
    )

    for notice, portal, work in hotspots:

        report.append(
            f"{notice}\t{portal}\t{work:,}"
        )

    report.append("")

    # ========================================================
    # PORTAL DISTRIBUTION
    # ========================================================

    portal_rows = portal_work_distribution(
        cur,
        baseline_distribution
    )

    report.append(
        "C. PORTAL CONTRIBUTION TO WORK"
    )
    report.append("-" * 70)

    report.append(
        "portal\tnotices\tcandidate_work\tpercent"
    )

    for portal, notices, work, percentage in (
        portal_rows[:20]
    ):

        report.append(
            f"{portal}\t"
            f"{notices:,}\t"
            f"{work:,}\t"
            f"{percentage:.2f}%"
        )

    report.append("")

    # ========================================================
    # MOST COMMON BANDS
    # ========================================================

    top_bands = get_top_bands(
        cur,
        20
    )

    report.append(
        "D. MOST FREQUENT MINHASH BANDS"
    )
    report.append("-" * 70)

    report.append(
        "band_no\tband_hash\tdocument_frequency"
    )

    for band_no, band_hash, frequency in top_bands:

        report.append(
            f"{band_no}\t"
            f"{band_hash}\t"
            f"{frequency:,}"
        )

    report.append("")

    # ========================================================
    # BASELINE LABEL QUALITY
    # ========================================================

    print(
        "Measuring labelled-pair baseline..."
    )

    baseline_quality = labelled_quality(
        cur,
        labels
    )

    print(
        f"SAME recall: "
        f"{baseline_quality['same_recall']:.4f}"
    )

    print()

    report.append(
        "E. BASELINE LABELLED-PAIR RETRIEVAL"
    )
    report.append("-" * 70)

    report.append(
        f"SAME pairs survived: "
        f"{baseline_quality['same_survived']}/"
        f"{baseline_quality['same_total']}"
    )

    report.append(
        f"SAME recall: "
        f"{baseline_quality['same_recall']:.4f}"
    )

    report.append(
        f"DIFFERENT pairs entering candidates: "
        f"{baseline_quality['different_survived']}/"
        f"{baseline_quality['different_total']}"
    )

    report.append(
        f"DIFFERENT candidate rate: "
        f"{baseline_quality['different_candidate_rate']:.4f}"
    )

    report.append("")

    # ========================================================
    # MITIGATION TESTS
    # ========================================================

    print("=" * 70)
    print("TESTING HIGH-FREQUENCY-BAND MITIGATION")
    print("=" * 70)

    report.append(
        "F. MITIGATION TESTS"
    )
    report.append("-" * 70)

    report.append(
        "Mitigation: ignore MinHash bands whose "
        "document frequency exceeds the threshold."
    )

    report.append("")

    tested = []

    for threshold in THRESHOLDS:

        print(
            f"Testing threshold "
            f"{threshold}..."
        )

        start = time.perf_counter()

        distribution = workload_distribution(
            cur,
            threshold
        )

        runtime = (
            time.perf_counter() - start
        )

        stats = workload_stats(
            distribution
        )

        quality = labelled_quality(
            cur,
            labels,
            threshold
        )

        tested.append(
            {
                "threshold": threshold,
                "runtime": runtime,
                "stats": stats,
                "quality": quality,
                "distribution": distribution,
            }
        )

        report.append(
            f"threshold={threshold} | "
            f"runtime={runtime:.4f}s | "
            f"work={stats['total']:,} | "
            f"median={stats['median']:.0f} | "
            f"p95={stats['p95']:.0f} | "
            f"p99={stats['p99']:.0f} | "
            f"max={stats['max']:,} | "
            f"SAME_recall="
            f"{quality['same_recall']:.4f}"
        )

    report.append("")

    # ========================================================
    # CHOOSE MITIGATION
    #
    # We want the least aggressive mitigation that preserves
    # all labelled SAME pairs.
    # ========================================================

    acceptable = [
        x for x in tested
        if (
            x["quality"]["same_survived"]
            ==
            x["quality"]["same_total"]
        )
    ]

    if acceptable:

        # Largest threshold = least aggressive filtering.
        chosen = max(
            acceptable,
            key=lambda x: x["threshold"]
        )

        selection_reason = (
            "Least aggressive tested threshold "
            "that preserves all labelled SAME pairs."
        )

    else:

        # If none preserves all, select maximum recall,
        # then minimum work.
        chosen = max(
            tested,
            key=lambda x: (
                x["quality"]["same_recall"],
                -x["stats"]["total"],
            )
        )

        selection_reason = (
            "No tested threshold preserved every "
            "labelled SAME pair; selected the threshold "
            "with the highest measured SAME recall and "
            "then lowest candidate work."
        )

    threshold = chosen["threshold"]

    after_runtime = chosen["runtime"]
    after = chosen["stats"]
    after_quality = chosen["quality"]
    after_distribution = chosen["distribution"]

    reduction = (
        100.0
        *
        (
            1.0
            -
            after["total"]
            /
            baseline["total"]
        )
        if baseline["total"]
        else 0
    )

    quality_change = (
        after_quality["same_recall"]
        -
        baseline_quality["same_recall"]
    )

    # ========================================================
    # AFTER HOTSPOTS
    # ========================================================

    after_hotspots = get_notice_hotspots(
        cur,
        after_distribution,
        20
    )

    # ========================================================
    # REPORT
    # ========================================================

    report.append(
        "G. CHOSEN MITIGATION"
    )
    report.append("-" * 70)

    report.append(
        f"Maximum allowed band document frequency: "
        f"{threshold}"
    )

    report.append(
        selection_reason
    )

    report.append("")

    report.append(
        "H. AFTER MITIGATION"
    )
    report.append("-" * 70)

    report.append(
        f"Runtime: {after_runtime:.4f} seconds"
    )

    report.append(
        f"Total candidate work: "
        f"{after['total']:,}"
    )

    report.append(
        f"Mean candidate work/notice: "
        f"{after['mean']:.2f}"
    )

    report.append(
        f"Median: {after['median']:.2f}"
    )

    report.append(
        f"P95: {after['p95']:.2f}"
    )

    report.append(
        f"P99: {after['p99']:.2f}"
    )

    report.append(
        f"Maximum: {after['max']:,}"
    )

    report.append("")

    report.append(
        f"Candidate-work reduction: "
        f"{reduction:.2f}%"
    )

    report.append("")

    report.append(
        "I. RETRIEVAL QUALITY COST"
    )
    report.append("-" * 70)

    report.append(
        f"SAME recall before: "
        f"{baseline_quality['same_recall']:.4f}"
    )

    report.append(
        f"SAME recall after: "
        f"{after_quality['same_recall']:.4f}"
    )

    report.append(
        f"Change in SAME recall: "
        f"{quality_change:+.4f}"
    )

    report.append(
        f"SAME pairs before: "
        f"{baseline_quality['same_survived']}/"
        f"{baseline_quality['same_total']}"
    )

    report.append(
        f"SAME pairs after: "
        f"{after_quality['same_survived']}/"
        f"{after_quality['same_total']}"
    )

    report.append("")

    report.append(
        "J. DIFFERENT-PAIR EFFECT"
    )
    report.append("-" * 70)

    report.append(
        f"DIFFERENT candidate rate before: "
        f"{baseline_quality['different_candidate_rate']:.4f}"
    )

    report.append(
        f"DIFFERENT candidate rate after: "
        f"{after_quality['different_candidate_rate']:.4f}"
    )

    report.append("")

    report.append(
        "K. TOP HOTSPOTS AFTER MITIGATION"
    )
    report.append("-" * 70)

    report.append(
        "notice_id\tportal_id\tcandidate_work"
    )

    for notice, portal, work in after_hotspots:

        report.append(
            f"{notice}\t{portal}\t{work:,}"
        )

    report.append("")

    # ========================================================
    # BUDGET
    # ========================================================

    budget_seconds = 20 * 60

    report.append(
        "L. 20-MINUTE NIGHTLY BUDGET"
    )
    report.append("-" * 70)

    report.append(
        f"Budget: {budget_seconds} seconds"
    )

    report.append(
        f"Measured baseline retrieval: "
        f"{baseline_runtime:.4f} seconds"
    )

    report.append(
        f"Measured mitigated retrieval: "
        f"{after_runtime:.4f} seconds"
    )

    report.append(
        f"Baseline within budget: "
        f"{baseline_runtime <= budget_seconds}"
    )

    report.append(
        f"Mitigated within budget: "
        f"{after_runtime <= budget_seconds}"
    )

    report.append("")

    # ========================================================
    # MECHANICAL EXPLANATION
    # ========================================================

    report.append(
        "M. MECHANICAL EXPLANATION"
    )
    report.append("-" * 70)

    report.append(
        "The retrieval structure groups notices through shared "
        "MinHash bands. A band appearing in many notices produces "
        "a large candidate bucket. Every notice containing that "
        "band therefore inherits candidate-generation work from "
        "the frequency of that band."
    )

    report.append(
        "The portal_profiles.md notes explain why this corpus can "
        "produce this skew. P001-P006 are nodal aggregation services "
        "and repeatedly paste approximately 1,400 characters of "
        "legal preamble into notices. P001, P002 and P005 also append "
        "a disclaimer footer. Short notices can therefore consist "
        "mostly of repeated portal boilerplate."
    )

    report.append(
        "Repeated boilerplate creates repeated text shingles. "
        "Those repeated shingles can generate common MinHash bands, "
        "which creates high-document-frequency buckets and therefore "
        "a disproportionate amount of candidate-generation work."
    )

    report.append(
        "The mitigation removes only bands whose document frequency "
        "exceeds the measured threshold. Less frequent bands remain "
        "available to retrieve genuinely similar notices."
    )

    report.append(
        "The threshold was selected from measurements on the supplied "
        "labelled pairs rather than from an arbitrary tutorial value. "
        "Its retrieval-quality cost is reported using the same "
        "labelled-pair set."
    )

    report.append("")

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    report.append(
        "N. SUBMISSION SUMMARY"
    )
    report.append("-" * 70)

    report.append(
        f"Baseline work: "
        f"{baseline['total']:,}"
    )

    report.append(
        f"Baseline P99: "
        f"{baseline['p99']:.0f}"
    )

    report.append(
        f"Baseline maximum: "
        f"{baseline['max']:,}"
    )

    report.append(
        f"Chosen frequency threshold: "
        f"{threshold}"
    )

    report.append(
        f"Mitigated work: "
        f"{after['total']:,}"
    )

    report.append(
        f"Work reduction: "
        f"{reduction:.2f}%"
    )

    report.append(
        f"SAME recall before: "
        f"{baseline_quality['same_recall']:.4f}"
    )

    report.append(
        f"SAME recall after: "
        f"{after_quality['same_recall']:.4f}"
    )

    report.append(
        f"Quality change: "
        f"{quality_change:+.4f}"
    )

    report.append("")

    # ========================================================
    # WRITE REPORT
    # ========================================================

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    # ========================================================
    # TERMINAL OUTPUT
    # ========================================================

    print()
    print("=" * 70)
    print("Q2 PART E COMPLETE")
    print("=" * 70)

    print()
    print("BASELINE")
    print(
        f"  Runtime          : "
        f"{baseline_runtime:.4f}s"
    )
    print(
        f"  Candidate work   : "
        f"{baseline['total']:,}"
    )
    print(
        f"  Median           : "
        f"{baseline['median']:.0f}"
    )
    print(
        f"  P95              : "
        f"{baseline['p95']:.0f}"
    )
    print(
        f"  P99              : "
        f"{baseline['p99']:.0f}"
    )
    print(
        f"  Maximum          : "
        f"{baseline['max']:,}"
    )

    print()
    print("MITIGATION")
    print(
        f"  Threshold        : "
        f"{threshold}"
    )
    print(
        f"  Runtime          : "
        f"{after_runtime:.4f}s"
    )
    print(
        f"  Candidate work   : "
        f"{after['total']:,}"
    )
    print(
        f"  Work reduction   : "
        f"{reduction:.2f}%"
    )

    print()
    print("LABELLED QUALITY")
    print(
        f"  SAME before      : "
        f"{baseline_quality['same_recall']:.4f}"
    )
    print(
        f"  SAME after       : "
        f"{after_quality['same_recall']:.4f}"
    )
    print(
        f"  Quality change   : "
        f"{quality_change:+.4f}"
    )

    print()
    print("BUDGET")
    print(
        f"  20-minute limit  : "
        f"{budget_seconds}s"
    )
    print(
        f"  Baseline fits    : "
        f"{baseline_runtime <= budget_seconds}"
    )
    print(
        f"  Mitigated fits   : "
        f"{after_runtime <= budget_seconds}"
    )

    print()
    print(
        f"Full report: {REPORT_FILE}"
    )

    print("=" * 70)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()