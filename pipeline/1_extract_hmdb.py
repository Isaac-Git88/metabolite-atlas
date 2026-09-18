"""
Step 1 -- extract normal-concentration records from the HMDB XML release.

Streams data/hmdb_metabolites.xml (~6.5 GB) with iterparse, clearing each
element after use so memory stays flat, and writes one CSV row per reported
concentration: 51,246 rows, including those with no value recorded.

Input:  data/hmdb_metabolites.xml   (download from https://hmdb.ca/downloads)
Output: data/hmdb_normal_concentrations_raw.csv

Usage:
    python pipeline/1_extract_hmdb.py
"""

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

# Paths are anchored to this script's own folder, so every step runs correctly
# from any working directory. Inputs and generated data live in data/, the
# website in explorer/.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
EXPLORER = ROOT / "explorer"

XML_FILE = DATA / "hmdb_metabolites.xml"
OUTPUT_FILE = DATA / "hmdb_normal_concentrations_raw.csv"

NAMESPACE = {"hmdb": "http://www.hmdb.ca"}
METABOLITE_TAG = "{http://www.hmdb.ca}metabolite"

metabolite_count = 0
concentration_count = 0

print("Starting HMDB extraction...")
print(f"Input: {XML_FILE}")
print(f"Output: {OUTPUT_FILE}")
print()

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csvfile:

    fieldnames = [
        "hmdb_id",
        "metabolite_name",
        "biospecimen",
        "concentration_value_raw",
        "concentration_units",
        "subject_age",
        "subject_sex",
        "subject_condition",
        "pubmed_ids",
        "reference_texts"
    ]

    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    for event, elem in ET.iterparse(XML_FILE, events=("end",)):

        if elem.tag != METABOLITE_TAG:
            continue

        metabolite_count += 1

        # Basic info
        hmdb_id = elem.findtext(
            "hmdb:accession",
            default="",
            namespaces=NAMESPACE
        )

        metabolite_name = elem.findtext(
            "hmdb:name",
            default="",
            namespaces=NAMESPACE
        )

        concentrations = elem.find(
            "hmdb:normal_concentrations",
            NAMESPACE
        )

        if concentrations is not None:

            for concentration in concentrations.findall(
                "hmdb:concentration",
                NAMESPACE
            ):

                concentration_count += 1

                # Concentration info
                biospecimen = concentration.findtext(
                    "hmdb:biospecimen",
                    default="",
                    namespaces=NAMESPACE
                )

                value = concentration.findtext(
                    "hmdb:concentration_value",
                    default="",
                    namespaces=NAMESPACE
                )

                units = concentration.findtext(
                    "hmdb:concentration_units",
                    default="",
                    namespaces=NAMESPACE
                )

                age = concentration.findtext(
                    "hmdb:subject_age",
                    default="",
                    namespaces=NAMESPACE
                )

                sex = concentration.findtext(
                    "hmdb:subject_sex",
                    default="",
                    namespaces=NAMESPACE
                )

                condition = concentration.findtext(
                    "hmdb:subject_condition",
                    default="",
                    namespaces=NAMESPACE
                )

                pubmed_ids = []
                reference_texts = []

                references = concentration.find(
                    "hmdb:references",
                    NAMESPACE
                )

                if references is not None:

                    for reference in references.findall(
                        "hmdb:reference",
                        NAMESPACE
                    ):

                        pubmed_id = reference.findtext(
                            "hmdb:pubmed_id",
                            default="",
                            namespaces=NAMESPACE
                        )

                        reference_text = reference.findtext(
                            "hmdb:reference_text",
                            default="",
                            namespaces=NAMESPACE
                        )

                        if pubmed_id:
                            pubmed_ids.append(pubmed_id)

                        if reference_text:
                            reference_texts.append(reference_text)

                writer.writerow({
                    "hmdb_id": hmdb_id,
                    "metabolite_name": metabolite_name,
                    "biospecimen": biospecimen,
                    "concentration_value_raw": value,
                    "concentration_units": units,
                    "subject_age": age,
                    "subject_sex": sex,
                    "subject_condition": condition,
                    "pubmed_ids": "; ".join(pubmed_ids),
                    "reference_texts": " || ".join(reference_texts)
                })
        # Free memory
        elem.clear()

        if metabolite_count % 1000 == 0:
            print(
                f"Processed {metabolite_count:,} metabolites | "
                f"{concentration_count:,} concentration records"
            )

print()
print(f"Metabolites processed: {metabolite_count:,}")
print(f"Concentration records: {concentration_count:,}")
