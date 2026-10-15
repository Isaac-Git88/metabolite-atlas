# HMDB (human) pipeline

Normal concentrations for _Homo sapiens_ from the [Human Metabolome Database](https://hmdb.ca),
the atlas's first and largest source.

## You usually don't need to run anything here

`data/hmdb/hmdb_normal_concentrations_clean.csv` is committed, and it is what the shared
steps read. These two scripts are only needed to refresh from a new HMDB release.

## Steps

```
# download hmdb_metabolites.xml (~6.5 GB) from https://hmdb.ca/downloads into data/hmdb/
python pipeline/hmdb/extract_hmdb.py     # XML -> data/hmdb/hmdb_normal_concentrations_raw.csv
python pipeline/hmdb/prepare_hmdb.py     # -> data/hmdb/hmdb_normal_concentrations_clean.csv
python pipeline/1_parse_concentrations.py --source HMDB
python pipeline/2_build_database.py
python pipeline/3_build_explorer.py
```

`extract_hmdb.py` streams the XML element by element, so memory stays flat, and writes one
row per reported concentration: 51,246 rows, including those with no value.
`prepare_hmdb.py` drops the ~59% that carry a citation but no number, leaving 20,974.

Unlike the other HMDB-family databases, HMDB records the subject's age, sex and condition
for each value, which the explorer's filters use.

## Files (`data/hmdb/`)

| File                                   | Committed |                                                                                                                              |
| -------------------------------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `hmdb_metabolites.xml`                 | no        | the download                                                                                                                 |
| `hmdb_normal_concentrations_raw.csv`   | no        | every concentration record                                                                                                   |
| `hmdb_normal_concentrations_clean.csv` | **yes**   | records with a value — the input to the shared steps                                                                         |
| `hmdb_inchikey_lookup.csv`             | **yes**   | InChIKey for each HMDB metabolite, used to match HMDB with the other sources (HMDB's concentration records do not carry one) |

These scripts were `pipeline/1_extract_hmdb.py` and `pipeline/2_remove_empty_concentrations.py`
before the October 2026 restructure.
