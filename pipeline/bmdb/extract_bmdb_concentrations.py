"""
BMDB step 1 -- extract every concentration record from the BMDB XML release.

Unlike YMDB and ECMDB, BMDB's download *does* carry concentrations, in the same
<normal_concentrations> block HMDB uses, so nothing needs scraping. The file is
streamed with iterparse and each <metabolite> is cleared after use, so memory
stays flat (the release is ~450 MB, 51,689 metabolites, most of them predicted
and without any concentration).

One CSV row is written per <concentration>, including those with no value, so
this file is a faithful copy of what BMDB holds; prepare_bmdb.py does the
filtering.

Differences from HMDB worth knowing:
  * There is no subject_age / subject_sex / subject_condition. What the cow
    was, ate, or how the sample was measured is all in a free-text <comment>
    ("By LC-MS/MS", "Commercial 2% milk by LC-HRMS", "Samples have been
    collected from 8 healthy primiparous Holstein cow ..."). It is kept whole.
  * There is no HMDB cross-reference. Cross-species identity comes from the
    InChIKey, which ~99% of concentration rows have.

Input:  data/bmdb/bmdb_metabolites.xml  (download from https://bmdb.ca/downloads)
        -- falls back to bmdb_metabolites.xml in the repo root if not found there
Output: data/bmdb/bmdb_concentrations_all.csv

Usage:
    python pipeline/bmdb/extract_bmdb_concentrations.py
    python pipeline/bmdb/extract_bmdb_concentrations.py --xml /path/to/bmdb_metabolites.xml
"""

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT / "data" / "bmdb"

XML_CANDIDATES = [DATA / "bmdb_metabolites.xml", ROOT / "bmdb_metabolites.xml"]
OUTPUT_FILE = DATA / "bmdb_concentrations_all.csv"

NS = "{http://www.bmdb.ca}"
METABOLITE_TAG = NS + "metabolite"

FIELDS = [
    "bmdb_id", "name", "biospecimen",
    "concentration_value", "concentration_units", "comment",
    "pubmed_ids", "reference_texts",
    "inchikey", "chemical_formula", "average_molecular_weight",
    "cas_registry_number", "kegg_id", "chebi_id", "pubchem_compound_id",
]


def text(elem, tag):
    """Stripped text of a direct child, '' if missing or empty."""
    return (elem.findtext(NS + tag) or "").strip()


def find_xml(explicit):
    if explicit:
        path = Path(explicit)
        if not path.exists():
            sys.exit(f"XML not found: {path}")
        return path
    for path in XML_CANDIDATES:
        if path.exists():
            return path
    sys.exit("bmdb_metabolites.xml not found. Download it from https://bmdb.ca/downloads "
             f"and place it in {DATA}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--xml", help="path to bmdb_metabolites.xml")
    ap.add_argument("--output", default=str(OUTPUT_FILE))
    args = ap.parse_args()

    xml_file = find_xml(args.xml)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    print(f"Input:  {xml_file}")
    print(f"Output: {args.output}\n")

    metabolites = with_conc = records = with_value = 0

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()

        for _, elem in ET.iterparse(xml_file, events=("end",)):
            if elem.tag != METABOLITE_TAG:
                continue
            metabolites += 1

            block = elem.find(NS + "normal_concentrations")
            concentrations = block.findall(NS + "concentration") if block is not None else []
            if concentrations:
                with_conc += 1
                ids = {t: text(elem, t) for t in (
                    "accession", "name", "inchikey", "chemical_formula",
                    "average_molecular_weight", "cas_registry_number",
                    "kegg_id", "chebi_id", "pubchem_compound_id")}

                for conc in concentrations:
                    records += 1
                    pubmed_ids, reference_texts = [], []
                    refs = conc.find(NS + "references")
                    if refs is not None:
                        for ref in refs.findall(NS + "reference"):
                            if text(ref, "pubmed_id"):
                                pubmed_ids.append(text(ref, "pubmed_id"))
                            if text(ref, "reference_text"):
                                reference_texts.append(text(ref, "reference_text"))

                    value = text(conc, "concentration_value")
                    with_value += bool(value)
                    writer.writerow({
                        "bmdb_id": ids["accession"],
                        "name": ids["name"],
                        "biospecimen": text(conc, "biospecimen"),
                        "concentration_value": value,
                        "concentration_units": text(conc, "concentration_units"),
                        # Comments can span lines in the XML; one line in the CSV.
                        "comment": " ".join(text(conc, "comment").split()),
                        "pubmed_ids": "; ".join(pubmed_ids),
                        "reference_texts": " || ".join(reference_texts),
                        "inchikey": ids["inchikey"],
                        "chemical_formula": ids["chemical_formula"],
                        "average_molecular_weight": ids["average_molecular_weight"],
                        "cas_registry_number": ids["cas_registry_number"],
                        "kegg_id": ids["kegg_id"],
                        "chebi_id": ids["chebi_id"],
                        "pubchem_compound_id": ids["pubchem_compound_id"],
                    })

            elem.clear()
            if metabolites % 10000 == 0:
                print(f"  {metabolites:,} metabolites | {records:,} concentration records")

    print()
    print(f"Metabolites in release:             {metabolites:,}")
    print(f"Metabolites with any concentration: {with_conc:,}")
    print(f"Concentration records:              {records:,}")
    print(f"  with a value:                     {with_value:,}")
    print(f"  without a value:                  {records - with_value:,}")


if __name__ == "__main__":
    main()
