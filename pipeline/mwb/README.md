# Metabolomics Workbench (MWB) pipeline — Part 2

Study-level concentration data from the [Metabolomics Workbench](https://www.metabolomicsworkbench.org),
the US NIH repository for metabolomics studies. Accessed through its public
[REST API](https://www.metabolomicsworkbench.org/tools/mw_rest.php); each analysis is downloaded as an
[mwTab](https://www.metabolomicsworkbench.org/data/mwTab_specification.pdf) file.

## Why this is harder than HMDB

| | HMDB / YMDB | Metabolomics Workbench |
|---|---|---|
| What a record is | one published normal concentration | one sample in one study |
| Units | always concentrations | mostly peak areas (relative); only targeted studies report concentrations |
| Healthy/control | implied (normal concentrations) | must be picked out of free-text sample factors |
| Names | HMDB IDs | free-text; map through RefMet to InChIKey |

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

| File | Committed | Contents |
|---|---|---|
| `mwb_analysis_survey.csv` | yes | one row per analysis: species, units, unit class; sample type and groups once downloaded |
| `mwb_unit_counts.csv` | yes | every distinct UNITS string and how it was classified |
| `mwtab/`, `status.jsonl`, `*.json` listings | no | downloaded working files |

Unit classes: `volumetric` (usable: µM, ng/mL, mg/dL…), `normalised` (per gram, protein, cell or creatinine),
`relative` (peak area, intensity, AUC, ratio), `amount` (nmol per vial or sample, no volume),
`not_a_value` (m/z, ppm), `missing`, `unknown`. Check `mwb_unit_counts.csv` and extend `UNIT_CLASSES`.

## First results (September 2026)

| | Analyses | Share |
|---|---|---|
| Listed | 7,540 | |
| Relative (peak area, intensity…) | 5,857 | 77.7% |
| **Volumetric concentration — usable** | **579** (428 studies) | **7.7%** |
| Normalised (per gram / protein / cell / creatinine) | 520 | 6.9% |
| Other (amount, m/z, missing, unknown) | 584 | 7.7% |

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
