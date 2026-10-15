# How to run and update the atlas

One guide for everything practical: setting up, rebuilding the atlas and the website,
updating any of the six data sources when it publishes new data, and publishing the result.

What the project is and the decisions behind it are in [README.md](README.md). Each source's
folder under `pipeline/` has its own README with the full detail of how that source is handled.

All commands are run from the repository root (the `metabolite-atlas` folder); every script
anchors its own paths, so they also work from anywhere else. On a Mac, use `python3` and `pip3`
if `python` is not found.

**Contents**

1. How the data flows
2. What changed? What do I do?
3. Set up (once)
4. Updating one source: HMDB, BMDB, YMDB, ECMDB, Metabolomics Workbench, MetaboLights
5. Quick rebuild: one dataset changed
6. Rebuild everything (the standard run)
7. Check and publish the website
8. Troubleshooting
9. Where the details are

---

## 1. How the data flows

Every source ends up as one **clean CSV**. Three shared steps then turn the clean CSVs
into the database and the website:

```
source website / download
   │   (source scripts in pipeline/<source>/)
   ▼
data/<source>/..._clean.csv          one file per source
   │   pipeline/1_parse_concentrations.py --source <SOURCE>
   ▼
data/parsed/<source>_..._parsed.csv  one file per source (not committed)
   │   pipeline/2_build_database.py
   ▼
data/metabolite_atlas.db             the database (not committed)
   │   pipeline/3_build_explorer.py
   ▼
explorer/index.html                  the website (committed; GitHub Pages serves it)
```

Two rules follow from this:

1. **The website changes only when `3_build_explorer.py` runs and `explorer/index.html` is
   pushed.** Updating a source does nothing visible until steps 1–3 run and you push.
2. **Step 2 deletes the database and rebuilds it from every parsed CSV that exists. A missing
   one is skipped without an error,** and that source silently disappears from the site.
   Always parse all six (section 6) and check the species list step 2 prints.

---

## 2. What changed? What do I do?

Find your situation, then follow the sections in the **Then** column, in order.
Updating a source (section 4) never changes the website by itself: you always finish with a
rebuild, either section 5 (quick: only the dataset that changed) or section 6 (everything), and
then section 7 (check and publish). Use section 6 whenever you are unsure.

| What changed                                                | Download first?                       | Then                                                  |
| ----------------------------------------------------------- | ------------------------------------- | ----------------------------------------------------- |
| Nothing; I just want to look at the site                    | No                                    | Section 7 (open `explorer/index.html`)                |
| Nothing; I want to rebuild the site (e.g. after `git pull`) | **BMDB file only** (section 6)        | Section 6 → 7                                         |
| I changed the website's look (`explorer/template.html`)     | No                                    | `python pipeline/3_build_explorer.py` → section 7     |
| **HMDB** released a new version                             | Yes: `hmdb_metabolites.xml` (~6.5 GB) | Section 4.1 → 5 or 6 → 7                              |
| **BMDB** released a new version                             | Yes: `bmdb_metabolites.xml` (~450 MB) | Section 4.2 → 5 or 6 → 7                              |
| **YMDB** was updated                                        | No; the script reads the website      | Section 4.3 → 5 or 6 → 7                              |
| **ECMDB** was updated                                       | No; the script reads the website      | Section 4.4 → 5 or 6 → 7                              |
| **Metabolomics Workbench** has new studies                  | No; the script uses its API           | Section 4.5 → 5 or 6 → 7                              |
| **MetaboLights** has new studies                            | No; the script downloads from EBI     | Section 4.6 → 5 or 6 → 7                              |
| A pending MetaboLights study's unit was confirmed           | Only that study's files (by script)   | Section 4.6 ("Adding one pending study") → 5 or 6 → 7 |

"Download first" means a file you fetch by hand from a website before running anything.
Every other source is downloaded by its own script, which needs an internet connection.

For example, if Metabolomics Workbench has new studies: section 4.5 refreshes
`data/mwb/mwb_concentrations_clean.csv`; section 5 re-parses it and rebuilds the database and
`explorer/index.html` (or section 6 re-parses all six sources); section 7 checks the site and
pushes it live.

---

## 3. Set up (once)

You need Python 3.10 or newer and the repository:

```bash
git clone https://github.com/Isaac-Git88/metabolite-atlas.git
cd metabolite-atlas
python -m pip install -r requirements.txt      # pandas, and requests for the downloads
```

Before any update, get your teammates' latest work: `git pull origin main`.

---

## 4. Updating one source

Each subsection says where the new data comes from, whether you download anything first,
what to run, and which files to commit. **Order: section 4 → section 5 (quick
rebuild) or section 6 (rebuild everything) → section 7 (check and publish).** The website does not change until you do all three. All re-downloads are resumable: stop and re-run to continue.

### 4.1 HMDB (human)

- **New data comes from:** a new release on <https://hmdb.ca/downloads>.
- **Download first:** yes, `hmdb_metabolites.xml` (~6.5 GB, unzipped) into `data/hmdb/`.

```bash
python pipeline/hmdb/extract_hmdb.py     # XML data/hmdb/hmdb_normal_concentrations_raw.csv
python pipeline/hmdb/prepare_hmdb.py     # data/hmdb/hmdb_normal_concentrations_clean.csv
```

- **Commit:** `data/hmdb/hmdb_normal_concentrations_clean.csv`.
- **Note:** `data/hmdb/hmdb_inchikey_lookup.csv` (each HMDB metabolite's structure key)
  is not rebuilt by these scripts. If the new release adds metabolites, they won't match
  other sources until the lookup is extended.
- Details: `pipeline/hmdb/README.md`.

### 4.2 BMDB (cow)

- **New data comes from:** a new release on <https://bovinedb.ca/downloads>.
- **Download first:** yes, replace `data/bmdb/bmdb_metabolites.xml` with the new file.
- **Run:** the two BMDB scripts, which read the new XML (~10 s), then section 5 or 6:

```bash
python pipeline/bmdb/extract_bmdb_concentrations.py   # XML -> data/bmdb/bmdb_concentrations_all.csv
python pipeline/bmdb/prepare_bmdb.py                  # -> data/bmdb/bmdb_concentrations_clean.csv
```

These are the same two commands as section 6 A, so running section 6 in full also works.

- **Commit:** only `explorer/index.html`. BMDB's CSVs are not committed, because they are
  rebuilt from the XML on every run.
- **Check:** `prepare_bmdb.py` prints the records it drops (mastitis cows, and the study in
  `EXCLUDE_STUDIES`). Look for new impossible values after a release.
- Details: `pipeline/bmdb/README.md`.

### 4.3 YMDB (yeast)

- **New data comes from:** YMDB's website. Its download files carry no concentrations,
  so the script reads each metabolite's page.
- **Download first:** no. The script downloads, and needs internet access.

1. **Clear any earlier download first.** The script skips every page it has already fetched, so
   an old download on your computer would hide YMDB's changes. If `data/ymdb/xml/` or
   `data/ymdb/status.jsonl` exist, rename them (e.g. `xml_old`, `status_old.jsonl`). On a fresh
   clone they don't exist.
2. **Download again:**

```bash
python pipeline/ymdb/ymdb_links.py                                  # list every metabolite page
python pipeline/ymdb/extract_ymdb_concentrations.py all --workers 8 # ~10 hours; resumable
```

- Both scripts try IDs YMDB00001–YMDB16500. If YMDB now has metabolites beyond that, add
  `--max-id` with a higher number to both commands (e.g. `--max-id 17000`).

- If it stops (the server returns 502 errors under load), run the same command again:
  finished pages are skipped. Lower `--workers` if errors persist.
- **Commit:** `data/ymdb/ymdb_concentrations_all.csv` and `data/ymdb/ymdb_all_metabolite_links.csv`.
- Details: `pipeline/ymdb/README.md`.

### 4.4 ECMDB (E. coli)

- **New data comes from:** ECMDB's website. Like YMDB, the downloads carry no concentrations.
- **Download first:** no. The script downloads, and needs internet access.

1. **Clear any earlier download first,** as for YMDB: if `data/ecmdb/xml/` or
   `data/ecmdb/status.jsonl` exist, rename them, or the script won't fetch the changed pages.
2. **Download again** (a few hours; resumable):

```bash
python pipeline/ecmdb/extract_ecmdb_concentrations.py all --workers 4
```

- **Known gap:** the script reads its list of compounds from `data/ecmdb/ecmdb_metabolites.csv`,
  which is made from ECMDB's `ecmdb.json` download by `extract_ecmdb_downloads.py`. That script
  is not in the repository yet, so a re-download only works on the computer that has the file.

- Keep `--workers` at 4 or below; the server returns 504 errors above that.
  Seven pages are known to fail on ECMDB's side; re-running won't fetch them.
- **Commit:** `data/ecmdb/ecmdb_concentrations_all.csv`.
- Details: `pipeline/ecmdb/README.md`.

### 4.5 Metabolomics Workbench (US repository)

- **New data comes from:** new studies deposited at <https://www.metabolomicsworkbench.org>.
- **Download first:** no. The scripts use the repository's API (internet needed).
- **A person is needed** to review new sample groups (step 3 below).

```bash
# 1. Survey: list every analysis and download the ones that report concentrations
python pipeline/mwb/survey_mwb.py fetch --workers 4     # resumable; only new analyses are downloaded
python pipeline/mwb/survey_mwb.py survey

# 2. Suggest control groups
python pipeline/mwb/select_controls.py                  # data/mwb/mwb_control_review.csv
```

**3. Review.** Open `data/mwb/mwb_control_review.csv` in Excel. For rows whose `suggestion`
is `control` or `unsure` and whose `decision` is empty, write `control`, `not_control` or
`exclude` in `decision`. Earlier decisions are kept, so only new rows need attention.
Save as **CSV UTF-8**. Only `decision = control` rows are used. Exclude disease, treatment,
knockout or tumour models, pregnancy, exercise or fed states, and tissue samples.

```bash
# 4. Match names to structures, then extract the control data
python pipeline/mwb/prepare_mwb.py names                # asks RefMet; cached
python pipeline/mwb/prepare_mwb.py build                # data/mwb/mwb_concentrations_clean.csv
```

- `build` compares every study with HMDB and leaves out likely unit errors. Read the
  `Checks:` line it prints, and look at the largest values of any new study. If a study is
  clearly wrong, add it to `EXCLUDE_STUDIES` in `prepare_mwb.py` with the reason and run
  `build` again.
- **Re-running `build` without a source update:** it reads the downloaded files in
  `data/mwb/mwtab/`, which are not committed. On a fresh computer, run step 1 first.
- **Commit:** everything in `data/mwb/` that git shows: the survey, review, name map,
  clean CSV and the two check files.
- Details: `pipeline/mwb/README.md`.

### 4.6 MetaboLights (European repository)

- **New data comes from:** new studies at <https://www.ebi.ac.uk/metabolights/download>.
- **Download first:** no. The scripts download from EBI (internet needed).
- **A person is needed** to review control groups **and** each study's unit, because
  MetaboLights has no unit field.

MetaboLights currently contributes control-group data from 8 studies (611 values, human and
mouse blood). If you only want to rebuild the site, there is nothing extra to do:
`data/metabolights/mtbls_concentrations_clean.csv` is committed, and section 6 includes it.

**Before you start** (adding or re-surveying studies only):

- **Internet access to `ebi.ac.uk`.** Check with
  `python pipeline/metabolights/survey_metabolights.py check`: all three lines should say `OK`.
- **The `requests` package**, in the same Python you run the scripts with:
  `python -m pip install requests`. On a Mac with Anaconda, use `python`, not `python3`;
  they can be two different Pythons, and only one may have the package.
- **For matching metabolites to structures,** at least one of the following (more of them
  resolves more metabolites):
  - the BMDB and/or HMDB XML download in `data/bmdb/` or `data/hmdb/`;
  - RDKit (`python -m pip install rdkit`);
  - internet access to PubChem (`pubchem.ncbi.nlm.nih.gov`).

#### Adding one pending study

Ten studies have healthy controls but an unclear unit: the rows of
`data/metabolights/mtbls_control_review.csv` with `decision = control` and
`unit_confirmed = unclear`. To add one, for example MTBLS27:

1. **Find the unit** in the study's paper (the `study_url` column links to the study page).
2. **Edit the review file.** On every row for that study, set `unit_confirmed` to the unit
   exactly as written: `umol/L`, `nmol/mL`, `mmol/L`, `nmol/L`, `ng/mL`, `ug/mL` or `mg/dL`
   (or `relative` if the values turn out not to be concentrations). Check `decision`, add a
   note, then save as **CSV UTF-8**.
3. **Download the study's files,** unless `data/metabolights/isa/MTBLS27/` already has `m_*.tsv` files:
   ```bash
   python pipeline/metabolights/survey_metabolights.py fetch --maf --ids MTBLS27
   ```
4. **Extract:** run `prepare_mtbls.py names` and `build` (step 4 below), then section 5 or 6.

#### Picking up all new studies

```bash
# 1. Survey every public study (resumable)
python pipeline/metabolights/survey_metabolights.py fetch --workers 4   # metadata, ~3,500 studies, ~40 min
python pipeline/metabolights/survey_metabolights.py survey              # text screen
python pipeline/metabolights/survey_metabolights.py fetch --maf         # data files of shortlisted studies
python pipeline/metabolights/survey_metabolights.py survey              # final screen, with the data-file check

# 2. Suggest control groups
python pipeline/metabolights/select_controls.py   # -> data/metabolights/mtbls_control_review.csv
```

**3. Review** `data/metabolights/mtbls_control_review.csv`:

- **`decision`**, for each row suggested `control` or `unsure`: `control`, `not_control` or `exclude`.
- **`unit_confirmed`**, once per study: a unit (as above), or `relative` or `unclear`.

Only rows with `decision = control` in a study with a real unit are used. Re-running
`select_controls.py` keeps whatever has already been entered.

```bash
# 4. Extract
python pipeline/metabolights/prepare_mtbls.py names     # add --offline to skip PubChem
python pipeline/metabolights/prepare_mtbls.py build
```

- **Check the result.** `build` prints one line per study. A new study should read `ok`, with
  a typical value roughly 0.3–3× HMDB; far outside that usually means the unit is wrong.
  Full results are in `data/metabolights/mtbls_study_check.csv`. If a study looks wrong,
  add it to `EXCLUDE_STUDIES` in `prepare_mtbls.py` with the reason and re-run `build`.
- **Two failures are expected.** MTBLS15156 and MTBLS15262 fail to download on MetaboLights'
  side; re-running won't help.
- **Most unresolved metabolites are lipids.** `names` leaves out lipid species written by class
  and carbon count (e.g. `PC(34:1)`) and kit shorthand such as `C10:1`, which have no single
  structure. A few hundred unresolved names is normal.

What each step writes, all in `data/metabolights/`:

| Step                 | Output                                                                               | Committed          |
| -------------------- | ------------------------------------------------------------------------------------ | ------------------ |
| `fetch`              | `isa/` (study files), `status.jsonl`, `studies.json`                                 | no                 |
| `survey`             | `mtbls_study_survey.csv`, `mtbls_organisms.csv`                                      | yes                |
| `select_controls.py` | `mtbls_control_review.csv`                                                           | yes                |
| `names`              | `mtbls_name_map.csv` (plus caches `inchi_inchikey_lookup.csv`, `pubchem_cache.json`) | map yes, caches no |
| `build`              | `mtbls_concentrations_clean.csv`, `mtbls_study_check.csv`, `mtbls_value_check.csv`   | yes                |

- **Commit:** the committed files in the table above that changed.
- Details: `pipeline/metabolights/README.md`.

---

## 5. Quick rebuild: one dataset changed

After updating one dataset in section 4, you don't have to re-prepare and re-parse the other
five. Re-parse only the one that changed, then rebuild the database and the website. Steps 2
and 3 always run in full: they rebuild the database and the site as a whole, from every file in
`data/parsed/`.

**Only use this if all six parsed files are already on your computer and up to date.** Check:

```bash
ls data/parsed
```

You should see six files: `hmdb_`, `bmdb_`, `ymdb_`, `ecmdb_`, `mwb_` and
`mtbls_concentrations_parsed.csv`. If any is missing, or you have just pulled teammates'
changes to other datasets, or you are not sure, use **section 6** instead.

Copy and run the **whole block** for the dataset you updated. Every block ends with the same
two commands, which rebuild the database and the website; without them the site doesn't change.

**HMDB**

```bash
python pipeline/1_parse_concentrations.py --source HMDB
python pipeline/2_build_database.py        # check: all 10 species listed at the end
python pipeline/3_build_explorer.py        # writes explorer/index.html
```

**BMDB**

```bash
python pipeline/bmdb/extract_bmdb_concentrations.py
python pipeline/bmdb/prepare_bmdb.py
python pipeline/1_parse_concentrations.py --source BMDB
python pipeline/2_build_database.py        # check: all 10 species listed at the end
python pipeline/3_build_explorer.py        # writes explorer/index.html
```

**YMDB**

```bash
python pipeline/ymdb/prepare_ymdb.py
python pipeline/1_parse_concentrations.py --source YMDB
python pipeline/2_build_database.py        # check: all 10 species listed at the end
python pipeline/3_build_explorer.py        # writes explorer/index.html
```

**ECMDB**

```bash
python pipeline/ecmdb/prepare_ecmdb.py
python pipeline/1_parse_concentrations.py --source ECMDB
python pipeline/2_build_database.py        # check: all 10 species listed at the end
python pipeline/3_build_explorer.py        # writes explorer/index.html
```

**Metabolomics Workbench**

```bash
python pipeline/1_parse_concentrations.py --source MWB
python pipeline/2_build_database.py        # check: all 10 species listed at the end
python pipeline/3_build_explorer.py        # writes explorer/index.html
```

**MetaboLights**

```bash
python pipeline/1_parse_concentrations.py --source MTBLS
python pipeline/2_build_database.py        # check: all 10 species listed at the end
python pipeline/3_build_explorer.py        # writes explorer/index.html
```

If any species is missing from the list `2_build_database.py` prints, run section 6.

If two datasets changed, run the first lines of both blocks, then the last two commands once.

**After an HMDB update:** the Metabolomics Workbench and MetaboLights checks compare each study
against HMDB. For a major HMDB release, also re-run `python pipeline/mwb/prepare_mwb.py build` and
`python pipeline/metabolights/prepare_mtbls.py build`, then parse `MWB` and `MTBLS`, before steps 2
and 3, so their checks use the new HMDB values. This needs their downloaded files (sections 4.5
and 4.6).

Then go to section 7 (check and publish).

---

## 6. Rebuild everything (the standard run)

Use this on a new computer, after pulling changes or editing a script, and at the end of any
update in section 4 when the quick rebuild (section 5) doesn't apply or you are unsure. It needs no downloads **except the BMDB file**, because BMDB's clean CSV is not
committed and is rebuilt from its XML every time:

> **BMDB download:** get `bmdb_metabolites.xml` (~450 MB) from <https://bovinedb.ca/downloads>
> and put it in `data/bmdb/`. You only need to do this once per computer. Without it, skip
> the two BMDB commands and `--source BMDB`: everything else still builds, but the cow data
> from BMDB disappears from the site, so **don't commit `explorer/index.html` from that run.**

```bash
# A. Make each source's clean CSV
#    HMDB, Metabolomics Workbench, MetaboLights: committed, nothing to do
python pipeline/bmdb/extract_bmdb_concentrations.py
python pipeline/bmdb/prepare_bmdb.py
python pipeline/ymdb/prepare_ymdb.py
python pipeline/ecmdb/prepare_ecmdb.py

# B. Parse every source
python pipeline/1_parse_concentrations.py --source HMDB
python pipeline/1_parse_concentrations.py --source BMDB
python pipeline/1_parse_concentrations.py --source YMDB
python pipeline/1_parse_concentrations.py --source ECMDB
python pipeline/1_parse_concentrations.py --source MWB
python pipeline/1_parse_concentrations.py --source MTBLS

# C. Database and website
python pipeline/2_build_database.py        # check: 10 species listed at the end
python pipeline/3_build_explorer.py        # writes explorer/index.html
```

**Expected output (October 2026).** Tested on a fresh clone, these commands reproduce the
committed `explorer/index.html`. Step 2 ends with 9,865 reference ranges: Human 4,518, Cow 2,775,
E. coli 891, Yeast 866, Mouse 340, plus five smaller species from Metabolomics Workbench.
Step 3 reports 40,145 measurements and 10 species. After a source update the numbers change,
but no species should vanish.

Then check the site and publish it (section 7).

---

## 7. Check and publish the website

**Just looking?** No Python is needed. `explorer/index.html` is committed and self-contained:
double-click it, or run `open explorer/index.html` (Mac), `start explorer/index.html` (Windows)
or `xdg-open explorer/index.html` (Linux). It is also published on GitHub Pages.

**After an update:**

1. **Check locally.** Open `explorer/index.html`. Confirm that all 10 species appear in the
   Species filter and the headline numbers look right. Search a well-known metabolite, e.g.
   `D-Glucose` in human blood (median about 4,750 µmol/L).
2. **Publish.** Commit the source files listed in section 4 together with the rebuilt site:

   ```bash
   git status                 # review what changed; data/parsed/ and the database are ignored
   git add <the files from section 4> explorer/index.html
   git commit -m "Update <source> data"
   git pull origin main
   git push origin main
   ```

3. The live site (GitHub Pages) updates 1–2 minutes after the push. Reload without the
   cache (Cmd+Shift+R on a Mac, Ctrl+Shift+R on Windows) if it still shows old numbers.

**Changing the website's design:** edit `explorer/template.html`, then run
`python pipeline/3_build_explorer.py` and commit both `template.html` and the rebuilt
`index.html`. Never edit `explorer/index.html` by hand: every build overwrites it.

---

## 8. Troubleshooting

| Problem                                                 | Fix                                                                                                                                                |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| A species is missing from the site                      | Its parsed CSV was missing when step 2 ran. Run section 6 B and C again.                                                                           |
| Cow is missing / `bmdb_metabolites.xml not found`       | Download it into `data/bmdb/` (section 6).                                                                                                         |
| `FileNotFoundError` for a `*_clean.csv`                 | Run that source's prepare script (section 6 A).                                                                                                    |
| MWB `build` can't find files in `mwtab/`                | Run `python pipeline/mwb/survey_mwb.py fetch --workers 4` first (section 4.5).                                                                     |
| `ModuleNotFoundError: pandas` / `requests`              | `python -m pip install -r requirements.txt`, using the same `python` you run the scripts with. On a Mac with Anaconda use `python`, not `python3`. |
| A download stops with 502/504 errors                    | The server is busy. Lower `--workers` and re-run; finished items are skipped.                                                                      |
| The site still shows old data                           | Check you pushed `explorer/index.html`, wait 2 minutes, and reload without the cache.                                                              |
| `git pull` conflict in `explorer/index.html`            | Keep either version, then rebuild it with section 6. Don't merge it by hand.                                                                       |
| `git pull` refuses because of local changes             | `git pull --rebase --autostash`                                                                                                                    |
| MetaboLights: `check` shows `FAIL`                      | Your network can't reach `ebi.ac.uk`. Try another network; the rest of the atlas doesn't need it.                                                  |
| MetaboLights: "No control groups with a confirmed unit" | No row in `mtbls_control_review.csv` has `decision = control` together with a real unit (section 4.6).                                             |
| MetaboLights: a study you added is missing              | Its `unit_confirmed` isn't a recognised unit, or it failed the HMDB check. Read the per-study lines `build` prints, or `mtbls_study_check.csv`.    |

---

## 9. Where the details are

| Topic                                                                      | File                              |
| -------------------------------------------------------------------------- | --------------------------------- |
| What the atlas is, headline numbers, design decisions, adding a new source | `README.md`                       |
| HMDB                                                                       | `pipeline/hmdb/README.md`         |
| BMDB                                                                       | `pipeline/bmdb/README.md`         |
| YMDB                                                                       | `pipeline/ymdb/README.md`         |
| ECMDB                                                                      | `pipeline/ecmdb/README.md`        |
| Metabolomics Workbench                                                     | `pipeline/mwb/README.md`          |
| MetaboLights                                                               | `pipeline/metabolights/README.md` |
