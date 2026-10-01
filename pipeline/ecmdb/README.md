# ECMDB (E. coli) pipeline

Concentration data for *Escherichia coli* from the [E. coli Metabolome Database](https://ecmdb.ca).

## Why the concentrations are scraped

Like YMDB, ECMDB's download files carry no measured concentrations:

| Download | Records | Concentrations? |
|---|---|---|
| `ecmdb.json` | 3,760 metabolites | none — identifiers, structures and properties only |
| `ecmdb.sdf` | the same 3,760 | none |

The `.sdf` download is also not an SDF: it is a sequence of 3,760 JSON arrays, each
holding one record's lines as separate strings. It has to be rebuilt into SDF text
before any chemistry toolkit can read it.

Concentrations appear only on each compound's page, so `extract_ecmdb_concentrations.py`
reads the XML version of every page (`https://ecmdb.ca/compounds/ECMDBxxxxx.xml`).
No ID guessing is needed here: `ecmdb.json` lists every compound.

## Steps

```
pip install requests

python pipeline/ecmdb/prepare_ecmdb.py          # scraped CSV -> the shared clean format
python pipeline/1_parse_concentrations.py --source ECMDB
python pipeline/2_build_database.py
python pipeline/3_build_explorer.py
```

To re-scrape (the saved pages are gitignored):

```
python pipeline/ecmdb/extract_ecmdb_concentrations.py all --workers 4
```

ECMDB's server starts fast and then returns 504s under load; 8 workers triggered
that, 4 held at roughly 11–100 pages a minute. The run is resumable and caches every
page, so `extract` alone rebuilds the CSV in seconds.

## Result (scraped September 2026)

- 3,760 compound pages checked, 3,753 read. Seven return 500/504 errors on ECMDB's
  side and could not be fetched (ECMDB00494, ECMDB21225, ECMDB24010, ECMDB24017,
  ECMDB24036, ECMDB24040, ECMDB24045).
- **1,187 measurements for 891 metabolites**, all in µM, all with a citation and a
  strain, and none needing interpretation when parsed.
- 478 measurements also carry molecules per cell, which is kept in the scraped CSV.

## What ECMDB records that the others don't

Every measurement names its growth medium, growth system (shake flask, bioreactor),
temperature, strain and growth phase. For a single-celled organism those conditions
are what the concentration depends on, so `prepare_ecmdb.py` carries them into the
subject columns: growth system as age, strain as sex, and medium with growth phase
as condition. The medium is shortened to its carbon source for display; the full
recipe stays in `ecmdb_concentrations_all.csv`.

## Identity

Every one of the 891 metabolites has an InChIKey, but only 460 measurements carry an
HMDB cross-reference, so the structure-based identity in `2_build_database.py` is what
lets this source load at all. Overlap with the rest of the atlas: 140 metabolites are
shared with human, 73 with yeast, and 70 appear in all three species.

## Data files (`data/ecmdb/`)

| File | Committed | Contents |
|---|---|---|
| `ecmdb_concentrations_all.csv` | yes | **the entry point**: one row per measurement, with the full growth conditions |
| `ecmdb_metabolites.csv`, `ecmdb_sdf_full.csv` | no | extracts of the downloads; rebuildable |
| `xml/`, `status.jsonl` | no | scrape working files |
