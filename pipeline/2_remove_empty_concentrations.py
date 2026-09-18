"""
Step 2 -- drop records that carry a citation but no concentration value.

About 59% of HMDB's normal_concentrations entries have a reference attached but
no number, so they cannot contribute to a range. 51,246 rows in, 20,977 out.

Input:  data/hmdb_normal_concentrations_raw.csv
Output: data/hmdb_normal_concentrations_clean.csv

Usage:
    python pipeline/2_remove_empty_concentrations.py
"""

import csv
from pathlib import Path

# Paths are anchored to this script's own folder, so every step runs correctly
# from any working directory. Inputs and generated data live in data/, the
# website in explorer/.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
EXPLORER = ROOT / "explorer"

INPUT_FILE = DATA / "hmdb_normal_concentrations_raw.csv"
OUTPUT_FILE = DATA / "hmdb_normal_concentrations_clean.csv"

total_rows = 0
kept_rows = 0
removed_rows = 0

with open(INPUT_FILE, "r", encoding="utf-8", newline="") as infile, \
     open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as outfile:

    reader = csv.DictReader(infile)
    writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)

    writer.writeheader()

    for row in reader:
        total_rows += 1

        # Remove the entire row if concentration is empty
        if not row["concentration_value_raw"].strip():
            removed_rows += 1
            continue

        writer.writerow(row)
        kept_rows += 1
