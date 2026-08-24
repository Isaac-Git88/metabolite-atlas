import csv

INPUT_FILE = "hmdb_normal_concentrations_raw.csv"
OUTPUT_FILE = "hmdb_normal_concentrations_clean.csv"

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
