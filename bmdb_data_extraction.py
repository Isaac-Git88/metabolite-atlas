import csv
import xml.etree.ElementTree as ET

XML_FILE = "bmdb_metabolites.xml"
OUTPUT_FILE = "bmdb_normal_concentrations_raw.csv"

NAMESPACE = {"bmdb": "http://www.bmdb.ca"}
METABOLITE_TAG = "{http://www.bmdb.ca}metabolite"

metabolite_count = 0
concentration_count = 0

print("Starting BMDB extraction...")
print(f"Input: {XML_FILE}")
print(f"Output: {OUTPUT_FILE}")
print()

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csvfile:

    fieldnames = [
        "bmdb_id",
        "metabolite_name",
        "biospecimen",
        "concentration_value_raw",
        "concentration_units",
        "comment",
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

        # Basic metabolite information
        bmdb_id = elem.findtext(
            "bmdb:accession",
            default="",
            namespaces=NAMESPACE
        )

        metabolite_name = elem.findtext(
            "bmdb:name",
            default="",
            namespaces=NAMESPACE
        )

        concentrations = elem.find(
            "bmdb:normal_concentrations",
            NAMESPACE
        )

        if concentrations is not None:

            for concentration in concentrations.findall(
                "bmdb:concentration",
                NAMESPACE
            ):

                concentration_count += 1

                # Concentration information
                biospecimen = concentration.findtext(
                    "bmdb:biospecimen",
                    default="",
                    namespaces=NAMESPACE
                )

                value = concentration.findtext(
                    "bmdb:concentration_value",
                    default="",
                    namespaces=NAMESPACE
                )

                units = concentration.findtext(
                    "bmdb:concentration_units",
                    default="",
                    namespaces=NAMESPACE
                )

                # BMDB stores useful experimental/context information
                # in a comment field.
                comment = concentration.findtext(
                    "bmdb:comment",
                    default="",
                    namespaces=NAMESPACE
                )

                # BMDB normal concentration records do not contain
                # dedicated age, sex, or condition fields.
                # These are retained as blank columns so the structure
                # remains compatible with the HMDB extraction output.
                age = ""
                sex = ""
                condition = ""

                pubmed_ids = []
                reference_texts = []

                references = concentration.find(
                    "bmdb:references",
                    NAMESPACE
                )

                if references is not None:

                    for reference in references.findall(
                        "bmdb:reference",
                        NAMESPACE
                    ):

                        pubmed_id = reference.findtext(
                            "bmdb:pubmed_id",
                            default="",
                            namespaces=NAMESPACE
                        )

                        reference_text = reference.findtext(
                            "bmdb:reference_text",
                            default="",
                            namespaces=NAMESPACE
                        )

                        if pubmed_id:
                            pubmed_ids.append(pubmed_id)

                        if reference_text:
                            reference_texts.append(reference_text)

                writer.writerow({
                    "bmdb_id": bmdb_id,
                    "metabolite_name": metabolite_name,
                    "biospecimen": biospecimen,
                    "concentration_value_raw": value,
                    "concentration_units": units,
                    "comment": comment,
                    "subject_age": age,
                    "subject_sex": sex,
                    "subject_condition": condition,
                    "pubmed_ids": "; ".join(pubmed_ids),
                    "reference_texts": " || ".join(reference_texts)
                })

        # Free memory after each metabolite.
        # This is important because the BMDB XML file is large.
        elem.clear()

        if metabolite_count % 1000 == 0:
            print(
                f"Processed {metabolite_count:,} metabolites | "
                f"{concentration_count:,} concentration records"
            )

print()
print(f"Metabolites processed: {metabolite_count:,}")
print(f"Concentration records: {concentration_count:,}")
print(f"Output saved to: {OUTPUT_FILE}")