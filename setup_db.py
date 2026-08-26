"""
Sets up a local SQLite database for metabolite-atlas from the HMDB
normal concentrations CSV.
 
Usage:
    pip install pandas
    python setup_db.py
"""
 
import sqlite3
import pandas as pd
from pathlib import Path
 
CSV_PATH = Path("hmdb_normal_concentrations_clean.csv")
DB_PATH = Path("metabolite_atlas.db")
 
def main():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Couldn't find {CSV_PATH}. Run this script from the metabolite-atlas project root."
        )
 
    print(f"Reading {CSV_PATH} ...")
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df):,} rows, {len(df.columns)} columns")
 
    conn = sqlite3.connect(DB_PATH)
 
    # Load raw data as-is into a staging table
    df.to_sql("concentrations_raw", conn, if_exists="replace", index=False)
 
    # Helpful indexes for common lookups
    cur = conn.cursor()
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hmdb_id ON concentrations_raw(hmdb_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_metabolite_name ON concentrations_raw(metabolite_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_biospecimen ON concentrations_raw(biospecimen)")
    conn.commit()
 
    # Quick sanity check
    n = cur.execute("SELECT COUNT(*) FROM concentrations_raw").fetchone()[0]
    n_metabolites = cur.execute("SELECT COUNT(DISTINCT hmdb_id) FROM concentrations_raw").fetchone()[0]
    print(f"Database ready at {DB_PATH}")
    print(f"  {n:,} rows, {n_metabolites:,} distinct metabolites")
 
    conn.close()
 
if __name__ == "__main__":
    main()
 
