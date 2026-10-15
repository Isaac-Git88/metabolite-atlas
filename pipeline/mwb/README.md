# Metabolomics Workbench (MWB) pipeline — Part 2

Study-level concentration data from the [Metabolomics Workbench](https://www.metabolomicsworkbench.org),
the US NIH repository for metabolomics studies. Accessed through its public
[REST API](https://www.metabolomicsworkbench.org/tools/mw_rest.php); each analysis is downloaded as an
[mwTab](https://www.metabolomicsworkbench.org/data/mwTab_specification.pdf) file.

## Why this is harder than HMDB

|                  | HMDB / YMDB                        | Metabolomics Workbench                                                    |
| ---------------- | ---------------------------------- | ------------------------------------------------------------------------- |
| What a record is | one published normal concentration | one sample in one study                                                   |
| Units            | always concentrations              | mostly peak areas (relative); only targeted studies report concentrations |
| Healthy/control  | implied (normal concentrations)    | must be picked out of free-text sample factors                            |
| Names            | HMDB IDs                           | free-text; map through RefMet to InChIKey                                 |

## Plan

1. **Survey** (`survey_mwb.py`) — how many analyses report a concentration unit, by species and sample type.
2. **Extract** — for usable analyses, pull the data matrix and sample factors.
3. **Select controls** — keyword rules on sample factors; unclear groups flagged for review, not guessed.
4. **Standardise** — names via RefMet → InChIKey; mass units (ng/mL, mg/dL) → µmol/L using molecular weight.
5. **Collapse** — one representative value per study's control group, so a study counts once, as in HMDB.
6. **Validate** — compare against HMDB medians for the same metabolite and biospecimen.

## Step 1: survey

```
pip install requests
python pipeline/mwb/survey_mwb.py fetch --limit 50    # trial: listings + 50 mwTab files
python pipeline/mwb/survey_mwb.py fetch --workers 4   # all analyses with a concentration unit (resumable)
python pipeline/mwb/survey_mwb.py survey
```

The analysis listing already gives every analysis's UNITS, so the unit survey covers the whole
repository without downloading the data. Only analyses with a concentration unit have their full
mwTab file downloaded (`--all-units` downloads everything). Those files add the sample type and the
sample groups, which are needed to find controls.

Outputs in `data/mwb/`:

| File                                        | Committed | Contents                                                                                 |
| ------------------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `mwb_analysis_survey.csv`                   | yes       | one row per analysis: species, units, unit class; sample type and groups once downloaded |
| `mwb_unit_counts.csv`                       | yes       | every distinct UNITS string and how it was classified                                    |
| `mwtab/`, `status.jsonl`, `*.json` listings | no        | downloaded working files                                                                 |

Unit classes: `volumetric` (usable: µM, ng/mL, mg/dL…), `normalised` (per gram, protein, cell or creatinine),
`relative` (peak area, intensity, AUC, ratio), `amount` (nmol per vial or sample, no volume),
`not_a_value` (m/z, ppm), `missing`, `unknown`. Check `mwb_unit_counts.csv` and extend `UNIT_CLASSES`.

## First results (September 2026)

|                                                     | Analyses              | Share    |
| --------------------------------------------------- | --------------------- | -------- |
| Listed                                              | 7,540                 |          |
| Relative (peak area, intensity…)                    | 5,857                 | 77.7%    |
| **Volumetric concentration — usable**               | **579** (428 studies) | **7.7%** |
| Normalised (per gram / protein / cell / creatinine) | 520                   | 6.9%     |
| Other (amount, m/z, missing, unknown)               | 584                   | 7.7%     |

Usable analyses by species: human 286, mouse 119, rat 53, cow 15, rhesus macaque 10, others ≤ 8.
Most usable studies still need their control groups identified before any value enters the atlas.

## Step 3: select control groups

```
python pipeline/mwb/select_controls.py               # biofluids: blood, urine, CSF, saliva
python pipeline/mwb/select_controls.py --all-samples # also tissue, cells, faeces
```

Writes `data/mwb/mwb_control_review.csv` (committed): one row per analysis × sample group, with an automated
`suggestion` (control / not_control / unsure / qc) and its `reason`. Each factor of a group is judged on its own:
neutral factors (sample source, sex, age, timepoint…) are ignored, and a group is `control` only if every other
factor is control-like (control, healthy, vehicle, saline, wild type, placebo, sham, chow…). Quality-control pools,
blanks and standards are `qc` and never used.

The suggestion is a screen, not the decision: a person fills in the `decision` column
(`control` / `not_control` / `exclude`) for the control and unsure rows. Only `decision = control` goes on to
extraction. Re-running the script keeps decisions and notes already entered.

First screen (biofluids): 2,337 groups in 291 analyses from 206 studies — 263 control, 172 unsure,
1,807 not control, 95 QC; 171 analyses have something to review.

**Review (October 2026).** The 435 control/unsure groups were reviewed and given a decision, with the
reason in `notes`. The review also promoted 17 groups the rules had missed (e.g. "Sample Type: Control"). Result:
209 control groups in 131 analyses from 96 studies (blood 181, urine 21, saliva 6, CSF 1), 192 not control,
82 excluded. Excluded on purpose: tissue and peritoneal samples, pregnancy, acute exercise or fed states,
single-group cohorts with unknown health status, and pooled reference material (NIST SRM 1950, CHEAR) pending
a team decision. The file as it was before the review is kept as `mwb_control_review.before_review.csv`.

## Step 4: extract the control data into the atlas

```
python pipeline/mwb/prepare_mwb.py names     # match names to structures (asks RefMet; cached, resumable)
python pipeline/mwb/prepare_mwb.py build     # control samples -> umol/L -> one value per study
python pipeline/1_parse_concentrations.py --source MWB
python pipeline/2_build_database.py
python pipeline/3_build_explorer.py
```

**Names → structure.** Only ~1% of MWB metabolite rows carry an InChIKey and ~9% an HMDB ID; the rest are
free-text names (e.g. `1MH_1-Methylhistidine`). Each name is matched, in order, by: the study's own InChIKey,
its HMDB ID (→ `hmdb_inchikey_lookup.csv`), an exact match of the cleaned name to an HMDB name, then RefMet
(the repository's name standard → formula and, via PubChem, an InChIKey). Unmatched names are left out, so every
MWB row merges with HMDB, YMDB and ECMDB on an exact InChIKey, the same rule as the other sources.
The result for every name is in `data/mwb/mwb_name_map.csv`.

**Units.** Everything is converted to µmol/L. Molar units are a fixed scaling; mass units (ng/mL, mg/dL) are
divided by the molar mass computed from the formula. Analyses that mix units in one column, or report logs,
are left out.

**One value per study.** All control samples of a study are pooled and summarised as `mean +/- SD (min - max)`,
which the shared parser reads like an HMDB entry. If several analyses of a study report the same metabolite,
the one with the most samples is used, so each study counts once per metabolite and biospecimen.

**Unit check.** Each human study is compared with HMDB on the metabolites both report. A study with ≥10 shared
metabolites whose typical value is >30-fold from HMDB is left out as a likely unit-label error (ST001490 labels
µM values "mM": 549-fold high across 181 metabolites). All results: `data/mwb/mwb_study_check.csv`.

**Checks after the full run (October 2026).** With RefMet name matching: 85 studies before checks.
Left out after checks: 8 studies, each with its reason in `data/mwb/mwb_study_check.csv` (6 found by
inspecting each study's largest values and listed in `EXCLUDE_STUDIES` in the script, 2 by the automatic
comparison with HMDB), and 39 single values more than 1000-fold from HMDB or above 200 mmol/L
(`data/mwb/mwb_value_check.csv`). The value check is cautious, not perfect: in a few cases HMDB is the outlier
(e.g. HMDB lists thyroxine at 0.00002 umol/L; MWB's ~0.1 umol/L is the physiological value), so some correct
values are lost. Plasma ATP/ADP (nanomolar) is also dropped because HMDB's "Blood" values are whole blood.

Result: 3,108 values from 79 studies, 927 metabolites; human, mouse, sika deer, cow, rat, rainbow trout,
dog and rhesus macaque; blood 2,714, urine 313, saliva 63, CSF 18.
