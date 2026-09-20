"""
ymdb_links.py
Build the list of YMDB metabolite page links (ymdb_all_metabolite_links.csv).

YMDB IDs follow the pattern YMDB00001, YMDB00002, ... but the numbering has
gaps, and the site cannot list every ID. So this script generates every ID in
a range and marks which ones are confirmed by the YMDB download files
(ymdb.sdf / ymdb.json). IDs that do not exist return 404 later and are
skipped by extract_ymdb_concentrations.py.

Usage (from anywhere; paths are anchored to the repo):
    python pipeline/ymdb/ymdb_links.py

Output: data/ymdb/ymdb_all_metabolite_links.csv
"""
import argparse
import csv
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "ymdb")

parser = argparse.ArgumentParser()
parser.add_argument("--sdf", default=os.path.join(DATA, "ymdb_sdf_full.csv"),
                    help="optional: CSV made from ymdb.sdf (columns YMDB_ID, GENERIC_NAME), used to fill in names")
parser.add_argument("--max-id", type=int, default=16500,
                    help="highest ID number to generate (YMDB's highest real ID is about 16300)")
parser.add_argument("--out", default=os.path.join(DATA, "ymdb_all_metabolite_links.csv"))
args = parser.parse_args()

# Names of metabolites confirmed by the download files (optional)
names = {}
if os.path.exists(args.sdf):
    with open(args.sdf, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            names[row["YMDB_ID"]] = row.get("GENERIC_NAME", "")
    print(f"Loaded {len(names)} known metabolites from {args.sdf}")
else:
    print(f"{args.sdf} not found - generating links without names")

with open(args.out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["ymdb_id", "name", "confirmed_in_download_files", "page_url", "xml_url"])
    for n in range(1, args.max_id + 1):
        ymdb_id = f"YMDB{n:05d}"
        w.writerow([
            ymdb_id,
            names.get(ymdb_id, ""),
            "yes" if ymdb_id in names else "unknown",
            f"https://www.ymdb.ca/compounds/{ymdb_id}",
            f"https://www.ymdb.ca/compounds/{ymdb_id}.xml",
        ])

print(f"Wrote {args.max_id} links to {args.out}")
