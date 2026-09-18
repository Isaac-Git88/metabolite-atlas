import json
import sqlite3
from pathlib import Path

# Paths are anchored to this script's own folder, so the pipeline runs correctly
# whatever the current working directory is. Version2 outputs live beside this
# script; the large shared inputs stay in the project root, one level up.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DB_PATH = HERE / "metabolite_atlas_v2.db"
OUT_PATH = HERE / "metabolite_atlas_explorer_v2.html"


def export_data(conn):
    conn.row_factory = sqlite3.Row

    metabolites = {r["hmdb_id"]: r["metabolite_name"]
                   for r in conn.execute("SELECT hmdb_id, metabolite_name FROM metabolites")}

    biospecimens = {r["biospecimen_id"]: r["name"]
                    for r in conn.execute("SELECT biospecimen_id, name FROM biospecimens")}

    units = {r["unit_id"]: [r["unit_std"], r["unit_class"], r["is_comparable"]]
             for r in conn.execute(
                 "SELECT unit_id, unit_std, unit_class, is_comparable FROM concentration_units")}

    references = {r["reference_id"]: [r["pubmed_id"], r["reference_text"]]
                  for r in conn.execute(
                      'SELECT reference_id, pubmed_id, reference_text FROM "references"')}

    measurements = []
    for r in conn.execute(
        """SELECT hmdb_id, biospecimen_id, unit_id, concentration_value_raw,
                  value_representative, value_min, value_max, value_sd,
                  parse_ok, needs_review, parse_note,
                  subject_age, subject_sex, subject_condition, reference_id
           FROM measurements"""
    ):
        measurements.append([
            r["hmdb_id"], r["biospecimen_id"], r["unit_id"],
            r["concentration_value_raw"], r["value_representative"],
            r["value_min"], r["value_max"], r["value_sd"],
            r["parse_ok"], r["needs_review"], r["parse_note"],
            r["subject_age"], r["subject_sex"], r["subject_condition"],
            r["reference_id"],
        ])

    ranges = []
    for r in conn.execute(
        """SELECT hmdb_id, metabolite_name, biospecimen, unit, n_measurements,
                  n_references, mean, median, sd, p25, p75, range_low, range_high,
                  n_needs_review
           FROM reference_ranges"""
    ):
        ranges.append([
            r["hmdb_id"], r["biospecimen"], r["unit"], r["n_measurements"],
            r["n_references"], r["mean"], r["median"], r["sd"], r["p25"], r["p75"],
            r["range_low"], r["range_high"], r["n_needs_review"],
        ])

    excluded = [[r["unit"], r["unit_class"], r["reason"], r["n"]]
                for r in conn.execute(
                    "SELECT unit, unit_class, reason, n FROM v_excluded ORDER BY n DESC")]

    return {
        "metabolites": metabolites,
        "biospecimens": biospecimens,
        "units": units,
        "references": references,
        "measurements": measurements,
        "ranges": ranges,
        "excluded": excluded,
    }


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Couldn't find %s. Run normalize_db_v2.py first." % DB_PATH)

    print("Reading %s ..." % DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    data = export_data(conn)
    conn.close()

    print("  %s measurements, %s metabolites, %s reference ranges"
          % (format(len(data["measurements"]), ","),
             format(len(data["metabolites"]), ","),
             format(len(data["ranges"]), ",")))

    payload = json.dumps(data, separators=(",", ":"))
    payload = payload.replace("</script", "<\\/script")

    template = Path(__file__).with_name("explorer_v2_template.html").read_text(encoding="utf-8")
    page = template.replace("__ATLAS_DATA_JSON__", payload)

    OUT_PATH.write_text(page, encoding="utf-8")
    print("Wrote %s (%.1f MB)" % (OUT_PATH, OUT_PATH.stat().st_size / 1024 / 1024))


if __name__ == "__main__":
    main()
