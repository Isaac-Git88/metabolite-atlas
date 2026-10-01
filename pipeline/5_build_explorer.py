"""
Step 5 -- build the standalone web explorer.

Reads the database, serialises it to JSON, and splices it into
explorer/template.html to produce explorer/index.html: a single self-contained
file with no build step, no dependencies and no network calls at runtime beyond
web fonts. Host it on GitHub Pages or open it locally.

Edit explorer/template.html to change the page; index.html is generated and any
hand edit to it is lost on the next build.

Input:  data/metabolite_atlas.db, explorer/template.html
Output: explorer/index.html

Usage:
    python pipeline/5_build_explorer.py
"""

import json
import sqlite3
from pathlib import Path

# Paths are anchored to this script's own folder, so every step runs correctly
# from any working directory. Inputs and generated data live in data/, the
# website in explorer/.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
EXPLORER = ROOT / "explorer"

DB_PATH = DATA / "metabolite_atlas.db"
OUT_PATH = EXPLORER / "index.html"


def export_data(conn):
    conn.row_factory = sqlite3.Row

    species = {r["species_id"]: [r["common_name"], r["scientific_name"], r["ncbi_taxon_id"]]
               for r in conn.execute(
                   "SELECT species_id, common_name, scientific_name, ncbi_taxon_id FROM species")}

    # The page keys metabolites by a single identifier. Since the atlas now
    # holds metabolites HMDB has never catalogued (yeast-only lipids keep their
    # YMDB id), metabolite_id is exported under the name the page already uses.
    metabolites = {r["metabolite_id"]: r["metabolite_name"]
                   for r in conn.execute(
                       "SELECT metabolite_id, metabolite_name FROM metabolites")}

    # The connectivity layer of each metabolite's InChIKey: what the
    # cross-species view offers as a looser, opt-in structure match.
    blocks = {r["metabolite_id"]: r["inchikey_block"]
              for r in conn.execute(
                  "SELECT metabolite_id, inchikey_block FROM metabolites "
                  "WHERE inchikey_block IS NOT NULL")}

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
        """SELECT metabolite_id, biospecimen_id, unit_id, concentration_value_raw,
                  value_representative, value_min, value_max, value_sd,
                  parse_ok, needs_review, parse_note,
                  subject_age, subject_sex, subject_condition, reference_id,
                  species_id
           FROM measurements"""
    ):
        measurements.append([
            r["metabolite_id"], r["biospecimen_id"], r["unit_id"],
            r["concentration_value_raw"], r["value_representative"],
            r["value_min"], r["value_max"], r["value_sd"],
            r["parse_ok"], r["needs_review"], r["parse_note"],
            r["subject_age"], r["subject_sex"], r["subject_condition"],
            r["reference_id"],
            r["species_id"],          # appended, so existing tuple offsets hold
        ])

    excluded = [[r["unit"], r["unit_class"], r["reason"], r["n"]]
                for r in conn.execute(
                    "SELECT unit, unit_class, reason, n FROM v_excluded ORDER BY n DESC")]

    # Which databases the measurements come from, largest first, so the page can
    # name its sources from the data rather than from hard-coded text.
    sources = [[r["source_db"], r["n"]] for r in conn.execute(
        "SELECT source_db, COUNT(*) AS n FROM measurements GROUP BY source_db ORDER BY n DESC")]

    return {
        "sources": sources,
        "species": species,
        "metabolites": metabolites,
        "blocks": blocks,
        "biospecimens": biospecimens,
        "units": units,
        "references": references,
        "measurements": measurements,
        "excluded": excluded,
    }


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "Couldn't find %s. Run 4_build_database.py first." % DB_PATH)

    print("Reading %s ..." % DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    data = export_data(conn)
    conn.close()

    print("  %s measurements, %s metabolites, %s species"
          % (format(len(data["measurements"]), ","),
             format(len(data["metabolites"]), ","),
             format(len(data["species"]), ",")))

    payload = json.dumps(data, separators=(",", ":"))
    payload = payload.replace("</script", "<\\/script")

    template = (EXPLORER / "template.html").read_text(encoding="utf-8")
    page = template.replace("__ATLAS_DATA_JSON__", payload)

    OUT_PATH.write_text(page, encoding="utf-8")
    print("Wrote %s (%.1f MB)" % (OUT_PATH, OUT_PATH.stat().st_size / 1024 / 1024))


if __name__ == "__main__":
    main()
