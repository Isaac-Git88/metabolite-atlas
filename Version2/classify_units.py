import re
import sqlite3
from pathlib import Path

# Paths are anchored to this script's own folder, so the pipeline runs correctly
# whatever the current working directory is. Version2 outputs live beside this
# script; the large shared inputs stay in the project root, one level up.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DB_PATH = ROOT / "metabolite_atlas.db"

# Units that mean the same thing get the same display label. Micromolar and
# micromoles per litre are identical: 1 uM == 1 umol/L.
DISPLAY_OVERRIDES = {
    "um": "umol/L",
    "umol/l": "umol/L",
    "mm": "mmol/L",
    "nm": "nmol/L",
}


def classify(unit_name):
    """
    Decide a unit's measurement type from its text.

    Returns (unit_class, display_name, is_comparable).
    """
    key = unit_name.strip().lower()

    if "creatinine" in key:
        return "creatinine_normalised", unit_name, 0

    # Amount per gram of sample -- feces, tissue, dry weight and so on.
    if re.search(r"/\s*g\b|/\s*mg\b|/\s*kg\b", key):
        return "mass_normalised", unit_name, 0

    # Amount per unit volume, however it is spelled.
    if key in DISPLAY_OVERRIDES:
        return "volumetric", DISPLAY_OVERRIDES[key], 1
    if re.fullmatch(r"[munp]?mol\s*/\s*l", key) or re.fullmatch(r"[munp]?m", key):
        return "volumetric", unit_name, 1
    if re.search(r"/\s*(l|dl|ml|ul)\b", key):
        return "volumetric", unit_name, 1

    return "unclassified", unit_name, 0


def add_column(conn, table, column, coltype):
    existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    if column not in existing:
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {coltype}')


def main():
    conn = sqlite3.connect(DB_PATH)

    for column, coltype in [
        ("unit_class", "TEXT"),
        ("display_name", "TEXT"),
        ("is_comparable", "INTEGER"),
    ]:
        add_column(conn, "concentration_units", column, coltype)

    units = conn.execute("SELECT unit_id, unit_name FROM concentration_units").fetchall()
    for unit_id, unit_name in units:
        unit_class, display_name, comparable = classify(unit_name)
        conn.execute(
            """UPDATE concentration_units
                  SET unit_class = ?, display_name = ?, is_comparable = ?
                WHERE unit_id = ?""",
            (unit_class, display_name, comparable, unit_id),
        )

    # The interface reads from this view, so the exclusion rule lives in one
    # place rather than being repeated in every query.
    conn.execute("DROP VIEW IF EXISTS comparable_measurements")
    conn.execute(
        """
        CREATE VIEW comparable_measurements AS
        SELECT ms.measurement_id,
               ms.hmdb_id,
               m.metabolite_name,
               b.name AS biospecimen,
               ms.concentration_value_raw,
               ms.value_mean, ms.value_sd, ms.value_min, ms.value_max,
               ms.value_representative,
               u.display_name AS unit,
               ms.subject_age, ms.subject_sex, ms.subject_condition,
               ms.reference_id,
               ms.parse_pattern, ms.parse_flags
          FROM measurements ms
          JOIN metabolites m         ON m.hmdb_id = ms.hmdb_id
          JOIN biospecimens b        ON b.biospecimen_id = ms.biospecimen_id
          JOIN concentration_units u ON u.unit_id = ms.unit_id
         WHERE u.is_comparable = 1
           AND ms.parse_ok = 1
        """
    )
    conn.commit()

    print("Unit classification:\n")
    rows = conn.execute(
        """SELECT u.unit_name, u.display_name, u.unit_class, u.is_comparable,
                  COUNT(ms.measurement_id) AS n
             FROM concentration_units u
             LEFT JOIN measurements ms ON ms.unit_id = u.unit_id
            GROUP BY u.unit_id
            ORDER BY n DESC"""
    ).fetchall()
    for unit_name, display_name, unit_class, comparable, n in rows:
        mark = "plotted" if comparable else "kept, not plotted"
        print(f"  {unit_name:22} -> {display_name:22} {unit_class:22} {n:6,}  {mark}")

    total = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    usable = conn.execute("SELECT COUNT(*) FROM comparable_measurements").fetchone()[0]
    mets = conn.execute(
        "SELECT COUNT(DISTINCT hmdb_id) FROM comparable_measurements"
    ).fetchone()[0]
    print(
        f"\ncomparable_measurements: {usable:,} of {total:,} rows "
        f"({usable / total:.1%}) across {mets:,} metabolites"
    )
    conn.close()


if __name__ == "__main__":
    main()
