# MetaboLights pipeline — Part 2

Study-level data from [MetaboLights](https://www.ebi.ac.uk/metabolights/), EMBL-EBI's
metabolomics repository. It's the second repository in Part 2 of the brief, after Metabolomics
Workbench (`pipeline/mwb/`), and it follows the same plan: survey first, then extract
control groups only if enough studies report real concentrations.

## Why it's harder than Metabolomics Workbench

| | Metabolomics Workbench | MetaboLights |
|---|---|---|
| Format | mwTab (one file per analysis, JSON available) | ISA-Tab: investigation, sample, assay and MAF files |
| Units | a `UNITS` field on every analysis | **no units field**; stated (if at all) in the description or protocols |
| Values | data matrix in the mwTab | MAF (metabolite assignment file): metabolites × samples |
| Identifiers | free-text names → RefMet | MAF carries ChEBI IDs, and often SMILES / InChI |
| Healthy/control | sample factors | `Factor Value[...]` columns of the sample sheet |

The missing units field is the main problem. Concentration studies can only be found by
reading each study's text, so step 1 is a keyword screen that a person then reviews.
ChEBI IDs and InChI are the easier part: they should map to InChIKeys more reliably than MWB's free-text names.

## Step 1: survey

```
pip install requests
python pipeline/metabolights/survey_metabolights.py check               # can we reach MetaboLights?
python pipeline/metabolights/survey_metabolights.py fetch --limit 20    # trial
python pipeline/metabolights/survey_metabolights.py fetch --workers 4   # all public studies (resumable)
python pipeline/metabolights/survey_metabolights.py survey
python pipeline/metabolights/survey_metabolights.py fetch --maf         # MAFs for likely/possible studies only
python pipeline/metabolights/survey_metabolights.py survey              # again, with MAF row counts
```

`fetch` downloads only the small metadata files (`i_`, `s_`, `a_`) of every public study,
from the public FTP folder served over HTTPS. MAFs can be large, so they are only downloaded
with `--maf`, and only for studies the screen marks `likely` or `possible`.

**The concentration screen** has two stages.

1. **Text** (`text_screen`), from the title, description, protocols and design types:
   - `likely`: a concentration unit stated as a *result*, next to wording such as "expressed in",
     "calculated in", "presented as" or "absolute" (e.g. "concentrations … were calculated in mM per litre");
   - `possible`: a targeted design with quantification wording (calibration curve, absolute
     quantification), or a unit mention in a study that does not call itself untargeted;
   - `unlikely`: otherwise. A study describing itself as untargeted, relative or peak-area based
     needs a result unit to pass.

   Unit mentions within 50 characters of a reagent, standard or treatment word are ignored
   ("10 mM ammonium formate", "50 nM acetaminophen (internal standard)", "treated with 5 µM
   atorvastatin"). The molar forms are case-sensitive, so lengths ("1.7 µm", "254 nm") never count.

2. **Values** (`maf_check`), once `fetch --maf` has downloaded the MAFs: if the median positive
   sample value is above 10,000, the file holds peak areas or intensities, and the study is set to
   `unlikely` whatever its text says. If the MAF holds no numbers at all, the study is set to
   `no_values`: the values were never deposited, so there is nothing to extract.
   `concentration_screen` is the final verdict after both stages.

**Trial (October 2026, 25 random studies + MTBLS1).** The first version of the screen flagged 12
studies; reading them showed only 2–3 hold concentrations. The others had picked up treatment doses,
internal standards and reagents, and their MAFs had median values from 15,000 to 39,000,000 (peak
areas). After the rules above, the screen gives 2 `likely` (MTBLS1894: synovial fluid by NMR, in mM;
MTBLS143: mouse lipids, µM in plasma), 1 `possible` (MTBLS434: targeted yeast amino acids with
calibration standards) and 22 `unlikely`, which matches a manual review of all 25. Known
limitation: a quantitative study that never states its unit in the text (e.g. MTBLS151, "Quantitative
1H NMR" of rice) is marked `unlikely`.

Outputs in `data/metabolights/`:

| File | Contents |
|---|---|
| `mtbls_study_survey.csv` | one row per study: organism, organism part, design, both screen stages and the final verdict, units found, sample groups, MAF row counts and median value |
| `mtbls_organisms.csv` | studies per organism and screen result |
| `isa/`, `status.jsonl`, `studies.json` | downloaded working files (gitignored) |

## Status

**Full run, October 2026.** All public studies were surveyed (3,507 listed; 3,505 downloaded,
MTBLS15156 and MTBLS15262 fail to download on MetaboLights' side), and the MAFs of the 370
studies the text screen flagged were fetched.

| Stage | Studies |
|---|---|
| Public studies surveyed | 3,507 |
| Text screen: likely or possible | 370 |
| ...MAF holds peak areas (median > 10,000), moved to `unlikely` | 62 |
| ...MAF holds no numbers at all (`no_values`: values only in the paper) | 172 |
| **Final `likely` + `possible`** | **136** (23 likely, 113 possible) |
| ...from a mammal | 84 |
| ...in a biofluid (blood, plasma, serum, urine, feces, saliva, BALF, milk…) | **58** |
| ...with a sample group named like a control | **24** |

So MetaboLights is a much smaller source than its size suggests: about 4% of studies hold
values that could be concentrations, and under 2% are mammalian biofluid studies. `could_be_concentration`
only rules out peak areas; each candidate's unit still has to be confirmed by reading its
description and MAF, as in the Workbench review. Notable candidates include MTBLS2104
(physiological extremes of the human blood metabolome), the MaHPIC macaque plasma studies
(MTBLS691, 821, 822, 824) and several targeted bile-acid and amino-acid panels.

## Step 2: select control groups and confirm units

```
python pipeline/metabolights/select_controls.py                # biofluids: blood, urine, CSF, saliva
python pipeline/metabolights/select_controls.py --all-samples  # also feces, tissue, cells, other fluids
```

Writes `data/metabolights/mtbls_control_review.csv`: one row per candidate study × sample group,
for mammalian `likely`/`possible` studies. Each group gets an automated `suggestion`
(control / not_control / unsure / qc) and its `reason`, using the **same rules as the Workbench
review** (`pipeline/mwb/select_controls.py`) so both sources are judged alike. Three adjustments
for MetaboLights:

- **Groups come from design factors only.** MetaboLights studies often record per-person details
  (age, sex, BMI, patient ID, symptom yes/no flags) as factors, which made every participant a
  group of one (2,045 groups). Such factors are left out of the grouping (303 groups).
- **Extra control wording:** air-exposure controls ("conditioned fresh air"), the abbreviations
  CON, CTR and HC, and factors named "control" with value TRUE.
- **Misreadings fixed:** "STD" in a diet factor is standard diet, not a QC standard, and design
  factors with a timing word in their name (e.g. "TreatPhase1") are no longer skipped.

**Because MetaboLights has no unit field, each row also carries the study's unit evidence:** the
units the text screen counted as results, the sentence they came from (`unit_evidence`), and the
median MAF value. The reviewer fills in two columns:

- `unit_confirmed`, once per study: the unit of the MAF values (e.g. `umol/L`, `nmol/mL`,
  `ng/mL`), or `relative` / `unclear` if they are not concentrations;
- `decision` for the control and unsure rows: `control` / `not_control` / `exclude`.

Only groups with `decision = control` and a concentration unit go on to extraction. Re-running
the script keeps decisions, units and notes already entered.

First screen (October 2026, biofluids): 303 groups from 48 studies (blood 45, urine 5, CSF 2,
saliva 2; 38 human, 10 mouse, 4 macaque, 1 pig): 28 control, 81 unsure, 183 not control, 11 QC.
31 studies have something to review.

**First-pass review (October 2026).** Decisions and units were proposed for all 31 studies with
control or unsure groups, with the reasoning in `notes` (prefixed `first pass:`) for a person to
check. Units were judged from the study text and from the data: each study's values for metabolites
HMDB also lists were compared with HMDB's human values in µmol/L. Concentrations in µmol/L agree with
HMDB closely and consistently (log10 ratio ≈ 0 with a narrow spread); peak areas scatter. The same
exclusions as the Workbench review were applied (pregnancy, acute exercise, supplementation, injury
models, premature infants, cells).

- **9 studies have controls with a confirmed concentration unit:** MTBLS2014, 2104, 2615, 3852, 7337,
  12333 (human, µmol/L), MTBLS15429 (human, ng/mL), MTBLS143 (mouse, µmol/L) and MTBLS13862 (mouse, nmol/L).
- **10 have controls but an unclear unit** (`unit_confirmed = unclear`): MTBLS27, 72, 162, 249, 327, 685,
  1866, 6990, 10266, 15754. They stay out of extraction until the unit is checked in the paper.
- 2 report peak-area ratios (MTBLS449, 14989) and the rest have no usable control group.

## Step 3: extract the control data into the atlas

```
python pipeline/metabolights/prepare_mtbls.py names     # metabolite -> InChIKey (writes mtbls_name_map.csv)
python pipeline/metabolights/prepare_mtbls.py build     # control samples -> umol/L -> one value per study
python pipeline/1_parse_concentrations.py --source MTBLS
python pipeline/2_build_database.py
python pipeline/3_build_explorer.py
```

Built to mirror `pipeline/mwb/prepare_mwb.py` and reusing its unit conversion, molar masses,
name cleaning and species names, so both repositories are processed the same way.

**Which data:** review rows with `decision = control` in a study whose `unit_confirmed` is a
concentration unit. Confirming a unit for one of the pending studies and re-running both steps
adds it; nothing else needs changing. MAF columns are matched to samples by sample name, or through
the assay sheet where a MAF uses assay names (MTBLS143).

**Names → structure,** first hit wins: the MAF's HMDB ID; the MAF's InChI looked up exactly in an
InChI → InChIKey table built from the HMDB/BMDB XML downloads (cached, gitignored); RDKit on the
InChI, if installed; the name matched to HMDB (exactly, or ignoring spacing, underscores and
punctuation, with an explicit L-/D- respected and the L- form preferred otherwise); PubChem, unless
`--offline`. Lipid species written by class and carbon count ("PC(34:1)", "16:1 SM") and kit
shorthand for acylcarnitines ("C10:1") have no single structure and are left out, as for Workbench.

**Values:** values ≤ 0 are missing codes (0, −1, −2) and are dropped; units are converted to
µmol/L (ng/mL via the molar mass of the MAF's formula); each study's control samples are pooled to
`mean +/- SD (min - max)`, one value per metabolite and biospecimen.

**Checks,** as for Workbench: each study is compared with HMDB's human values (whole study dropped
if >30-fold off on ≥10 metabolites; `mtbls_study_check.csv`), and single values >1000-fold off
are dropped (`mtbls_value_check.csv`). Studies dropped after inspection are listed with the reason
in `EXCLUDE_STUDIES`.

**First run (October 2026, offline: no RDKit or PubChem):** 1,425 distinct metabolites in the 9
usable studies, 629 resolved (most of the rest are lipid species). 606 values from 8 studies
(556 human, 50 mouse; all blood). MTBLS13862 was excluded: its mouse amino acids come out 10–20×
below expected with the stated nmol/L. The other studies sit at 0.3–1.2× HMDB, and spot checks
agree with physiology (glucose 5.3 mmol/L, creatinine 50–108, valine 130–290, glutamine
400–730 µmol/L). In the atlas: 606 measurements, data for 313 human metabolites, 46 new mouse
ranges. Running `names` with RDKit installed or with PubChem access should resolve more of the
non-lipid metabolites.

## Next

- Team check of the first-pass decisions and of the 8 included studies.
- Check the units of the 10 pending studies in their papers; each confirmed one adds data.
- Re-run `names` without `--offline` (or with RDKit) to resolve more metabolites.
