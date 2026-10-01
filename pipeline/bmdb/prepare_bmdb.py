"""
BMDB step 2 -- turn the extracted BMDB concentrations into the shape the shared
parser expects, so cow joins the atlas through the same steps 3-5.

Input:  data/bmdb/bmdb_concentrations_all.csv   (from extract_bmdb_concentrations.py)
Output: data/bmdb/bmdb_concentrations_clean.csv (the input to 3_parse_concentrations.py)

What is dropped, and why:

  no value    Records with a citation but no number (~15%) cannot contribute to
              a range -- the same rule as HMDB step 2.

  diseased    BMDB's block is called "normal_concentrations", but a handful of
              records are from sick animals (mastitis). Rows whose comment
              names a disease are dropped, and every dropped comment is
              printed so the rule can be checked. The keyword list is explicit
              below; nothing is inferred.

  wrong unit  Whole studies whose values are impossible as labelled are listed
              in EXCLUDE_STUDIES with the reason, and every row citing them is
              dropped -- not corrected, because the true unit is a guess. This
              is the same rule pipeline/mwb/prepare_mwb.py applies.

The mappings, and why:

  value       BMDB writes one string ("14+/-2", "2-12") exactly as HMDB does,
              so it passes through unchanged and the shared parser reads it.

  biospecimen Kept as BMDB names it. BMDB has distinct muscle names
              (Longissimus thoracis, Semimembranosus) as well as plain
              "Muscle"; merging them would be a judgement, so it is not made
              here.

  conditions  BMDB has no age or sex fields. The comment -- which carries the
              diet, the cow type, the milk product and the method -- goes into
              subject_condition, so the explorer shows it next to each value.
              subject_age and subject_sex are left empty.

  identity    The BMDB accession is native_id and the InChIKey travels with the
              row for cross-species matching. BMDB carries no HMDB
              cross-reference, so hmdb_id is left empty rather than guessed
              from the accession number.

Usage:
    python pipeline/bmdb/prepare_bmdb.py
"""

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT / "data" / "bmdb"

FIELDS = [
    "hmdb_id", "metabolite_name", "biospecimen",
    "concentration_value_raw", "concentration_units",
    "subject_age", "subject_sex", "subject_condition",
    "pubmed_ids", "reference_texts",
    "native_id", "inchikey",
]

# A comment matching any of these describes a sick animal, not a normal one.
DISEASE = re.compile(
    r"mastitis|ketosis|acidosis|metritis|lameness|infect|disease|"
    r"displaced abomasum|retained placenta|milk fever|hypocalc",
    re.IGNORECASE,
)


# Studies left out whole. Matched on a phrase from the reference text, because
# BMDB gives some of them no PubMed ID.
EXCLUDE_STUDIES = {
    "Abarghuei": (
        "Abarghuei et al. 2014, Livestock Science 164:72-80 (pomegranate-peel extract). "
        "Blood cholesterol is ~4,000,000 umol/L, about 1,000x the bovine range "
        "(2,000-5,000 umol/L), and milk palmitic acid ~400,000 umol/L, ~10x what "
        "milk fat allows; the values look like percentages or mg/dL converted "
        "wrongly upstream. Also a diet-intervention study."
    ),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DATA / "bmdb_concentrations_all.csv"))
    ap.add_argument("--output", default=str(DATA / "bmdb_concentrations_clean.csv"))
    args = ap.parse_args()

    rows, no_value, diseased, excluded = [], 0, Counter(), Counter()
    with open(args.input, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["concentration_value"].strip():
                no_value += 1
                continue
            study = next((k for k in EXCLUDE_STUDIES if k in r["reference_texts"]), None)
            if study:
                excluded[study] += 1
                continue
            if DISEASE.search(r["comment"]):
                diseased[r["comment"]] += 1
                continue
            rows.append({
                "hmdb_id": "",
                "metabolite_name": r["name"],
                "biospecimen": r["biospecimen"],
                "concentration_value_raw": r["concentration_value"],
                "concentration_units": r["concentration_units"],
                "subject_age": "",
                "subject_sex": "",
                "subject_condition": r["comment"],
                "pubmed_ids": r["pubmed_ids"],
                "reference_texts": r["reference_texts"],
                "native_id": r["bmdb_id"],
                "inchikey": r["inchikey"],
            })

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"Rows written: {len(rows):,}")
    print(f"  dropped, no value:  {no_value:,}")
    print(f"  dropped, diseased:  {sum(diseased.values()):,}")
    for comment, n in diseased.most_common():
        print(f"      {n:>4}  {comment}")
    print(f"  dropped, excluded study: {sum(excluded.values()):,}")
    for study, n in excluded.most_common():
        print(f"      {n:>4}  {study}: {EXCLUDE_STUDIES[study][:70]}...")
    print(f"Metabolites:          {len({r['native_id'] for r in rows}):,}")
    print(f"With an InChIKey:     {sum(1 for r in rows if r['inchikey']):,}")
    print(f"With a citation:      {sum(1 for r in rows if r['reference_texts']):,}")

    print("\nBy biospecimen:")
    for k, n in Counter(r["biospecimen"] for r in rows).most_common():
        print(f"  {n:>6,}  {k}")
    print("By unit:")
    for k, n in Counter(r["concentration_units"] for r in rows).most_common():
        print(f"  {n:>6,}  {k}")
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
