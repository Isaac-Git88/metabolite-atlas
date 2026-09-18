# Cross-species metabolite concentration atlas

Reference ranges for metabolite concentrations, mined from public metabolomics
databases.

Most metabolomics studies report only the *relative* change between control and
treated groups. The more useful question is usually whether a treatment pushes a
metabolite outside the range seen in healthy individuals — but for most
compounds, in most species, that normal range has never been collected in one
place. This project builds it.

**Current scope: human (HMDB).** Yeast (YMDB), bovine (BMDB) and *E. coli*
(ECMDB) are next; they share HMDB's schema, so the pipeline is designed to
extend to them.

## What's here

| | |
|---|---|
| **4,048** | reference ranges (metabolite × biospecimen) |
| **2,874** | metabolites with a range |
| **1,384** | ranges supported by 3+ independent studies |
| **20,974** | measurements in the database |
| **1,625** | source citations |

## Layout

```
data/       inputs and generated data (see "Data files" below)
pipeline/   the five steps, numbered in run order
explorer/   template.html (source) and index.html (generated site)
archive/v1/ superseded first-pass scripts, kept as project history
```

## Running the pipeline

```bash
pip install pandas

python pipeline/1_extract_hmdb.py                 # XML  -> raw CSV   (slow, ~6.5 GB input)
python pipeline/2_remove_empty_concentrations.py  # raw  -> clean CSV
python pipeline/3_parse_concentrations.py         # text -> numbers
python pipeline/4_build_database.py               # CSV  -> SQLite
python pipeline/5_build_explorer.py               # DB   -> explorer/index.html
```

Each script anchors its own paths, so it runs from any working directory.

**Starting from step 2** is normal: `data/hmdb_normal_concentrations_clean.csv`
is committed, so you can rebuild everything without the 6.5 GB XML. Step 1 is
only needed to refresh from a new HMDB release — download it from
<https://hmdb.ca/downloads> into `data/`.

## Data files

Only the clean CSV and the generated site are committed. Everything else in
`data/` is reproducible and gitignored, because git cannot diff binaries and
would re-commit them in full on every rebuild.

| File | Committed | Notes |
|---|---|---|
| `hmdb_metabolites.xml` | no | ~6.5 GB, download separately |
| `hmdb_normal_concentrations_raw.csv` | no | 51,246 rows |
| `hmdb_normal_concentrations_clean.csv` | **yes** | 20,977 rows — the entry point |
| `hmdb_concentrations_parsed.csv` | no | numeric values + parse provenance |
| `metabolite_atlas.db` | no | the atlas |
| `explorer/index.html` | **yes** | self-contained site, served by GitHub Pages |

## Two decisions worth knowing

**Units are classified, not converted.** HMDB reports concentrations in five
units spanning three measurement types: volume-based (µM), creatinine-normalised
(µmol/mmol creatinine) and mass-normalised (nmol/g feces). No conversion exists
between them — it would need per-subject creatinine excretion or per-sample water
content, neither of which HMDB records. So comparability is recorded as a
property of each unit: 12,067 volumetric records are comparable and expressed as
µmol/L, and the remaining 8,907 stay in the database but are excluded from
concentration plots. µM → µmol/L is a relabelling, not a conversion: the two are
identical, so no arithmetic is applied to any value.

**Parsing is explicit, and never guesses.** 99.9% of concentration strings parse
into numbers. The 13 that don't are malformed in HMDB itself (`0.3.4`,
`1.0 +/- 1/0`) and are retained with `parse_ok = 0`. A further 1,394 rows parse
but are flagged `needs_review` — censored bounds, unlabelled brackets read as an
SD, ranges written high-to-low. Four values had been corrupted into dates by a
spreadsheet somewhere upstream (`13-Feb` was originally `13-2`); these are
recovered and flagged.

See the docstring in `pipeline/4_build_database.py` for how the summary
statistics are computed and what they do and don't claim.

## Validation

Parsed medians in blood, against published reference intervals:

| Metabolite | n | Median (µmol/L) | Expected |
|---|---|---|---|
| D-Glucose | 34 | 4,787 | ~4.8 mM ✓ |
| Creatinine | 34 | 61.2 | 60–110 µM ✓ |
| L-Lactic acid | 29 | 1,350 | ~1.35 mM ✓ |
| Urea | 14 | 3,805 | ~3.8 mM ✓ |
| Uric acid | 29 | 280 | 240–360 µM ✓ |
| L-Glutamine | 28 | 580 | 500–750 µM ✓ |

Cobalamin's median of 0.0004 µmol/L looks wrong but is correct — B12 circulates
at sub-nanomolar concentrations.

## Next

- A `species` dimension, then YMDB, BMDB and ECMDB — what makes this a
  cross-species atlas rather than a view of HMDB.
- Compare several metabolites within one biospecimen; look up a measured value
  against its normal range.
- Part 2 of the brief: MetaboLights and Metabolomics Workbench.
