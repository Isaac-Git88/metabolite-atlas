"""
Step 3 (E. coli) -- turn the scraped ECMDB concentrations into the shape the
shared parser expects, so E. coli joins the atlas through the same steps.

Input:  data/ecmdb/ecmdb_concentrations_all.csv   (from extract_ecmdb_concentrations.py)
Output: data/ecmdb/ecmdb_concentrations_clean.csv (the input to 3_parse_concentrations.py)

The mappings, and why:

  value       ECMDB stores value and error separately; HMDB stores one string.
              They are joined into "value +/- error" so the shared parser reads
              every source the same way. An error of 0.0 means none was recorded,
              so it is dropped rather than written as "+/- 0".

  biospecimen E. coli measurements are of whole cells in culture, so every row
              gets "Whole cell" -- the same value yeast uses, which keeps
              single-celled organisms comparable with each other and separate
              from human biofluids.

  conditions  E. coli has no age or sex, but it has the conditions the
              concentration depends on, and ECMDB records them well:
                  subject_age       -> growth system (shake flask, bioreactor)
                  subject_sex       -> strain, e.g. K12 NCM3722
                  subject_condition -> growth medium, with growth phase appended
              The medium is often a full recipe, so it is shortened to its
              carbon source where one is recognisable, with the full text kept
              in the scraped CSV.

Identifiers travel with the row: the ECMDB accession as native_id, the InChIKey
for cross-species matching (every ECMDB metabolite has one), and ECMDB's HMDB
cross-reference where it gives one -- only about 40% of rows do, which is why
the InChIKey matters here more than it did for yeast.

Usage:
    python pipeline/ecmdb/prepare_ecmdb.py
"""
import argparse
import csv
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "ecmdb")

BIOSPECIMEN = "Whole cell"

FIELDS = [
    "hmdb_id", "metabolite_name", "biospecimen",
    "concentration_value_raw", "concentration_units",
    "subject_age", "subject_sex", "subject_condition",
    "pubmed_ids", "reference_texts",
    "native_id", "inchikey",
]


def pad_hmdb(hmdb_id):
    """ECMDB gives the old short form (HMDB00005); HMDB now uses HMDB0000005."""
    hmdb_id = (hmdb_id or "").strip()
    if not hmdb_id.startswith("HMDB"):
        return ""
    return "HMDB" + hmdb_id[4:].zfill(7)


def raw_value(value, error):
    value = (value or "").strip()
    error = (error or "").strip()
    try:
        has_error = error != "" and float(error) != 0.0
    except ValueError:
        has_error = error != ""
    return "%s +/- %s" % (value, error) if has_error else value


def short_media(media, status):
    """A readable label: the carbon source where one is named, plus the phase.

    ECMDB's growth_media is often the full salt recipe, which is unreadable in a
    table. The carbon source is the part that changes between measurements of the
    same metabolite, so that is what the label leads with.
    """
    media = " ".join((media or "").split())
    m = re.search(r"with\s+[\d.]+\s*g/L\s+([A-Za-z][\w-]*)", media)
    label = m.group(1).lower() if m else (media[:60] + ("…" if len(media) > 60 else ""))
    status = " ".join((status or "").split())
    return "%s%s" % (label, " · " + status if status else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=os.path.join(DATA, "ecmdb_concentrations_all.csv"))
    ap.add_argument("--output", default=os.path.join(DATA, "ecmdb_concentrations_clean.csv"))
    args = ap.parse_args()

    rows, skipped = [], 0
    with open(args.input, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not (r.get("concentration") or "").strip():
                skipped += 1
                continue
            rows.append({
                "hmdb_id": pad_hmdb(r.get("hmdb_id")),
                "metabolite_name": r.get("name", ""),
                "biospecimen": BIOSPECIMEN,
                "concentration_value_raw": raw_value(r.get("concentration"), r.get("error")),
                "concentration_units": r.get("concentration_units", ""),
                "subject_age": " ".join((r.get("growth_system") or "").split()),
                "subject_sex": r.get("strain", ""),
                "subject_condition": short_media(r.get("growth_media"), r.get("growth_status")),
                "pubmed_ids": r.get("pubmed_id", ""),
                "reference_texts": r.get("reference", ""),
                "native_id": r.get("ecmdb_id", ""),
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
    print("With a citation:        %s" % format(sum(1 for r in rows if r["reference_texts"]), ","))
    print("\nWrote %s" % args.output)


if __name__ == "__main__":
    main()
