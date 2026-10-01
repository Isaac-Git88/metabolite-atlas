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

# Shared step 1: free-text concentrations -> numbers (data/parsed/)
python pipeline/1_parse_concentrations.py --source HMDB
python pipeline/1_parse_concentrations.py --source BMDB
python pipeline/1_parse_concentrations.py --source YMDB
python pipeline/1_parse_concentrations.py --source ECMDB
python pipeline/1_parse_concentrations.py --source MWB

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
Step 2 ends with 9,770 reference ranges: Human 4,469, Cow 2,775, E. coli 891, Yeast 866,
plus six smaller species from Metabolomics Workbench. Step 3 reports 39,534 measurements
and 10 species.

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

## 6. MetaboLights (in progress)

MetaboLights is not in the atlas yet. Step 1, a survey of which studies report real
concentrations, is in `pipeline/metabolights/`:

```bash
python pipeline/metabolights/survey_metabolights.py check               # can we reach MetaboLights?
python pipeline/metabolights/survey_metabolights.py fetch --limit 20    # small trial
python pipeline/metabolights/survey_metabolights.py fetch --workers 4   # all ~3,500 public studies
python pipeline/metabolights/survey_metabolights.py survey
python pipeline/metabolights/survey_metabolights.py fetch --maf         # data files of shortlisted studies
python pipeline/metabolights/survey_metabolights.py survey
```

Results go to `data/metabolights/mtbls_study_survey.csv`. See
`pipeline/metabolights/README.md` for how the screen works.

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
| Re-download stops with 502/504 errors | The source server is overloaded. Lower `--workers` and re-run; finished items are skipped. |
