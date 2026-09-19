import csv
import xml.etree.ElementTree as ET

XML_FILE = "hmdb_metabolites.xml"
OUTPUT_FILE = "hmdb_test.csv"

NAMESPACE = {"hmdb": "http://www.hmdb.ca"}

# Open the CSV file
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
        "pubmed_id",
        "reference_text"
    ]

    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    # Read the XML
    for event, elem in ET.iterparse(XML_FILE, events=("end",)):

        if elem.tag == "{http://www.hmdb.ca}metabolite":

            # Basic metabolite information
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

            # Find normal concentration records
            concentrations = elem.find(
                "hmdb:normal_concentrations",
                NAMESPACE
            )

            if concentrations is not None:

                for concentration in concentrations.findall(
                    "hmdb:concentration",
                    NAMESPACE
                ):

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

                    pubmed_id = concentration.findtext(
                        ".//hmdb:pubmed_id",
                        default="",
                        namespaces=NAMESPACE
                    )

                    reference_text = concentration.findtext(
                        ".//hmdb:reference_text",
                        default="",
                        namespaces=NAMESPACE
                    )

                    # Write concentration record to the CSV
                    writer.writerow({
                        "hmdb_id": hmdb_id,
                        "metabolite_name": metabolite_name,
                        "biospecimen": biospecimen,
                        "concentration_value_raw": value,
                        "concentration_units": units,
                        "subject_age": age,
                        "subject_sex": sex,
                        "subject_condition": condition,
                        "pubmed_id": pubmed_id,
                        "reference_text": reference_text
                    })

            elem.clear()
            break
