"""
survey_mwb.py
Step 1 of the Metabolomics Workbench (MWB) source: find out how much of the
repository reports real concentrations before building an extractor for it.

Most MWB analyses are untargeted and report peak areas or intensities, which are
relative and cannot go into the atlas. Only analyses that report a concentration
unit (uM, ng/mL, mg/dL, ...) are usable. This script tallies which is which.

Two steps:
  1. fetch  - download the study and analysis lists (the analysis list already
              gives every analysis's units), then the full mwTab file (JSON) of each
              analysis that reports a concentration unit, into data/mwb/mwtab/ as .json.gz. Resumable: already
              downloaded analyses are skipped, so it can be stopped and restarted.
              Progress is logged to data/mwb/status.jsonl.
  2. survey - read every saved mwTab file and write:
                data/mwb/mwb_analysis_survey.csv  one row per analysis
                data/mwb/mwb_unit_counts.csv      every distinct UNITS string, with its class
              and print a summary.

Usage:
    pip install requests
    python pipeline/mwb/survey_mwb.py fetch --limit 50     # quick trial on 50 analyses
    python pipeline/mwb/survey_mwb.py fetch --workers 4
    python pipeline/mwb/survey_mwb.py survey
    python pipeline/mwb/survey_mwb.py all                  # fetch then survey

REST API: https://www.metabolomicsworkbench.org/tools/mw_rest.php
mwTab format: https://www.metabolomicsworkbench.org/data/mwTab_specification.pdf

Notes:
  - Only the ~7% of analyses with a concentration unit are downloaded (add
    --all-units for everything). The mwTab files hold the full data matrix the
    extractor needs later, so they are fetched once. data/mwb/mwtab/ is gitignored.
  - Keep --workers low (2-4): this is a shared public server.
  - Unit classification is a first pass by pattern. Check mwb_unit_counts.csv
    and add any misclassified units to the patterns below.
"""
import argparse
import csv
import gzip
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "mwb")
MWTAB_DIR = os.path.join(DATA, "mwtab")
STATUS_FILE = os.path.join(DATA, "status.jsonl")
BASE = "https://www.metabolomicsworkbench.org/rest"

# words that suggest a healthy / untreated group in SUBJECT_SAMPLE_FACTORS
CONTROL_WORDS = re.compile(
    r"\b(control|ctrl|healthy|baseline|vehicle|sham|wild[- ]?type|wt|normal|untreated|placebo)\b", re.I)


# ------------------------------------------------------------------ helpers
def session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = "metabolite-concentration-atlas (university research project)"
    return s


def get_json(s, url, tries=6):
    for attempt in range(tries):
        try:
            r = s.get(url, timeout=180)
            if r.status_code == 200:
                return r.json() if r.text.strip() else None
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(min(60, 2 ** attempt))
    raise RuntimeError("failed after retries: " + url)


def rows(listing):
    """The REST API returns one record as a dict, and several as {"1": {...}, "2": {...}}."""
    if not listing:
        return []
    if isinstance(listing, list):
        return listing
    if all(isinstance(v, dict) for v in listing.values()):
        return list(listing.values())
    return [listing]


# ------------------------------------------------------------------ step 1: fetch
def fetch(workers, limit, all_units=False):
    os.makedirs(MWTAB_DIR, exist_ok=True)
    s = session()

    # study- and analysis-level listings (small; refreshed every run)
    for name, url in [("studies_summary", BASE + "/study/study_id/ST/summary"),
                      ("studies_species", BASE + "/study/study_id/ST/species"),
                      ("analyses", BASE + "/study/study_id/ST/analysis")]:
        print("listing", name, "...")
        with open(os.path.join(DATA, name + ".json"), "w") as f:
            json.dump(get_json(s, url), f)

    analyses = rows(json.load(open(os.path.join(DATA, "analyses.json"))))
    ids = sorted({a.get("analysis_id") for a in analyses if a.get("analysis_id")})
    print(f"{len(ids)} analyses listed")
    if not all_units:
        # the listing already carries each analysis's units, so only the analyses that
        # report a concentration need their full mwTab file
        ids = sorted({a["analysis_id"] for a in analyses
                      if a.get("analysis_id") and classify_unit(a.get("units")) == "volumetric"})
        print(f"{len(ids)} report a volumetric concentration unit and will be downloaded")

    done = set()
    if os.path.exists(STATUS_FILE):
        for line in open(STATUS_FILE):
            r = json.loads(line)
            if r["s"] in ("ok", "empty"):
                done.add(r["id"])
    todo = [i for i in ids if i not in done]
    if limit:
        todo = todo[:limit]
    print(f"{len(done)} already done, {len(todo)} to fetch")

    lock = threading.Lock()
    log = open(STATUS_FILE, "a")
    n = {"i": 0}

    def job(an):
        status = "fail"
        try:
            data = get_json(s, f"{BASE}/study/analysis_id/{an}/mwtab/json")
            if data:
                with gzip.open(os.path.join(MWTAB_DIR, an + ".json.gz"), "wt") as f:
                    json.dump(data, f)
                status = "ok"
            else:
                status = "empty"
        except Exception:
            status = "fail"
        with lock:
            log.write(json.dumps({"id": an, "s": status, "t": time.time()}) + "\n")
            log.flush()
            n["i"] += 1
            if n["i"] % 25 == 0 or n["i"] == len(todo):
                print(f"  {n['i']}/{len(todo)}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(job, todo))
    log.close()


# ------------------------------------------------------------------ unit classification
# Order matters: the first match wins.
UNIT_CLASSES = [
    ("missing", r"^(n/?a|none|-|unspecified|not applicable|no applicable.*|n/a \(.*\))$"),
    ("relative", r"peak|area|\bauc\b|intensit|count|\bcps\b|abu\w*ance|\bratio|\bfold|normali[sz]ed|arbitrary|"
                 r"\ba\.?u\.?\b|relative|response|signal|height|\blog|z.?score|scaled|%|percent|absorbance|"
                 r"presence|original scale|\bsi\b"),
    ("not_a_value", r"m/?z|\bppm\b|\bda\b|dalton|retention|time_"),
    ("normalised", r"/\s*(k?g|mg|µg|μg|ug|ng|gram)\b|per\s*(k?g|mg|gram|\d)|/\s*\d+\s*mg|protein|tissue|"
                   r"cells?\b|pbmc|\bdna\b|dry\s*(weight|powder)|\bdw\b|/\s*od|creatinine|/\s*brain"),
    ("volumetric", r"^\s*(p|n|u|µ|μ|m)?\s*(m|mol/l|mol/ml|mol/dl)\s*$|"
                   r"(p|n|u|µ|μ|m|pico|nano|micro|milli)?(mol|mole|moles)\b.*(/|\bper)\s*(100\s*)?(l|ml|dl|µl|ul|μl)\b|"
                   r"(p|n|u|µ|μ|m)?g\s*/\s*(100\s*)?(l|ml|dl|µl|ul|μl)\b|"
                   r"\b(p|n|u|µ|μ|m)m\b|micromolar|millimolar|nanomolar|\bmolar"),
    ("amount", r"mol(es)?\b|gram|\bng\b|\bpg\b|vial"),   # absolute amount with no volume or mass
]


def classify_unit(u):
    t = " ".join(str(u or "").split()).lower()
    if not t:
        return "missing"
    for cls, pat in UNIT_CLASSES:
        if re.search(pat, t):
            return cls
    return "unknown"


# ------------------------------------------------------------------ step 2: survey
CONTROL_WORDS_POOLED = re.compile(r"\b(pooled|pool|reference material|srm ?1950|nist)\b", re.I)


def find_value(section, *words):
    """First value in a mwTab section whose key contains all the given words."""
    if not isinstance(section, dict):
        return ""
    for k, v in section.items():
        if all(w in k.upper() for w in words):
            return v if isinstance(v, str) else json.dumps(v)
    return ""


def detail(d):
    """What the full mwTab file adds: sample type, data size and the sample groups."""
    blocks = {k: v for k, v in d.items() if k.endswith("_METABOLITE_DATA")}
    block = next(iter(blocks.values()), {}) if blocks else {}
    binned = isinstance(d.get("Data"), list) and d["Data"] and "Bin range(ppm)" in d["Data"][0]
    factors = d.get("SUBJECT_SAMPLE_FACTORS") or []
    groups = Counter()
    for f in factors:
        fac = f.get("Factors") if isinstance(f, dict) else None
        groups[" | ".join(f"{k}:{v}" for k, v in fac.items()) if isinstance(fac, dict) else str(fac or "")] += 1
    return {
        "sample_type": find_value(d.get("COLLECTION", {}), "SAMPLE_TYPE"),
        "data_block": next(iter(blocks), "") or ("NMR_BINNED_DATA" if binned else ""),
        "n_metabolites": len(block.get("Data", [])) if isinstance(block, dict) else 0,
        "n_samples": len(factors),
        "n_groups": len(groups),
        "has_control_group": int(any(CONTROL_WORDS.search(g) for g in groups)),
        "has_pooled_sample": int(any(CONTROL_WORDS_POOLED.search(g) for g in groups)),
        "groups": " || ".join(f"{g} (n={k})" for g, k in groups.most_common(6)),
    }


def survey():
    listing = os.path.join(DATA, "analyses.json")
    if not os.path.exists(listing):
        sys.exit("No analysis listing yet - run `fetch` first.")
    analyses = rows(json.load(open(listing)))
    species = {}
    for r in rows(json.load(open(os.path.join(DATA, "studies_species.json")))):
        species.setdefault(r.get("Study ID"), []).append(r.get("Latin name", ""))
    titles = {r.get("study_id"): r.get("study_title", "")
              for r in rows(json.load(open(os.path.join(DATA, "studies_summary.json"))))}

    out, bad = [], 0
    for a in analyses:
        an, st = a.get("analysis_id"), a.get("study_id")
        r = {"analysis_id": an, "study_id": st,
             "species": "; ".join(sorted(set(species.get(st, [])))),
             "study_title": titles.get(st, ""),
             "analysis_type": a.get("analysis_type", ""),
             "units": " ".join(str(a.get("units") or "").split()),
             "unit_class": classify_unit(a.get("units")),
             "downloaded": 0}
        path = os.path.join(MWTAB_DIR, f"{an}.json.gz")
        if os.path.exists(path):
            try:
                with gzip.open(path, "rt") as f:
                    r.update(detail(json.load(f)))
                r["downloaded"] = 1
            except Exception as e:
                bad += 1
                print("  could not read", an, "-", e)
        out.append(r)

    fields = ["analysis_id", "study_id", "species", "study_title", "analysis_type", "units", "unit_class",
              "downloaded", "sample_type", "data_block", "n_metabolites", "n_samples", "n_groups",
              "has_control_group", "has_pooled_sample", "groups"]
    path = os.path.join(DATA, "mwb_analysis_survey.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(out)

    units = Counter((r["units"], r["unit_class"]) for r in out)
    with open(os.path.join(DATA, "mwb_unit_counts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["units", "unit_class", "n_analyses"])
        for (u, c), k in units.most_common():
            w.writerow([u, c, k])

    # ---- summary
    n = len(out)
    print(f"\n{n} analyses from {len({r['study_id'] for r in out})} studies\n")
    print("By unit class:")
    for c, k in Counter(r["unit_class"] for r in out).most_common():
        print(f"  {c:12s} {k:6d}  ({100 * k / n:.1f}%)")
    usable = [r for r in out if r["unit_class"] == "volumetric"]
    print(f"\nUsable (volumetric concentration): {len(usable)} analyses from "
          f"{len({r['study_id'] for r in usable})} studies")
    print("\nUsable analyses by species (top 12):")
    for v, k in Counter(r["species"] or "(blank)" for r in usable).most_common(12):
        print(f"  {k:5d}  {v}")
    got = [r for r in usable if r["downloaded"]]
    if got:
        print(f"\nOf the {len(got)} usable analyses downloaded ({bad} unreadable):")
        print(f"  {sum(r['has_control_group'] for r in got)} have a group named like a control, "
              f"{sum(r['has_pooled_sample'] for r in got)} a pooled/reference sample")
        print("  by sample type (top 12):")
        for v, k in Counter((r["sample_type"] or "(blank)").strip().lower() for r in got).most_common(12):
            print(f"    {k:5d}  {v}")
    print(f"\nWrote {os.path.relpath(path, ROOT)} and data/mwb/mwb_unit_counts.csv")


# ------------------------------------------------------------------ main
if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["fetch", "survey", "all"])
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0, help="fetch at most this many analyses (for a trial run)")
    p.add_argument("--all-units", action="store_true",
                   help="download every analysis, not only those reporting a concentration unit")
    a = p.parse_args()
    os.makedirs(DATA, exist_ok=True)
    if a.step in ("fetch", "all"):
        fetch(a.workers, a.limit, a.all_units)
    if a.step in ("survey", "all"):
        survey()
