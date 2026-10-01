# Cross-species metabolite concentration atlas

Reference ranges for metabolite concentrations, mined from public metabolomics
databases.

Most metabolomics studies report only the _relative_ change between control and
treated groups. The more useful question is usually whether a treatment pushes a
metabolite outside the range seen in healthy individuals — but for most
compounds, in most species, that normal range has never been collected in one
place. This project builds it.

**Current scope: four species databases — human (HMDB), cow (BMDB), yeast (YMDB)
and _E. coli_ (ECMDB) — plus control-group data from Metabolomics Workbench (MWB),**
which adds human, cow and six further species. Species is carried on every
measurement, and metabolite identity is structure-based (InChIKey), so a new
organism needs no schema change. HMDB and BMDB publish concentrations in their XML
downloads; YMDB and ECMDB do not, so both were scraped from their websites — see
the README in each `pipeline/<source>/` folder.

## What's here

|            |                                                      |
| ---------- | ---------------------------------------------------- |
| **9,770**   | reference ranges (species × metabolite × biospecimen) |
| **5,326**   | metabolites with a range                             |
| **10 / 1,401** | species, and structures measured in more than one |
| **3,455**   | ranges supported by 3+ measurements                  |
| **39,534**  | measurements in the database                         |
| **1,801**   | source citations                                     |

| Species | Ranges | Metabolites | Sources |
| ------- | ------ | ----------- | ------- |
| Human   | 4,469  | 3,046       | HMDB, MWB |
| Cow     | 2,775  | 2,079       | BMDB, MWB |
| _E. coli_ | 891  | 891         | ECMDB |
| Yeast   | 866    | 866         | YMDB |
| Mouse, sika deer, rat, rainbow trout, dog, rhesus macaque | 769 | — | MWB |

757 of the _E. coli_ metabolites are not in the human data at all. Cow ranges
cover milk, rumen fluid, blood, adipose tissue, liver, testis and muscle.

## Layout

```
data/       inputs and generated data (see "Data files" below)
pipeline/   the five steps, numbered in run order
pipeline/bmdb/  the cow source: extract from the XML, then prepare for step 3
pipeline/ymdb/  the yeast source: scrape, then prepare for step 3
pipeline/ecmdb/ the E. coli source: same two steps
pipeline/mwb/   Metabolomics Workbench: survey, download, select controls, prepare
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

Steps 1–3 above are for HMDB. Each other source has its own prepare step (see
its folder's README) and is then parsed with `--source`:

```bash
python pipeline/bmdb/extract_bmdb_concentrations.py   # needs bmdb_metabolites.xml
python pipeline/bmdb/prepare_bmdb.py
python pipeline/ymdb/prepare_ymdb.py
python pipeline/ecmdb/prepare_ecmdb.py
for s in BMDB YMDB ECMDB MWB; do python pipeline/3_parse_concentrations.py --source $s; done
```

Step 4 deletes and rebuilds the database from whichever
`data/*_concentrations_parsed.csv` files exist, and silently skips missing ones.
Parse every source before running it, or the atlas (and the site step 5 writes)
will be missing species.

**Starting from step 2** is normal: `data/hmdb_normal_concentrations_clean.csv`
is committed, so you can rebuild everything without the 6.5 GB XML. Step 1 is
only needed to refresh from a new HMDB release — download it from
<https://hmdb.ca/downloads> into `data/`.

## Data files

Only the clean CSV and the generated site are committed. Everything else in
`data/` is reproducible and gitignored, because git cannot diff binaries and
would re-commit them in full on every rebuild.

| File                                   | Committed | Notes                                       |
| -------------------------------------- | --------- | ------------------------------------------- |
| `hmdb_metabolites.xml`                 | no        | ~6.5 GB, download separately                |
| `bmdb_metabolites.xml`                 | no        | ~450 MB, from <https://bmdb.ca/downloads>   |
| `hmdb_normal_concentrations_raw.csv`   | no        | 51,246 rows                                 |
| `hmdb_normal_concentrations_clean.csv` | **yes**   | 20,977 rows — the entry point               |
| `hmdb_concentrations_parsed.csv`       | no        | numeric values + parse provenance           |
| `metabolite_atlas.db`                  | no        | the atlas                                   |
| `explorer/index.html`                  | **yes**   | self-contained site, served by GitHub Pages |

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

| Metabolite    | n   | Median (µmol/L) | Expected     |
| ------------- | --- | --------------- | ------------ |
| D-Glucose     | 34  | 4,787           | ~4.8 mM ✓    |
| Creatinine    | 34  | 61.2            | 60–110 µM ✓  |
| L-Lactic acid | 29  | 1,350           | ~1.35 mM ✓   |
| Urea          | 14  | 3,805           | ~3.8 mM ✓    |
| Uric acid     | 29  | 280             | 240–360 µM ✓ |
| L-Glutamine   | 28  | 580             | 500–750 µM ✓ |

Cobalamin's median of 0.0004 µmol/L looks wrong but is correct — B12 circulates
at sub-nanomolar concentrations.

Cow (BMDB), against typical dairy-cow values:

| Metabolite             | Biospecimen | n  | Median (µmol/L) | Expected                    |
| ---------------------- | ----------- | -- | --------------- | --------------------------- |
| D-Glucose              | Blood       | 13 | 3,808           | 2.5–4.2 mM ✓                |
| 3-Hydroxybutyric acid  | Blood       | 6  | 738             | < 1.2 mM (ketosis cut-off) ✓ |
| Acetic acid            | Rumen       | 16 | 56,325          | 50–70 mM ✓                  |
| Propionic acid         | Rumen       | 17 | 16,860          | 15–30 mM ✓                  |
| Butyric acid           | Rumen       | 16 | 9,383           | 8–15 mM ✓                   |
| Citric acid            | Milk        | 19 | 6,440           | 6–10 mM ✓                   |

## Adding another database

`pipeline/3_parse_concentrations.py` carries a registry of source databases and
the organism each describes, with NCBI taxonomy identifiers:

| Source | Species                            | Taxon |
| ------ | ---------------------------------- | ----- |
| HMDB   | _Homo sapiens_ (Human)             | 9606  |
| YMDB   | _Saccharomyces cerevisiae_ (Yeast) | 4932  |
| BMDB   | _Bos taurus_ (Cow)                 | 9913  |
| ECMDB  | _Escherichia coli_                 | 562   |

Extract the new source to a clean CSV in the same column shape (see
`pipeline/bmdb/prepare_bmdb.py` for the simplest example), register it in
`SOURCE_FILES` and `SOURCES` in step 3 and `CSV_PATHS` in step 4, then:

    python pipeline/3_parse_concentrations.py --source <NAME>

Concatenate the parsed CSVs and run steps 4 and 5. Species is recorded on every
measurement rather than on the source, so MetaboLights and Metabolomics
Workbench — which carry many organisms per repository — fit the same schema.

## Next

- Decide whether BMDB's commercial retail milk (~6,100 of 8,010 milk rows)
  belongs in the cow's normal range — see `pipeline/bmdb/README.md`.
- MetaboLights, the second repository in Part 2 of the brief.
