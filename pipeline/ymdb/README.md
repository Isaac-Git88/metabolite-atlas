# YMDB (yeast) pipeline

Concentration data for _Saccharomyces cerevisiae_ from the [Yeast Metabolome Database](https://www.ymdb.ca)
(Jewison et al. 2012, _Nucleic Acids Research_ 40:D815–D820).

## Why the concentrations are scraped

YMDB's official downloads do not contain the concentration data:

| Download                                           | Records                                               | Concentrations?                      |
| -------------------------------------------------- | ----------------------------------------------------- | ------------------------------------ |
| `ymdb.json` ("full database")                      | only 17 of 16,042 metabolites; file is malformed JSON | 2 values                             |
| `ymdb.sdf`                                         | 2,025 metabolites                                     | none (structure and properties only) |
| `protein_sequences.fasta` / `gene_sequences.fasta` | 995 proteins                                          | none                                 |

Concentrations only appear on each metabolite's page, so `extract_ymdb_concentrations.py` downloads every page's
XML version (`https://www.ymdb.ca/compounds/YMDBxxxxx.xml`) and extracts them.

## Steps

```
pip install requests

python pipeline/ymdb/ymdb_links.py                   # -> data/ymdb/ymdb_all_metabolite_links.csv
python pipeline/ymdb/extract_ymdb_concentrations.py all --workers 8
                                                      # -> data/ymdb/ymdb_concentrations_all.csv
```

The concentration step is slow: the YMDB server takes 10–60 s per page and returns 502 errors under load.
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

| Unit           | Rows  | Type                            |
| -------------- | ----- | ------------------------------- |
| µM, umol/L, uM | 1,433 | volumetric; all equal to µmol/L |
| umol/g DW      | 28    | per dry weight                  |
| nmol/mg        | 2     | per mass                        |

## Data files (`data/ymdb/`)

| File                            | Committed | Contents                                                                      |
| ------------------------------- | --------- | ----------------------------------------------------------------------------- |
| `ymdb_concentrations_all.csv`   | yes       | **the entry point**: one row per concentration measurement                    |
| `ymdb_all_metabolite_links.csv` | yes       | page and XML link for every ID YMDB00001–YMDB16500                            |
| `downloads/`                    | no        | the original YMDB download files; get them from https://www.ymdb.ca/downloads |
| `xml/`, `status.jsonl`          | no        | scrape working files; rebuild with `extract_ymdb_concentrations.py`           |
