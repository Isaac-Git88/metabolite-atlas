# BMDB (cow) pipeline

Concentration data for *Bos taurus* from the [Bovine Metabolome Database](https://bmdb.ca).

## No scraping needed

Unlike YMDB and ECMDB, BMDB's XML download carries concentrations, in the same
`<normal_concentrations>` block HMDB uses. Download `bmdb_metabolites.xml` from
<https://bmdb.ca/downloads> into `data/bmdb/` (the repo root also works). It is
gitignored (`*.xml`).

| | |
|---|---|
| Metabolites in the release | 51,689 (mostly predicted, no concentrations) |
| Metabolites with a concentration record | 2,840 |
| Concentration records | 15,192 — 12,865 with a value |
| After prepare (value present, not diseased, not excluded) | 12,802 rows, 2,099 metabolites |
| Comparable (µM) | 10,912 rows (85%) |

## How it differs from HMDB

- **No age, sex or condition fields.** Everything about the animal and the sample is in a
  free-text `<comment>`: diet ("fed barley grains (30% of diet dry matter)"), product
  ("Commercial 2% milk by LC-HRMS") or just the method ("By LC-MS/MS"). It is kept whole
  in `subject_condition`.
- **No HMDB cross-reference.** Identity across species comes from the InChIKey (98.6% of rows).
- **Biospecimens are cow-specific:** milk (62% of rows), rumen fluid, adipose tissue, blood,
  testis, liver and three muscle names, which are kept as BMDB gives them.
- **Three records are from mastitis-infected cows** despite sitting under
  `normal_concentrations`. `prepare_bmdb.py` drops them with an explicit keyword rule and
  prints each one.
- **One study is excluded whole** for impossible values: Abarghuei et al. 2014 (pomegranate-peel
  extract, 60 rows) reports blood cholesterol at ~4,000,000 µmol/L (~1,000× the bovine range) and
  milk palmitic acid at ~400,000 µmol/L. It is listed with its reason in `EXCLUDE_STUDIES` in
  `prepare_bmdb.py`; as in the Workbench pipeline, wrong-unit studies are dropped, not corrected.

## Open question

About 6,100 of the 8,010 milk rows are **commercial retail milk** (skim, 1%, 2%, 3.25%,
organic, UHT), not milk from individual cows. Whether processed milk belongs in a
"normal range" for the cow is a decision for the project, not the parser; those rows are
kept and are identifiable by their `subject_condition`.

## Steps

```
python pipeline/bmdb/extract_bmdb_concentrations.py   # XML -> data/bmdb/bmdb_concentrations_all.csv (~10 s)
python pipeline/bmdb/prepare_bmdb.py                  # -> data/bmdb/bmdb_concentrations_clean.csv
python pipeline/1_parse_concentrations.py --source BMDB
python pipeline/2_build_database.py
python pipeline/3_build_explorer.py
```

The shared parser (`pipeline/1_parse_concentrations.py`) reads 99.9% of BMDB values. The 7 it doesn't are `<LOQ` and `x +/- *`. Two units
are unclassified and so not comparable: `mg/100g dry matter content` (62 rows) and
`IU/100 g` (3).
