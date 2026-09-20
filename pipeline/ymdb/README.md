# YMDB (yeast) pipeline

Concentration data for *Saccharomyces cerevisiae* from the [Yeast Metabolome Database](https://www.ymdb.ca)
(Jewison et al. 2012, *Nucleic Acids Research* 40:D815–D820).

## Why the concentrations are scraped

YMDB's official downloads do not contain the concentration data:

| Download | Records | Concentrations? |
|---|---|---|
| `ymdb.json` ("full database") | only 17 of 16,042 metabolites; file is malformed JSON | 2 values |
| `ymdb.sdf` | 2,025 metabolites | none (structure and properties only) |
| `protein_sequences.fasta` / `gene_sequences.fasta` | 995 proteins | none |

Concentrations only appear on each metabolite's page, so step 2 downloads every page's
XML version (`https://www.ymdb.ca/compounds/YMDBxxxxx.xml`) and extracts them.

## Steps

```
pip install pandas requests

python pipeline/ymdb/0_extract_ymdb_downloads.py      # downloads -> CSVs (JSON, SDF, FASTA)
python pipeline/ymdb/ymdb_links.py                   # -> data/ymdb/ymdb_all_metabolite_links.csv
python pipeline/ymdb/extract_ymdb_concentrations.py all --workers 8
                                                      # -> data/ymdb/ymdb_concentrations_all.csv
```

Step 2 is slow: the YMDB server takes 10–60 s per page and returns 502 errors under load.
The full run (16,500 IDs) took about 10 hours. It is resumable, so it can be stopped and
restarted. `extract` alone rebuilds the CSV from the saved pages in about 10 seconds.

## Result (scraped September 2026)

- 16,500 IDs checked: 16,040 metabolite pages, 458 IDs that do not exist, and 2 pages that
  return a server error on YMDB's side (YMDB16144, YMDB16155; their JSON shows no concentrations).
  That gives 16,042 metabolites, which matches YMDB's statistics page.
- **1,463 concentration measurements for 870 metabolites.** YMDB states 1,462 across 873.
- The data is kept exactly as YMDB publishes it. 3 rows appear twice on YMDB itself,
  3 potassium rows have no growth media, and 562 rows have no reference.

## Units

Units are recorded as published, not converted:

| Unit | Rows | Type |
|---|---|---|
| µM, umol/L, uM | 1,433 | volumetric; all equal to µmol/L |
| umol/g DW | 28 | per dry weight |
| nmol/mg | 2 | per mass |

## Data files (`data/ymdb/`)

| File | Contents |
|---|---|
| `ymdb_concentrations_all.csv` | **the entry point**: one row per concentration measurement |
| `ymdb_all_metabolite_links.csv` | page and XML link for every ID YMDB00001–YMDB16500 |
| `ymdb_sdf_full.csv` | the SDF, all fields plus the MOL block |
| `ymdb_json_full.csv.gz` | the JSON, all fields (gzipped; pandas reads it directly) |
| `json_tables/` | the JSON split into linked tables |
| `ymdb_protein_sequences.csv`, `ymdb_gene_sequences.csv` | the FASTA files |
| `downloads/` | the original YMDB download files |
