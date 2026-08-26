"""
Builds a normalized SQLite database for metabolite-atlas from the HMDB
normal concentrations CSV.
 
Replaces the single flat table (concentrations_raw) with five related
tables: metabolites, biospecimens, concentration_units, references, and
measurements (the fact table linking them all together).
 
Usage:
    pip install pandas
    python normalize_db.py
"""
 
import sqlite3
import pandas as pd
from pathlib import Path
 
CSV_PATH = Path("hmdb_normal_concentrations_clean.csv")
DB_PATH = Path("metabolite_atlas.db")
 
SCHEMA = """
CREATE TABLE metabolites (
    hmdb_id         TEXT PRIMARY KEY,
    metabolite_name TEXT NOT NULL
);
 
CREATE TABLE biospecimens (
    biospecimen_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE
);
 
CREATE TABLE concentration_units (
    unit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_name       TEXT NOT NULL UNIQUE
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
    concentration_value_raw TEXT NOT NULL,
    unit_id                 INTEGER NOT NULL REFERENCES concentration_units(unit_id),
    subject_age             TEXT,
    subject_sex             TEXT,
    subject_condition       TEXT,
    reference_id            INTEGER REFERENCES "references"(reference_id)
);
 
CREATE INDEX idx_measurements_hmdb_id        ON measurements(hmdb_id);
CREATE INDEX idx_measurements_biospecimen_id ON measurements(biospecimen_id);
CREATE INDEX idx_metabolites_name            ON metabolites(metabolite_name);
"""
 
 
def main():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Couldn't find {CSV_PATH}. Run this script from the metabolite-atlas project root."
        )
 
    print(f"Reading {CSV_PATH} ...")
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df):,} rows")
 
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
 
    # --- metabolites: one row per distinct hmdb_id ---
    metabolites = df[["hmdb_id", "metabolite_name"]].drop_duplicates("hmdb_id")
    metabolites.to_sql("metabolites", conn, if_exists="append", index=False)
    print(f"  metabolites:         {len(metabolites):,}")
 
    # --- biospecimens: dictionary of distinct specimen types ---
    biospecimens = pd.DataFrame({"name": sorted(df["biospecimen"].dropna().unique())})
    biospecimens.to_sql("biospecimens", conn, if_exists="append", index=False)
    biospecimen_map = dict(conn.execute("SELECT name, biospecimen_id FROM biospecimens").fetchall())
    print(f"  biospecimens:        {len(biospecimens):,}")
 
    # --- concentration_units: dictionary of distinct units ---
    units = pd.DataFrame({"unit_name": sorted(df["concentration_units"].dropna().unique())})
    units.to_sql("concentration_units", conn, if_exists="append", index=False)
    unit_map = dict(conn.execute("SELECT unit_name, unit_id FROM concentration_units").fetchall())
    print(f"  concentration_units: {len(units):,}")
 
    # --- references: one row per distinct pubmed_id (rows with no pubmed_id get none) ---
    refs = (
        df[["pubmed_ids", "reference_texts"]]
        .dropna(subset=["pubmed_ids"])
        .drop_duplicates("pubmed_ids")
        .rename(columns={"pubmed_ids": "pubmed_id", "reference_texts": "reference_text"})
    )
    refs.to_sql("references", conn, if_exists="append", index=False)
    ref_map = dict(conn.execute('SELECT pubmed_id, reference_id FROM "references"').fetchall())
    print(f"  references:          {len(refs):,}")
 
    # --- measurements: the fact table, one row per original CSV row ---
    measurements = pd.DataFrame({
        "hmdb_id": df["hmdb_id"],
        "biospecimen_id": df["biospecimen"].map(biospecimen_map),
        "concentration_value_raw": df["concentration_value_raw"],
        "unit_id": df["concentration_units"].map(unit_map),
        "subject_age": df["subject_age"],
        "subject_sex": df["subject_sex"],
        "subject_condition": df["subject_condition"],
        "reference_id": df["pubmed_ids"].map(ref_map),
    })
    measurements.to_sql("measurements", conn, if_exists="append", index=False)
    print(f"  measurements:        {len(measurements):,}")
 
    conn.commit()
 
    # Sanity check: row counts and a sample join
    print("\nSample join (first 3 measurements, fully resolved):")
    sample = conn.execute("""
        SELECT m.metabolite_name, b.name AS biospecimen,
               ms.concentration_value_raw, u.unit_name
        FROM measurements ms
        JOIN metabolites m ON m.hmdb_id = ms.hmdb_id
        JOIN biospecimens b ON b.biospecimen_id = ms.biospecimen_id
        JOIN concentration_units u ON u.unit_id = ms.unit_id
        LIMIT 3
    """).fetchall()
    for row in sample:
        print(f"  {row}")
 
    conn.close()
    print(f"\nNormalized database ready at {DB_PATH}")
 
 
if __name__ == "__main__":
    main()
 

