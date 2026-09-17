import csv
import json
import zipfile

ZIP_FILE = "ecmdb.json.zip"
OUTPUT_FILE = "ecmdb_metabolites_raw.csv"

metabolite_count = 0

print("Starting ECMDB extraction...")
print(f"Input: {ZIP_FILE}")
print(f"Output: {OUTPUT_FILE}")
print()

# Fields selected from the supplied ECMDB JSON for the metabolite atlas.
# The original ECMDB names are preserved where practical.
fieldnames = [
    "ecmdb_id",
    "metabolite_name",
    "description",
    "cas",
    "state",
    "melting_point",
    "location",
    "category",
    "hmdb_id",
    "chebi_id",
    "kegg_id",
    "pubchem_id",
    "biocyc_id",
    "foodb_id",
    "chemspider_id",
    "m2m_id",
    "het_id",
    "chemical_formula",
    "smiles",
    "inchi",
    "inchikey",
    "iupac_name",
    "traditional_iupac_name",
    "average_molecular_mass",
    "monoisotopic_molecular_mass",
    "logp",
    "pka",
    "polar_surface_area",
    "formal_charge",
    "experimental_water_solubility",
    "experimental_logp_hydrophobicity",
    "synthesis_reference",
    "wikipedia_link",
    "comment",
    "created_at",
    "updated_at"
]

with zipfile.ZipFile(ZIP_FILE, "r") as archive:

    json_files = [
        name for name in archive.namelist()
        if name.lower().endswith(".json")
    ]

    if not json_files:
        raise FileNotFoundError("No JSON file was found inside the ECMDB ZIP archive.")

    json_filename = json_files[0]

    print(f"JSON file inside archive: {json_filename}")

    with archive.open(json_filename) as json_file:
        data = json.load(json_file)

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csvfile:

    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    for metabolite in data:

        metabolite_count += 1

        writer.writerow({
            "ecmdb_id": metabolite.get("met_id", ""),
            "metabolite_name": metabolite.get("name", ""),
            "description": metabolite.get("description", ""),
            "cas": metabolite.get("cas", ""),
            "state": metabolite.get("state", ""),
            "melting_point": metabolite.get("melting_point", ""),
            "location": metabolite.get("location", ""),
            "category": metabolite.get("category", ""),

            # Cross-database identifiers
            "hmdb_id": metabolite.get("hmdb_id", ""),
            "chebi_id": metabolite.get("chebi_id", ""),
            "kegg_id": metabolite.get("kegg_id", ""),
            "pubchem_id": metabolite.get("pubchem_id", ""),
            "biocyc_id": metabolite.get("biocyc_id", ""),
            "foodb_id": metabolite.get("foodb_id", ""),
            "chemspider_id": metabolite.get("cs_id", ""),
            "m2m_id": metabolite.get("m2m_id", ""),
            "het_id": metabolite.get("het_id", ""),

            # Chemical structure and properties
            "chemical_formula": metabolite.get("moldb_formula", ""),
            "smiles": metabolite.get("moldb_smiles", ""),
            "inchi": metabolite.get("moldb_inchi", ""),
            "inchikey": metabolite.get("moldb_inchikey", ""),
            "iupac_name": metabolite.get("moldb_iupac", ""),
            "traditional_iupac_name": metabolite.get(
                "moldb_traditional_iupac", ""
            ),
            "average_molecular_mass": metabolite.get(
                "moldb_average_mass", ""
            ),
            "monoisotopic_molecular_mass": metabolite.get(
                "moldb_mono_mass", ""
            ),
            "logp": metabolite.get("moldb_logp", ""),
            "pka": metabolite.get("moldb_pka", ""),
            "polar_surface_area": metabolite.get(
                "moldb_polar_surface_area", ""
            ),
            "formal_charge": metabolite.get(
                "moldb_formal_charge", ""
            ),

            # Additional ECMDB metadata
            "experimental_water_solubility": metabolite.get(
                "experimental_water_solubility", ""
            ),
            "experimental_logp_hydrophobicity": metabolite.get(
                "experimental_logp_hydrophobicity", ""
            ),
            "synthesis_reference": metabolite.get(
                "synthesis_reference", ""
            ),
            "wikipedia_link": metabolite.get("wikipedia_link", ""),
            "comment": metabolite.get("comment", ""),
            "created_at": metabolite.get("created_at", ""),
            "updated_at": metabolite.get("updated_at", "")
        })

        if metabolite_count % 500 == 0:
            print(f"Processed {metabolite_count:,} metabolites")

print()
print(f"Metabolites processed: {metabolite_count:,}")
print(f"Output saved to: {OUTPUT_FILE}")