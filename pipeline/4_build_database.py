"""
Step 4 -- build the normalised SQLite database and the reference-range table.

Five related tables (metabolites, biospecimens, concentration_units,
references, measurements) plus reference_ranges: the summary statistics the
project exists to produce, one row per metabolite x biospecimen.

Method, and its limits -- state these in the report:
  Each measurement contributes one representative value: the mean as reported,
  or the midpoint of a reported range where no mean was given. Studies are
  pooled UNWEIGHTED, because HMDB does not record sample sizes, so a study of 8
  subjects counts the same as one of 800. The statistics therefore describe the
  spread of reported values across the literature, not a sample-weighted
  population distribution. One-sided detection limits ("<0.5") are retained in
  measurements but excluded from the statistics, since they give no point
  estimate.

Input:  data/hmdb_concentrations_parsed.csv
Output: data/metabolite_atlas.db

Usage:
    pip install pandas
    python pipeline/4_build_database.py
"""

import sqlite3
import pandas as pd
from pathlib import Path

# Paths are anchored to this script's own folder, so every step runs correctly
# from any working directory. Inputs and generated data live in data/, the
# website in explorer/.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
EXPLORER = ROOT / "explorer"

CSV_PATH = DATA / "hmdb_concentrations_parsed.csv"
DB_PATH = DATA / "metabolite_atlas.db"

SCHEMA = """
CREATE TABLE metabolites (
    hmdb_id         TEXT PRIMARY KEY,
    metabolite_name TEXT NOT NULL
);

CREATE TABLE biospecimens (
    biospecimen_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE
);

-- unit_class distinguishes the three kinds of measurement HMDB mixes together.
-- is_comparable = 1 marks the volumetric measurements that can be plotted on a
-- shared concentration axis; creatinine-normalised and fecal-mass rows are
-- retained but excluded from comparison.
CREATE TABLE concentration_units (
    unit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_name       TEXT NOT NULL UNIQUE,   -- as written in HMDB
    unit_std        TEXT NOT NULL,          -- display label (uM -> umol/L)
    unit_class      TEXT NOT NULL,          -- volumetric | mass_per_volume | creatinine_normalised
                                            -- | mass_normalised | unclassified
    is_comparable   INTEGER NOT NULL        -- 1 = may appear in concentration plots
);

CREATE TABLE "references" (
    reference_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pubmed_id       TEXT UNIQUE,
    reference_text  TEXT
);

CREATE TABLE measurements (
    measurement_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hmdb_id                 TEXT NOT NULL REFERENCES metabolites(hmdb_id),
    biospecimen_id          INTEGER NOT NULL REFERENCES biospecimens(biospecimen_id),
    unit_id                 INTEGER NOT NULL REFERENCES concentration_units(unit_id),

    -- the source string, kept verbatim so every number stays traceable
    concentration_value_raw TEXT NOT NULL,

    -- parsed numerics (any may be NULL depending on how the source reported it)
    value_mean              REAL,
    value_sd                REAL,
    value_min               REAL,
    value_max               REAL,
    value_bound_type        TEXT,     -- <, <=, >, >= for censored values
    value_representative    REAL,     -- one number per row, for plotting
    representative_source   TEXT,     -- reported_mean | range_midpoint

    -- parse provenance
    parse_pattern           TEXT NOT NULL,
    parse_ok                INTEGER NOT NULL,
    needs_review            INTEGER NOT NULL,
    parse_note              TEXT,

    subject_age             TEXT,
    subject_sex             TEXT,
    subject_condition       TEXT,
    reference_id            INTEGER REFERENCES "references"(reference_id)
);

CREATE INDEX idx_meas_hmdb        ON measurements(hmdb_id);
CREATE INDEX idx_meas_biospecimen ON measurements(biospecimen_id);
CREATE INDEX idx_meas_unit        ON measurements(unit_id);
CREATE INDEX idx_meas_parse_ok    ON measurements(parse_ok);
CREATE INDEX idx_met_name         ON metabolites(metabolite_name);

-- Everything the interface is allowed to plot: comparable units, successfully
-- parsed, with a usable numeric value.
CREATE VIEW v_comparable AS
SELECT
    ms.measurement_id,
    ms.hmdb_id,
    m.metabolite_name,
    b.name              AS biospecimen,
    u.unit_std          AS unit,
    ms.value_representative,
    ms.value_mean, ms.value_sd, ms.value_min, ms.value_max,
    ms.representative_source,
    ms.needs_review,
    ms.subject_age, ms.subject_sex, ms.subject_condition,
    ms.reference_id,
    ms.concentration_value_raw
FROM measurements ms
JOIN metabolites m         ON m.hmdb_id = ms.hmdb_id
JOIN biospecimens b        ON b.biospecimen_id = ms.biospecimen_id
JOIN concentration_units u ON u.unit_id = ms.unit_id
WHERE u.is_comparable = 1
  AND ms.parse_ok = 1
  AND ms.value_representative IS NOT NULL;

-- Audit view: what was set aside, and why. Useful for the report, and for
-- showing the exclusion in the interface rather than hiding it.
CREATE VIEW v_excluded AS
SELECT
    u.unit_std AS unit,
    u.unit_class,
    CASE
        WHEN u.is_comparable = 0 THEN 'non-comparable unit'
        WHEN ms.parse_ok = 0     THEN 'value could not be parsed'
        ELSE 'no numeric value'
    END AS reason,
    COUNT(*) AS n
FROM measurements ms
JOIN concentration_units u ON u.unit_id = ms.unit_id
WHERE u.is_comparable = 0 OR ms.parse_ok = 0 OR ms.value_representative IS NULL
GROUP BY 1, 2, 3;

-- Materialised summary statistics: one row per metabolite x biospecimen.
-- This is the "reference range" the project set out to produce.
CREATE TABLE reference_ranges (
    hmdb_id         TEXT NOT NULL REFERENCES metabolites(hmdb_id),
    metabolite_name TEXT NOT NULL,
    biospecimen     TEXT NOT NULL,
    unit            TEXT NOT NULL,
    n_measurements  INTEGER NOT NULL,
    n_references    INTEGER NOT NULL,
    mean            REAL,
    median          REAL,
    sd              REAL,
    p25             REAL,
    p75             REAL,
    range_low       REAL,
    range_high      REAL,
    n_needs_review  INTEGER NOT NULL,
    PRIMARY KEY (hmdb_id, biospecimen)
);

CREATE INDEX idx_rr_name        ON reference_ranges(metabolite_name);
CREATE INDEX idx_rr_biospecimen ON reference_ranges(biospecimen);
"""


def to_num(series):
    return pd.to_numeric(series, errors="coerce")


def main():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            "Couldn't find %s. Run 3_parse_concentrations.py first." % CSV_PATH
        )

    print("Reading %s ..." % CSV_PATH)
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False, na_values=[""])
    print("  %s rows" % format(len(df), ","))

    for col in ["value_mean", "value_sd", "value_min", "value_max",
                "value_representative"]:
        df[col] = to_num(df[col])
    for col in ["parse_ok", "needs_review", "is_comparable"]:
        df[col] = to_num(df[col]).fillna(0).astype(int)

    if DB_PATH.exists():
        # v2 is rebuilt from the CSV each run; v1 (metabolite_atlas.db) is
        # never touched.
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    # --- metabolites ---
    metabolites = df[["hmdb_id", "metabolite_name"]].drop_duplicates("hmdb_id")
    metabolites.to_sql("metabolites", conn, if_exists="append", index=False)
    print("  metabolites:         %s" % format(len(metabolites), ","))

    # --- biospecimens ---
    biospecimens = pd.DataFrame({"name": sorted(df["biospecimen"].dropna().unique())})
    biospecimens.to_sql("biospecimens", conn, if_exists="append", index=False)
    bio_map = dict(conn.execute("SELECT name, biospecimen_id FROM biospecimens").fetchall())
    print("  biospecimens:        %s" % format(len(biospecimens), ","))

    # --- units, carrying the agreed classification through from the parser ---
    units = (df[["concentration_units", "unit_std", "unit_class", "is_comparable"]]
             .dropna(subset=["concentration_units"])
             .drop_duplicates("concentration_units")
             .rename(columns={"concentration_units": "unit_name"})
             .sort_values("unit_name"))
    units.to_sql("concentration_units", conn, if_exists="append", index=False)
    unit_map = dict(conn.execute("SELECT unit_name, unit_id FROM concentration_units").fetchall())
    print("  concentration_units: %s" % format(len(units), ","))
    for r in conn.execute("SELECT unit_std, unit_class, is_comparable FROM concentration_units"):
        print("      %-22s %-22s comparable=%d" % r)

    # --- references ---
    refs = (df[["pubmed_ids", "reference_texts"]]
            .dropna(subset=["pubmed_ids"])
            .drop_duplicates("pubmed_ids")
            .rename(columns={"pubmed_ids": "pubmed_id",
                             "reference_texts": "reference_text"}))
    refs.to_sql("references", conn, if_exists="append", index=False)
    ref_map = dict(conn.execute('SELECT pubmed_id, reference_id FROM "references"').fetchall())
    print("  references:          %s" % format(len(refs), ","))

    # --- measurements ---
    measurements = pd.DataFrame({
        "hmdb_id": df["hmdb_id"],
        "biospecimen_id": df["biospecimen"].map(bio_map),
        "unit_id": df["concentration_units"].map(unit_map),
        "concentration_value_raw": df["concentration_value_raw"],
        "value_mean": df["value_mean"],
        "value_sd": df["value_sd"],
        "value_min": df["value_min"],
        "value_max": df["value_max"],
        "value_bound_type": df["value_bound_type"],
        "value_representative": df["value_representative"],
        "representative_source": df["representative_source"],
        "parse_pattern": df["parse_pattern"],
        "parse_ok": df["parse_ok"],
        "needs_review": df["needs_review"],
        "parse_note": df["parse_note"],
        "subject_age": df["subject_age"],
        "subject_sex": df["subject_sex"],
        "subject_condition": df["subject_condition"],
        "reference_id": df["pubmed_ids"].map(ref_map),
    })
    measurements.to_sql("measurements", conn, if_exists="append", index=False)
    print("  measurements:        %s" % format(len(measurements), ","))
    conn.commit()

    # --- reference ranges -------------------------------------------------
    # Computed in pandas because SQLite has no median or percentile function.
    #
    # Methodological note: summary statistics are computed over one
    # representative value per measurement (the reported mean, or the midpoint
    # of a reported range). Studies are NOT weighted by their sample size,
    # because HMDB does not record n for most entries. Censored values ("<0.5")
    # carry no representative value and are excluded from the statistics,
    # though they remain in the measurements table.
    comp = pd.read_sql_query("SELECT * FROM v_comparable", conn)
    print("\n  comparable, parsed, plottable: %s rows" % format(len(comp), ","))

    grouped = comp.groupby(["hmdb_id", "metabolite_name", "biospecimen", "unit"])
    rr = grouped.agg(
        n_measurements=("value_representative", "size"),
        n_references=("reference_id", lambda s: s.nunique()),
        mean=("value_representative", "mean"),
        median=("value_representative", "median"),
        sd=("value_representative", "std"),
        p25=("value_representative", lambda s: s.quantile(0.25)),
        p75=("value_representative", lambda s: s.quantile(0.75)),
        n_needs_review=("needs_review", "sum"),
    ).reset_index()

    # Observed range: widen to any explicitly reported min/max, since a study
    # reporting "37 (10 - 76)" tells us more about the range than its mean does.
    lows = comp["value_min"].fillna(comp["value_representative"])
    highs = comp["value_max"].fillna(comp["value_representative"])
    bounds = (comp.assign(_lo=lows, _hi=highs)
                  .groupby(["hmdb_id", "biospecimen"])
                  .agg(range_low=("_lo", "min"), range_high=("_hi", "max"))
                  .reset_index())
    rr = rr.merge(bounds, on=["hmdb_id", "biospecimen"], how="left")

    rr = rr[["hmdb_id", "metabolite_name", "biospecimen", "unit",
             "n_measurements", "n_references", "mean", "median", "sd",
             "p25", "p75", "range_low", "range_high", "n_needs_review"]]
    rr.to_sql("reference_ranges", conn, if_exists="append", index=False)
    print("  reference_ranges:    %s (metabolite x biospecimen)" % format(len(rr), ","))
    print("    with 3+ measurements: %s" % format(int((rr["n_measurements"] >= 3).sum()), ","))

    conn.commit()

    print("\nExcluded from comparable plots (kept in the database):")
    for unit, cls, reason, n in conn.execute(
            "SELECT unit, unit_class, reason, n FROM v_excluded ORDER BY n DESC"):
        print("  %-22s %-22s %-26s %s" % (unit, cls, reason, format(n, ",")))

    conn.close()
    print("\nWrote %s" % DB_PATH)


if __name__ == "__main__":
    main()
