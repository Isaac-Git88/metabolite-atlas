"""
select_controls.py
Step 3 of the Metabolomics Workbench (MWB) source: decide which sample groups in
each usable study are healthy / untreated controls.

A study's groups are free text (e.g. "Genotype:wt | Treatment:saline"), so this
is done in two stages:
  1. automated screening - every group in every usable analysis gets a suggestion
     (control / not_control / qc / unsure) and the reason for it;
  2. human review - you fill in the `decision` column. Only groups with
     decision = control go on to extraction.

Reads   data/mwb/mwb_analysis_survey.csv and data/mwb/mwtab/  (from survey_mwb.py)
Writes  data/mwb/mwb_control_review.csv   one row per analysis x sample group

Re-running is safe: decisions and notes already typed into the review file are
kept (matched on analysis_id + group), so the rules can be improved at any time.

Usage:
    python pipeline/mwb/select_controls.py               # biofluids only (blood, urine, CSF, saliva)
    python pipeline/mwb/select_controls.py --all-samples # include tissue, cells, faeces

How a group is judged. Each factor in the group (e.g. Genotype, Treatment) is
read on its own:
  - neutral factors (sample source, sex, age, timepoint, batch...) are ignored;
  - a factor whose value is control-like (control, healthy, vehicle, saline,
    wild type, placebo, sham, chow...) counts for control;
  - a factor with a disease/treatment word, or any other value, counts against.
  control      every non-neutral factor is control-like
  not_control  no factor is control-like
  unsure       a mix, or a single-group study (could be all healthy or all patients)
  qc           quality-control, blank or standard samples - never biological
"""
import argparse
import csv
import gzip
import json
import os
import re
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "mwb")
MWTAB_DIR = os.path.join(DATA, "mwtab")
SURVEY = os.path.join(DATA, "mwb_analysis_survey.csv")
OUT = os.path.join(DATA, "mwb_control_review.csv")

QC = re.compile(r"\bqc\b|qc[-_ ]|quality control|\bblanks?\b|process(ing)? blank|extraction blank|solvent|"
                r"calibra|internal standard|external ?standard|\bstd\b|standard mix|pooled qc|study pool|"
                r"\bpool(ed)?\b.*\b(qc|sample)|system suitability|reference standard|spike|"
                r"(source|type|group)\s*:\s*(standard|pool(ed)?|blank)\b", re.I)
REFERENCE = re.compile(r"\bsrm ?\d+|\bnist\b|reference material", re.I)
CONTROL = re.compile(r"\bcontrols?\b|\bctrl\b|\bctl\b|\bhealthy\b|\bhealth\b|\bnormal\b|\bbaseline\b|"
                     r"\bvehicle\b|\bveh\b\.?|\bsham\b|wild[- ]?type|\bwt\b|\buntreated\b|\bplacebo\b|"
                     r"\bsaline\b|\bpbs\b|\bchow\b|standard diet|normal diet|regular diet|\bnd\b|\bmock\b|"
                     r"\bnaive\b|\bnaïve\b|non[- ]?diabetic|\blean\b|\bnone\b|\bno treatment\b|\bunexposed\b|"
                     r"\bpre[- ]?(treatment|dose|op)|\bday ?0\b|\btime ?0\b|\b0 ?(h|hr|hour|min)\b|^0$|^(no|non|none)\b", re.I)
DISEASE = re.compile(r"patient|cancer|tumou?r|carcinoma|diabet|disease|infect|obes|knock ?out|\bko\b|"
                     r"treated|\bhfd\b|high[- ]fat|syndrome|injur|sepsis|fibrosis|failure|deficien|"
                     r"transgenic|mutant|\bcase\b|stroke|colitis|asthma|covid|hiv|nafld|nash|masld|pcos|hypertens|"
                     r"arthritis|alzheimer|parkinson|autism|preeclampsia|lupus|crohn|\bibd\b|cirrhosis|hepatitis|"
                     r"athlete|pregnan|smok", re.I)
NEUTRAL_KEYS = re.compile(r"sample ?source|sample ?type|tissue|matrix|specimen|\bsex\b|gender|\bage\b|"
                          r"time ?point|\btime\b|\bday\b|\bweek|batch|\brun\b|plate|replicate|subject|"
                          r"\brace\b|ethnic|\bbmi\b|site|fraction|organ|parity|cycle|phase|visit|collection ?point", re.I)
SAMPLE_KEYS = re.compile(r"sample ?source|sample ?type|tissue|matrix|specimen|organ", re.I)

BUCKETS = [("blood", r"plasma|serum|blood"), ("urine", r"urine"),
           ("csf", r"\bcsf\b|cerebrospinal"), ("saliva", r"saliva"),
           ("feces", r"feces|faeces|fecal|faecal|stool|cecal|caecal"),
           ("cells/culture", r"cell|bacteri|culture|media|medium|yeast"),
           ("tissue", r"liver|heart|brain|kidney|muscle|lung|adipose|tissue|ovary|intestin|colon|retina|spleen")]
BIOFLUIDS = {"blood", "urine", "csf", "saliva"}


def bucket(text):
    t = (text or "").lower()
    for name, pat in BUCKETS:
        if re.search(pat, t):
            return name
    return "(unknown)" if not t.strip() else "other"


def judge(factors, n_groups):
    """Suggestion and reason for one sample group, from its factor dict."""
    whole = " | ".join(f"{k}:{v}" for k, v in factors.items())
    if QC.search(whole):
        return "qc", "quality-control / blank / standard"
    if REFERENCE.search(whole):
        return "unsure", "reference material (e.g. NIST SRM 1950 is pooled healthy plasma) - check"
    pro, con, other = [], [], []
    for k, v in factors.items():
        v = str(v).strip()
        if NEUTRAL_KEYS.search(k) or v in ("", "-"):
            continue
        if DISEASE.search(v):
            con.append(f"{k}={v}")
        elif CONTROL.search(v):
            pro.append(f"{k}={v}")
        else:
            other.append(f"{k}={v}")
    if pro and not con and not other:
        if n_groups == 1:
            return "unsure", "only group in the study, labelled " + "; ".join(pro)
        return "control", "control-like: " + "; ".join(pro)
    if not pro:
        if n_groups == 1:
            return "unsure", "only group in the study - may be all healthy or all patients"
        return "not_control", ("disease/treatment: " + "; ".join(con)) if con else "no control-like factor"
    return "unsure", "mixed: control-like " + "; ".join(pro) + " but also " + "; ".join(con + other)


def sample_type(d, groups):
    st = ""
    col = d.get("COLLECTION", {}) or {}
    for k, v in col.items():
        if "SAMPLE_TYPE" in k.upper() and isinstance(v, str) and v.strip() not in ("", "-"):
            st = v.strip()
    if not st:  # fall back to a sample-source factor, if every group names one
        found = {v for g in groups for k, v in g.items() if SAMPLE_KEYS.search(k) and str(v).strip() not in ("", "-")}
        st = "; ".join(sorted(found))
    return st


def main(all_samples):
    survey = [r for r in csv.DictReader(open(SURVEY, encoding="utf-8"))
              if r["unit_class"] == "volumetric" and r["downloaded"] == "1"]

    kept = {}
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            if r.get("decision") or r.get("notes"):
                kept[(r["analysis_id"], r["group"])] = (r.get("decision", ""), r.get("notes", ""))

    out = []
    for s in survey:
        an = s["analysis_id"]
        with gzip.open(os.path.join(MWTAB_DIR, an + ".json.gz"), "rt") as f:
            d = json.load(f)
        groups = OrderedDict()
        for ssf in d.get("SUBJECT_SAMPLE_FACTORS") or []:
            fac = ssf.get("Factors") if isinstance(ssf, dict) else None
            fac = fac if isinstance(fac, dict) else {"Factor": str(fac or "")}
            key = " | ".join(f"{k}:{v}" for k, v in fac.items())
            groups.setdefault(key, [fac, 0])[1] += 1
        st = sample_type(d, [g[0] for g in groups.values()])
        b = bucket(st or s.get("study_title", ""))
        if not all_samples and b not in BIOFLUIDS:
            continue
        for key, (fac, n) in groups.items():
            sug, why = judge(fac, len(groups))
            dec, notes = kept.get((an, key), ("", ""))
            out.append({
                "analysis_id": an, "study_id": s["study_id"], "species": s["species"],
                "sample_type": st, "sample_group": b, "units": s["units"],
                "n_metabolites": s["n_metabolites"], "group": key, "n_samples": n,
                "suggestion": sug, "reason": why, "decision": dec, "notes": notes,
                "study_title": s["study_title"],
                "study_url": "https://www.metabolomicsworkbench.org/data/DRCCMetadata.php"
                             "?Mode=Study&StudyID=" + s["study_id"],
            })

    order = {"control": 0, "unsure": 1, "not_control": 2, "qc": 3}
    out.sort(key=lambda r: (r["study_id"], r["analysis_id"], order[r["suggestion"]]))
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:   # -sig so Excel reads µ correctly
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    an_with = {r["analysis_id"] for r in out if r["suggestion"] in ("control", "unsure")}
    print(f"{len(out)} groups from {len({r['analysis_id'] for r in out})} analyses "
          f"({len({r['study_id'] for r in out})} studies)")
    for k, v in Counter(r["suggestion"] for r in out).most_common():
        print(f"  {k:12s} {v}")
    print(f"{len(an_with)} analyses have at least one control or unsure group to review")
    print("By sample group:", dict(Counter(r["sample_group"] for r in out)))
    if kept:
        print(f"Kept {len(kept)} decisions/notes from the previous review file")
    print(f"\nWrote {os.path.relpath(OUT, ROOT)}")
    print("Fill in `decision` (control / not_control / exclude) for the control and unsure rows.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all-samples", action="store_true", help="include tissue, cells and faeces, not only biofluids")
    main(p.parse_args().all_samples)
