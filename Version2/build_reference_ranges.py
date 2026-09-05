import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

# Paths are anchored to this script's own folder, so the pipeline runs correctly
# whatever the current working directory is. Version2 outputs live beside this
# script; the large shared inputs stay in the project root, one level up.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DB_PATH = ROOT / "metabolite_atlas.db"

SCHEMA = """
DROP TABLE IF EXISTS reference_ranges;
CREATE TABLE reference_ranges (
    hmdb_id          TEXT NOT NULL REFERENCES metabolites(hmdb_id),
    metabolite_name  TEXT NOT NULL,
    biospecimen      TEXT NOT NULL,
    unit             TEXT NOT NULL,
    n_measurements   INTEGER NOT NULL,
    n_studies        INTEGER NOT NULL,
    value_min        REAL,
    q1               REAL,
    median           REAL,
    q3               REAL,
    value_max        REAL,
    mean             REAL,
    sd               REAL,
    PRIMARY KEY (hmdb_id, biospecimen)
);
CREATE INDEX idx_refranges_name       ON reference_ranges(metabolite_name);
CREATE INDEX idx_refranges_biospecimen ON reference_ranges(biospecimen);
"""


def quartile(sorted_values, fraction):
    """
    Linear-interpolated quantile, matching the common R type-7 definition.

    Written out rather than pulled from numpy so the pipeline stays
    standard-library only, and so the definition used is explicit in the report.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    rows = conn.execute(
        """SELECT hmdb_id, metabolite_name, biospecimen, unit,
                  value_representative, reference_id
             FROM comparable_measurements
            WHERE value_representative IS NOT NULL"""
    ).fetchall()

    grouped = defaultdict(lambda: {"values": [], "studies": set(), "unit": None,
                                   "name": None})
    for hmdb_id, name, biospecimen, unit, value, reference_id in rows:
        bucket = grouped[(hmdb_id, biospecimen)]
        bucket["values"].append(value)
        bucket["studies"].add(reference_id)
        bucket["unit"] = unit
        bucket["name"] = name

    records = []
    for (hmdb_id, biospecimen), bucket in grouped.items():
        values = sorted(bucket["values"])
        records.append((
            hmdb_id, bucket["name"], biospecimen, bucket["unit"],
            len(values),
            len({s for s in bucket["studies"] if s is not None}),
            values[0],
            quartile(values, 0.25),
            statistics.median(values),
            quartile(values, 0.75),
            values[-1],
            statistics.fmean(values),
            statistics.stdev(values) if len(values) > 1 else None,
        ))

    conn.executemany(
        """INSERT INTO reference_ranges
           (hmdb_id, metabolite_name, biospecimen, unit, n_measurements,
            n_studies, value_min, q1, median, q3, value_max, mean, sd)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        records,
    )
    conn.commit()

    print(f"Built {len(records):,} reference ranges "
          f"from {len(rows):,} comparable measurements\n")

    print("Coverage by biospecimen:")
    for biospecimen, n, mets in conn.execute(
        """SELECT biospecimen, SUM(n_measurements), COUNT(*)
             FROM reference_ranges GROUP BY 1 ORDER BY 2 DESC"""
    ):
        print(f"  {biospecimen:26} {n:6,} measurements  {mets:5,} metabolites")

    print("\nBest-supported ranges (most independent studies):")
    for name, biospecimen, n, studies, lo, med, hi, unit in conn.execute(
        """SELECT metabolite_name, biospecimen, n_measurements, n_studies,
                  value_min, median, value_max, unit
             FROM reference_ranges ORDER BY n_studies DESC, n_measurements DESC
            LIMIT 8"""
    ):
        print(f"  {name[:26]:26} {biospecimen:12} n={n:4,} ({studies:3,} studies)  "
              f"{lo:>10,.2f} - {hi:<12,.2f} median {med:,.2f} {unit}")

    conn.close()


if __name__ == "__main__":
    main()
