# Cross-species metabolite concentration atlas

Reference ranges for metabolite concentrations, mined from public metabolomics
databases.

Most metabolomics studies report only the _relative_ change between control and
treated groups. The more useful question is usually whether a treatment pushes a
metabolite outside the range seen in healthy individuals — but for most
compounds, in most species, that normal range has never been collected in one
place. This project builds it.

**Current scope: four species databases — human (HMDB), cow (BMDB), yeast (YMDB)
and _E. coli_ (ECMDB) — plus control-group data from two study repositories,
Metabolomics Workbench (MWB) and MetaboLights (MTBLS),** which add human, cow, mouse and
five further species. Species is carried on every
measurement, and metabolite identity is structure-based (InChIKey), so a new
organism needs no schema change. HMDB and BMDB publish concentrations in their XML
downloads; YMDB and ECMDB do not, so both were scraped from their websites. The two
study repositories were surveyed for studies reporting real concentrations, and their
healthy/control groups and units reviewed by hand. See the README in each
`pipeline/<source>/` folder.

## What's here

|                |                                                       |
| -------------- | ----------------------------------------------------- |
| **9,865**      | reference ranges (species × metabolite × biospecimen) |
| **5,355**      | metabolites with a range                              |
| **10 / 1,419** | species, and structures measured in more than one     |
| **3,493**      | ranges supported by 3+ measurements                   |
| **40,145**     | measurements in the database                          |
| **1,801**      | source citations                                      |

| Species                                            | Ranges | Metabolites | Sources          |
| -------------------------------------------------- | ------ | ----------- | ---------------- |
| Human                                              | 4,518  | 3,087       | HMDB, MWB, MTBLS |
| Cow                                                | 2,775  | 2,079       | BMDB, MWB        |
| _E. coli_                                          | 891    | 891         | ECMDB            |
| Yeast                                              | 866    | 866         | YMDB             |
| Mouse                                              | 340    | 325         | MWB, MTBLS       |
| Sika deer, rat, rainbow trout, dog, rhesus macaque | 475    | —           | MWB              |

757 of the _E. coli_ metabolites are not in the human data at all. Cow ranges
cover milk, rumen fluid, blood, adipose tissue, liver, testis and muscle.

## Layout

```
RUNNING.md                how to run, update each source, and publish the site
requirements.txt          Python packages

pipeline/
  hmdb/  bmdb/  ymdb/  ecmdb/  mwb/  metabolights/
                          one folder per source: extract (or scrape) it, then
                          prepare it in the shared clean-CSV format
  1_parse_concentrations.py   shared step 1: free-text concentrations -> numbers
  2_build_database.py         shared step 2: parsed CSVs -> SQLite atlas
  3_build_explorer.py         shared step 3: atlas -> explorer/index.html

data/
  hmdb/  bmdb/  ymdb/  ecmdb/  mwb/  metabolights/
                          each source's inputs and clean CSV
  parsed/                 one parsed CSV per source (generated)
  metabolite_atlas.db     the atlas (generated)

explorer/   template.html (source) and index.html (generated site)
archive/v1/ superseded first-pass scripts, kept as project history
```

## Running the pipeline

Each source is prepared in its own folder under `pipeline/`, then goes through the
three shared steps:

```bash
pip install -r requirements.txt

python pipeline/bmdb/prepare_bmdb.py                # e.g. one source's prepare step
python pipeline/1_parse_concentrations.py --source BMDB
python pipeline/2_build_database.py                 # every parsed CSV -> data/metabolite_atlas.db
python pipeline/3_build_explorer.py                 # -> explorer/index.html
```

Step 2 rebuilds the database from whichever parsed CSVs exist and silently skips
missing ones, so parse every source first. The full sequence for all six sources,
re-downloading each source from scratch, and troubleshooting are in
[RUNNING.md](RUNNING.md). Each script anchors its own paths, so it runs from any
working directory.

## Data files

The clean CSVs the shared steps start from, the survey and review files of the two
study repositories (`data/mwb/`, `data/metabolights/`) and the generated site are
committed. Downloads and everything the
pipeline regenerates are gitignored, because git cannot diff binaries and
would re-commit them in full on every rebuild.

| File                                               | Committed | Notes                                           |
| -------------------------------------------------- | --------- | ----------------------------------------------- |
| `data/hmdb/hmdb_metabolites.xml`                   | no        | ~6.5 GB, from <https://hmdb.ca/downloads>       |
| `data/hmdb/hmdb_normal_concentrations_raw.csv`     | no        | 51,246 rows                                     |
| `data/hmdb/hmdb_normal_concentrations_clean.csv`   | **yes**   | 20,974 rows — HMDB's entry point                |
| `data/hmdb/hmdb_inchikey_lookup.csv`               | **yes**   | InChIKeys for HMDB metabolites                  |
| `data/bmdb/bmdb_metabolites.xml`                   | no        | ~450 MB, from <https://bovinedb.ca/downloads>   |
| `data/ymdb/ymdb_concentrations_all.csv`            | **yes**   | scraped; see `pipeline/ymdb/README.md`          |
| `data/ecmdb/ecmdb_concentrations_all.csv`          | **yes**   | scraped; see `pipeline/ecmdb/README.md`         |
| `data/mwb/mwb_concentrations_clean.csv`            | **yes**   | control groups after review                     |
| `data/metabolights/mtbls_concentrations_clean.csv` | **yes**   | control groups after review (8 studies)         |
| `data/metabolights/mtbls_control_review.csv`       | **yes**   | control-group and unit decisions per study      |
| `data/metabolights/isa/`                           | no        | downloaded study files; rebuild with the survey |
| `data/parsed/*_concentrations_parsed.csv`          | no        | numeric values + parse provenance               |
| `data/metabolite_atlas.db`                         | no        | the atlas                                       |
| `explorer/index.html`                              | **yes**   | self-contained site, served by GitHub Pages     |

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

See the docstring in `pipeline/2_build_database.py` for how the summary
statistics are computed and what they do and don't claim.

## Validation

Human blood medians (HMDB, Metabolomics Workbench and MetaboLights together),
against published reference intervals:

| Metabolite    | n   | Median (µmol/L) | Expected     |
| ------------- | --- | --------------- | ------------ |
| D-Glucose     | 40  | 4,750           | ~4.8 mM ✓    |
| Creatinine    | 45  | 62.5            | 60–110 µM ✓  |
| L-Lactic acid | 37  | 1,350           | ~1.35 mM ✓   |
| Urea          | 14  | 3,805           | ~3.8 mM ✓    |
| Uric acid     | 33  | 280             | 240–360 µM ✓ |
| L-Glutamine   | 46  | 580             | 500–750 µM ✓ |

Cobalamin's median of 0.0004 µmol/L looks wrong but is correct — B12 circulates
at sub-nanomolar concentrations.

Cow (BMDB), against typical dairy-cow values:

| Metabolite            | Biospecimen | n   | Median (µmol/L) | Expected                     |
| --------------------- | ----------- | --- | --------------- | ---------------------------- |
| D-Glucose             | Blood       | 13  | 3,808           | 2.5–4.2 mM ✓                 |
| 3-Hydroxybutyric acid | Blood       | 6   | 738             | < 1.2 mM (ketosis cut-off) ✓ |
| Acetic acid           | Rumen       | 16  | 56,325          | 50–70 mM ✓                   |
| Propionic acid        | Rumen       | 17  | 16,860          | 15–30 mM ✓                   |
| Butyric acid          | Rumen       | 16  | 9,383           | 8–15 mM ✓                    |
| Citric acid           | Milk        | 19  | 6,440           | 6–10 mM ✓                    |

## Adding another database

`pipeline/1_parse_concentrations.py` carries a registry of source databases and
the organism each describes, with NCBI taxonomy identifiers:

| Source | Species                            | Taxon         |
| ------ | ---------------------------------- | ------------- |
| HMDB   | _Homo sapiens_ (Human)             | 9606          |
| YMDB   | _Saccharomyces cerevisiae_ (Yeast) | 4932          |
| BMDB   | _Bos taurus_ (Cow)                 | 9913          |
| ECMDB  | _Escherichia coli_                 | 562           |
| MWB    | per study (Metabolomics Workbench) | from each row |
| MTBLS  | per study (MetaboLights)           | from each row |

The two study repositories carry many organisms, so their prepare scripts write the
species on every row and the registry leaves it to them.

To add one:

1. Create `pipeline/<source>/` with a script that writes
   `data/<source>/<source>_concentrations_clean.csv` in the shared column shape
   (`pipeline/bmdb/prepare_bmdb.py` is the simplest example).
2. Register it in `SOURCE_FILES` and `SOURCES` in `1_parse_concentrations.py`
   and in `CSV_PATHS` in `2_build_database.py`.
3. Add an update subsection to section 4 of `RUNNING.md`, and its prepare and parse commands to sections 5 and 6.

Species is recorded on every measurement rather than on the source, so
MetaboLights and Metabolomics Workbench — which carry many organisms per
repository — fit the same schema.

## Next

- Decide whether BMDB's commercial retail milk (~6,100 of 8,010 milk rows)
  belongs in the cow's normal range — see `pipeline/bmdb/README.md`.
- MetaboLights: 8 studies are in (611 values); the team still has to confirm the
  first-pass control and unit decisions, and 10 more studies need their units checked
  in the papers. See `pipeline/metabolights/README.md`.
