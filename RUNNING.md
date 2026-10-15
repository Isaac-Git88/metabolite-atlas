# How to run the project

This guide takes you from a fresh clone to a rebuilt atlas and explorer site.
For what the project is and the decisions behind it, see [README.md](README.md);
each source's folder under `pipeline/` has its own README with the details.

All commands are run from the repository root (the `metabolite-atlas` folder).
Every script anchors its own paths, so they also work from anywhere else.

---

## 1. Set up (once)

You need Python 3.10 or newer.

```bash
git clone https://github.com/Isaac-Git88/metabolite-atlas.git
cd metabolite-atlas
pip install -r requirements.txt
```

On a Mac, use `python3` and `pip3` if `python` is not found.

---

## 2. Just look at the explorer

No Python needed. `explorer/index.html` is committed and fully self-contained:

```bash
open explorer/index.html          # Mac
start explorer/index.html         # Windows
xdg-open explorer/index.html      # Linux
```

or double-click it in your file browser. It is also published on GitHub Pages.

---

## 3. Rebuild the atlas and the site

This is the normal workflow after pulling changes or editing a script. Each source is
prepared in its own folder under `pipeline/`, then goes through three shared steps.
No large downloads are needed, **except for cow (BMDB)**: see the note below.

```bash
# Each source -> data/<source>/..._clean.csv
#   HMDB: nothing to do, data/hmdb/hmdb_normal_concentrations_clean.csv is committed
python pipeline/bmdb/extract_bmdb_concentrations.py   # needs data/bmdb/bmdb_metabolites.xml
python pipeline/bmdb/prepare_bmdb.py
python pipeline/ymdb/prepare_ymdb.py
python pipeline/ecmdb/prepare_ecmdb.py
#   MWB: nothing to do, data/mwb/mwb_concentrations_clean.csv is committed
#   MTBLS: nothing to do, data/metabolights/mtbls_concentrations_clean.csv is committed

# Shared step 1: free-text concentrations -> numbers (data/parsed/)
python pipeline/1_parse_concentrations.py --source HMDB
python pipeline/1_parse_concentrations.py --source BMDB
python pipeline/1_parse_concentrations.py --source YMDB
python pipeline/1_parse_concentrations.py --source ECMDB
python pipeline/1_parse_concentrations.py --source MWB
python pipeline/1_parse_concentrations.py --source MTBLS

# Shared steps 2 and 3
python pipeline/2_build_database.py                   # -> data/metabolite_atlas.db
python pipeline/3_build_explorer.py                   # -> explorer/index.html
```

**Step 2 deletes the database and rebuilds it from whichever
`data/parsed/*_concentrations_parsed.csv` files exist. A missing one is skipped without
an error**, and that species silently disappears from the atlas and the site. Parse
every source first, and check the species list step 2 prints at the end.

**Cow (BMDB) needs one download.** Its source file, `bmdb_metabolites.xml` (~450 MB),
is not in the repository. Download it from <https://bmdb.ca/downloads> and put it in
`data/bmdb/`. Without it, skip the two BMDB commands and `--source BMDB`: everything
else still builds, but the site has no cow data from BMDB, so **don't commit
`explorer/index.html` from that run**.

### Expected output (October 2026)

Tested on a fresh clone: these commands reproduce the committed `explorer/index.html`.
Step 2 ends with 9,865 reference ranges: Human 4,518, Cow 2,775, E. coli 891, Yeast 866,
Mouse 340, plus five smaller species from Metabolomics Workbench. Step 3 reports 40,145
measurements and 10 species.

---

## 4. Changing the website

Edit **`explorer/template.html`**, then rebuild the site only:

```bash
python pipeline/3_build_explorer.py
```

Never edit `explorer/index.html` by hand: it is generated, and the next build overwrites it.
Commit both `template.html` and the rebuilt `index.html`.

---

## 5. Re-downloading a source from scratch

Only needed to refresh from a new release, or to change how a source is extracted.
These need internet access and some take hours; all are resumable (stop and
re-run to continue).

| Source | Command(s) | Time | Details |
|---|---|---|---|
| HMDB | download `hmdb_metabolites.xml` (~6.5 GB) from <https://hmdb.ca/downloads> into `data/hmdb/`, then `python pipeline/hmdb/extract_hmdb.py` and `python pipeline/hmdb/prepare_hmdb.py` | slow (6.5 GB file) | `pipeline/hmdb/README.md` |
| BMDB | download `bmdb_metabolites.xml`, then the two BMDB commands above | ~10 s | `pipeline/bmdb/README.md` |
| YMDB | `python pipeline/ymdb/ymdb_links.py` then `python pipeline/ymdb/extract_ymdb_concentrations.py all --workers 8` | ~10 hours | `pipeline/ymdb/README.md` |
| ECMDB | `python pipeline/ecmdb/extract_ecmdb_concentrations.py all --workers 4` | hours | `pipeline/ecmdb/README.md` |
| Metabolomics Workbench | `survey_mwb.py fetch` / `survey`, `select_controls.py`, manual review of `data/mwb/mwb_control_review.csv`, then `prepare_mwb.py names` / `build` | hours + review | `pipeline/mwb/README.md` |

Then run the shared steps 1–3 (section 3).

The Metabolomics Workbench control-group review is a manual decision recorded in
`data/mwb/mwb_control_review.csv` (committed). Re-running `select_controls.py` keeps
the decisions already entered.

---

## 6. MetaboLights

MetaboLights is in the atlas: control-group data from 8 studies (611 values, human and
mouse blood). They were chosen by surveying all public studies for real concentrations,
then reviewing each candidate's control groups and units by hand. The scripts are in
`pipeline/metabolights/`; how each one works is in `pipeline/metabolights/README.md`.

Which of the three cases below applies to you?

| You want to… | Go to |
|---|---|
| Rebuild the atlas and site, MetaboLights included | **6.1**: nothing extra to do |
| Add one of the pending studies once its unit is confirmed | **6.2** |
| Redo the whole MetaboLights source from scratch | **6.3** |

### Before you start (6.2 and 6.3 only)

- **Internet access to `ebi.ac.uk`.** Study files download from MetaboLights. Check with
  `python pipeline/metabolights/survey_metabolights.py check`: all three lines should say `OK`.
- **The `requests` package**, in the same Python you run the scripts with:
  `python -m pip install requests`. On a Mac with Anaconda, use `python`, not `python3`.
  They can be two different Pythons, and only one may have the package.
- **For matching metabolites to structures**, at least one of the following. More of
  them resolves more metabolites:
  - the BMDB and/or HMDB XML download in `data/bmdb/` or `data/hmdb/`;
  - RDKit (`python -m pip install rdkit`);
  - internet access to PubChem (`pubchem.ncbi.nlm.nih.gov`).

### 6.1 Rebuild with MetaboLights: nothing extra

`data/metabolights/mtbls_concentrations_clean.csv` is committed, so section 3 already
includes MetaboLights through this line:

```bash
python pipeline/1_parse_concentrations.py --source MTBLS
```

### 6.2 Add a pending study after confirming its unit

Ten studies have healthy controls but an unclear unit. They are the rows of
`data/metabolights/mtbls_control_review.csv` with `decision = control` and
`unit_confirmed = unclear`, and the **Unit to confirm** sheet of the survey summary lists
them. To add one, for example MTBLS27:

1. **Find the unit** in the study's paper (the `study_url` column links to the study page).
2. **Edit the review file.** Open `data/metabolights/mtbls_control_review.csv` in Excel.
   On every row for that study, set `unit_confirmed` to the unit exactly as written:
   `umol/L`, `nmol/mL`, `mmol/L`, `nmol/L`, `ng/mL`, `ug/mL` or `mg/dL`. If the values
   turn out to be relative, write `relative`. Check that the `decision` column is right,
   add a note, then save as **CSV UTF-8**.
3. **Download the study's files.** A fresh clone doesn't have them; skip this if
   `data/metabolights/isa/MTBLS27/` already has `m_*.tsv` files:
   ```bash
   python pipeline/metabolights/survey_metabolights.py fetch --maf --ids MTBLS27
   ```
4. **Extract and rebuild:**
   ```bash
   python pipeline/metabolights/prepare_mtbls.py names
   python pipeline/metabolights/prepare_mtbls.py build
   python pipeline/1_parse_concentrations.py --source MTBLS
   python pipeline/2_build_database.py
   python pipeline/3_build_explorer.py
   ```
5. **Check the result.** `build` prints one line per study. The new study should read
   `ok`, and its typical value should be roughly 0.3–3× HMDB. Anything far outside that
   suggests the unit is wrong. The full results are in
   `data/metabolights/mtbls_study_check.csv`. If a study looks wrong, add it to
   `EXCLUDE_STUDIES` in `prepare_mtbls.py` with the reason, and re-run `build`.
6. **Commit** the review file, `mtbls_name_map.csv`, `mtbls_concentrations_clean.csv`,
   the two check files and `explorer/index.html`.

### 6.3 Redo MetaboLights from scratch

Needed only to pick up new MetaboLights studies or to change the screening rules. It
takes about an hour of downloads plus a manual review.

```bash
# 1. Survey every public study (resumable: re-run to continue after a stop)
python pipeline/metabolights/survey_metabolights.py fetch --workers 4   # metadata, ~3,500 studies, ~40 min
python pipeline/metabolights/survey_metabolights.py survey              # text screen
python pipeline/metabolights/survey_metabolights.py fetch --maf         # data files of shortlisted studies
python pipeline/metabolights/survey_metabolights.py survey              # final screen, with the data-file check

# 2. Suggest control groups for review
python pipeline/metabolights/select_controls.py   # -> data/metabolights/mtbls_control_review.csv
```

**3. Review**, by a person, in `mtbls_control_review.csv`:

- **`decision`**, for each row suggested `control` or `unsure`: `control`, `not_control` or
  `exclude`.
- **`unit_confirmed`**, once per study: a unit (as in 6.2), or `relative` or `unclear`.

Only rows with `decision = control` in a study with a real unit are used. Re-running
`select_controls.py` keeps whatever has already been entered.

```bash
# 4. Extract, then the shared steps
python pipeline/metabolights/prepare_mtbls.py names     # add --offline to skip PubChem
python pipeline/metabolights/prepare_mtbls.py build
python pipeline/1_parse_concentrations.py --source MTBLS
python pipeline/2_build_database.py
python pipeline/3_build_explorer.py
```

What each step writes, all in `data/metabolights/`:

| Step | Output | Committed |
|---|---|---|
| `fetch` | `isa/` (study files), `status.jsonl`, `studies.json` | no |
| `survey` | `mtbls_study_survey.csv`, `mtbls_organisms.csv` | yes |
| `select_controls.py` | `mtbls_control_review.csv` | yes |
| `names` | `mtbls_name_map.csv` (plus caches `inchi_inchikey_lookup.csv`, `pubchem_cache.json`) | map yes, caches no |
| `build` | `mtbls_concentrations_clean.csv`, `mtbls_study_check.csv`, `mtbls_value_check.csv` | yes |

**Notes**

- **Two failures are expected.** MTBLS15156 and MTBLS15262 fail to download on
  MetaboLights' side. `fetch` reports them as failed attempts, and re-running won't help.
- **Most unresolved metabolites are lipids.** `names` leaves out lipid species written by
  class and carbon count (e.g. `PC(34:1)`) and kit shorthand such as `C10:1`. These have no
  single structure. A few hundred unresolved names is normal.

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| A species is missing from the site | Its `data/parsed/*_concentrations_parsed.csv` was missing when step 2 ran. Parse it (step 1) and re-run steps 2 and 3. |
| `FileNotFoundError` for a `*_clean.csv` | Run that source's prepare script first (section 3). |
| Cow is skipped / `bmdb_metabolites.xml not found` | Download it into `data/bmdb/` (section 3). |
| `ModuleNotFoundError: pandas` / `requests` | `python -m pip install -r requirements.txt`, using the same `python` you run the scripts with. |
| The site still shows old data | Reload without cache: Cmd+Shift+R (Mac) / Ctrl+Shift+R (Windows). |
| `git pull` conflict in `explorer/index.html` | Keep either version, then rebuild it with the steps in section 3. Don't merge it by hand. |
| `git pull` refuses because of local changes | `git pull --rebase --autostash` |
| MetaboLights: `ModuleNotFoundError: requests` | `python -m pip install requests`, with the same `python` you run the script with. On a Mac with Anaconda use `python`, not `python3`. |
| MetaboLights: `check` shows `FAIL` | Your network can't reach `ebi.ac.uk`. Try another network; the rest of the atlas doesn't need it. |
| MetaboLights: "No control groups with a confirmed unit" | No row in `mtbls_control_review.csv` has `decision = control` together with a real unit. See 6.2. |
| MetaboLights: a study you added is missing | Its `unit_confirmed` isn't a recognised unit, or it failed the HMDB check. Read the per-study lines `build` prints, or `mtbls_study_check.csv`. |
| Re-download stops with 502/504 errors | The source server is overloaded. Lower `--workers` and re-run; finished items are skipped. |
