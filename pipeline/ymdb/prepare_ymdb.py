"""
Step 3 (yeast) -- turn the scraped YMDB concentrations into the shape the shared
parser expects, so yeast joins the atlas through the same steps as human data.

Input:  data/ymdb/ymdb_concentrations_all.csv   (from extract_ymdb_concentrations.py)
Output: data/ymdb/ymdb_concentrations_clean.csv (the input to 3_parse_concentrations.py)

Three mappings are needed, and each is a judgement worth stating in the report:

  value    YMDB stores the value and its error in separate columns; HMDB stores
           one string. They are joined back into "value +/- error", so the shared
           parser reads both databases the same way. An error of 0.0 means YMDB
           recorded no error, so it is dropped rather than written as "+/- 0".

  biospecimen
           HMDB rows name a biofluid (Blood, Urine); yeast measurements are of
           whole cells in culture, so every yeast row gets the single value
           "Whole cell". YMDB's 'internal' flag is NOT a biospecimen: all 562
           rows it marks come from one unpublished in-house experiment and carry
           no reference, while the literature rows are marked false or left
           blank. It is therefore recorded as provenance (see below), not as a
           kind of sample.

  subject fields
           Yeast has no age or sex. The columns are reused for what does vary
           between yeast experiments -- strain and growth medium -- because they
           play the same role: the conditions the measurement belongs to.
               subject_age       -> (empty)
               subject_sex       -> strain, e.g. BY4741
               subject_condition -> growth medium
           A row flagged internal=true has no citation, so its reference text is
           set to "YMDB in-house measurement (unpublished)": unpublished data
           shown as such, rather than looking like a missing reference.

The metabolite's own identifiers travel with the row: ymdb_id as native_id, the
InChIKey for cross-species matching, and YMDB's HMDB cross-reference (padded to
the modern 11-character form) where it gives one.

Usage:
    python pipeline/ymdb/prepare_ymdb.py
"""
import argparse
import csv
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "ymdb")

BIOSPECIMEN = "Whole cell"
IN_HOUSE = "YMDB in-house measurement (unpublished)"

FIELDS = [
    # the columns 3_parse_concentrations.py reads
    "hmdb_id", "metabolite_name", "biospecimen",
    "concentration_value_raw", "concentration_units",
    "subject_age", "subject_sex", "subject_condition",
    "pubmed_ids", "reference_texts",
    # carried through for cross-species identity
    "native_id", "inchikey",
]


def pad_hmdb(hmdb_id):
    """YMDB gives the old short form (HMDB00641); HMDB now uses HMDB0000641."""
    hmdb_id = (hmdb_id or "").strip()
    if not hmdb_id.startswith("HMDB"):
        return ""
    return "HMDB" + hmdb_id[4:].zfill(7)


def raw_value(value, error):
    """Join YMDB's value and error into one string, the way HMDB writes them."""
    value = (value or "").strip()
    error = (error or "").strip()
    try:
        has_error = error != "" and float(error) != 0.0
    except ValueError:
        has_error = error != ""
    return "%s +/- %s" % (value, error) if has_error else value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=os.path.join(DATA, "ymdb_concentrations_all.csv"))
    ap.add_argument("--output", default=os.path.join(DATA, "ymdb_concentrations_clean.csv"))
    args = ap.parse_args()

    rows, skipped, biospecimens = [], 0, {}
    with open(args.input, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not (r.get("concentration") or "").strip():
                skipped += 1          # no value at all: nothing to load
                continue
            in_house = (r.get("internal") or "").strip().lower() == "true"
            reference = r.get("reference", "") or (IN_HOUSE if in_house else "")
            biospecimens[BIOSPECIMEN] = biospecimens.get(BIOSPECIMEN, 0) + 1
            rows.append({
                "hmdb_id": pad_hmdb(r.get("hmdb_id")),
                "metabolite_name": r.get("name", ""),
                "biospecimen": BIOSPECIMEN,
                "concentration_value_raw": raw_value(r.get("concentration"), r.get("error")),
                "concentration_units": r.get("concentration_units", ""),
                "subject_age": "",
                "subject_sex": r.get("strain", ""),
                "subject_condition": r.get("growth_media", ""),
                "pubmed_ids": r.get("pubmed_id", ""),
                "reference_texts": reference,
                "native_id": r.get("ymdb_id", ""),
                "inchikey": r.get("inchikey", ""),
            })

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print("Rows written: %s%s" % (format(len(rows), ","),
                                  "" if not skipped else "  (%d with no value skipped)" % skipped))
    print("Metabolites:  %s" % format(len({r["native_id"] for r in rows}), ","))
    print("With an InChIKey:       %s" % format(sum(1 for r in rows if r["inchikey"]), ","))
    print("With an HMDB reference: %s" % format(sum(1 for r in rows if r["hmdb_id"]), ","))
    in_house = sum(1 for r in rows if r["reference_texts"] == IN_HOUSE)
    print("Biospecimen:  %s (all rows)" % BIOSPECIMEN)
    print("Unpublished YMDB in-house rows: %s" % format(in_house, ","))
    print("\nWrote %s" % args.output)


if __name__ == "__main__":
    main()
