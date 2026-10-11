"""
select_controls.py
Step 2 of the MetaboLights (MTBLS) source: for each candidate study, decide
which sample groups are healthy / untreated controls, and confirm the unit.

Same two stages as the Metabolomics Workbench source (pipeline/mwb/select_controls.py):
  1. automated screening - every sample group in every candidate study gets a
     suggestion (control / not_control / qc / unsure) and the reason for it;
  2. human review - you fill in `decision` and, once per study, `unit_confirmed`.
     Only groups with decision = control go on to extraction.

MetaboLights has no units field, so unlike Workbench each row also carries the
study's unit evidence: the units the text screen counted as results, the
sentence they came from, and the median MAF value. Read these (and the study
page, if needed) to fill in `unit_confirmed`, e.g. umol/L, nmol/mL, ng/mL, or
`relative` / `unclear` if the values are not concentrations.

Candidates are the studies survey_metabolights.py marked likely or possible,
restricted to mammals. By default only biofluid samples (blood, urine, CSF,
saliva) are listed, as for Workbench; --all-samples adds feces, tissue, cells
and other fluids.

Reads   data/metabolights/mtbls_study_survey.csv and data/metabolights/isa/
Writes  data/metabolights/mtbls_control_review.csv   one row per study x sample group

Re-running is safe: decisions, units and notes already typed into the review
file are kept (matched on study_id + group).

Usage:
    python pipeline/metabolights/select_controls.py
    python pipeline/metabolights/select_controls.py --all-samples

Groups are formed from the study's design factors only. MetaboLights studies
often record per-person details (age, sex, BMI, patient ID, symptom yes/no
flags) as factors; a factor is dropped from the grouping if it names such a
detail, has more than 8 distinct values, or is a yes/no flag that is not a
design variable (disease, treatment, group, smoking, time...). Nothing is
dropped from the data, only from how samples are grouped for review.

How a group is judged: exactly as for Workbench (see the docstring of
pipeline/mwb/select_controls.py), using the same rules, with air-exposure
controls ("conditioned fresh air", "room air", "filtered air") added, because
MetaboLights has inhalation studies.
"""
import argparse
import csv
import glob
import importlib.util
import os
import re
import sys
from collections import Counter, OrderedDict

csv.field_size_limit(sys.maxsize)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data", "metabolights")
ISA_DIR = os.path.join(DATA, "isa")
SURVEY = os.path.join(DATA, "mtbls_study_survey.csv")
OUT = os.path.join(DATA, "mtbls_control_review.csv")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# One set of control rules for both repositories.
mwb = load("mwb_select_controls", os.path.join(ROOT, "pipeline", "mwb", "select_controls.py"))
mwb.CONTROL = re.compile(mwb.CONTROL.pattern +
                         r"|fresh air|room air|filtered air|clean air|air control|\bair\b(?! pollut)"
                         r"|\bcon\b|\bctrs?\b|\bhc\b", re.I)          # CON, CTR, HC: common abbreviations

# Factor names that look like timing ("TreatPhase1") but carry the treatment.
DESIGN_NAME = re.compile(r"treat|exposure|condition|status|group|diet|disease|diagnos|genotype", re.I)


def normalise(fac):
    """Rewrite factor values that the shared rules would misread.

    - a factor named like "control" with value TRUE/yes is a control group,
      and FALSE/no is not (MTBLS449: "control:TRUE");
    - "STD" in a diet factor is standard diet, not a QC standard (MTBLS327);
    - a design factor whose name happens to contain a timing word, such as
      "TreatPhase1", is renamed so the shared rules do not skip it (MTBLS143).
    """
    out = OrderedDict()
    for k, v in fac.items():
        low = v.strip().lower()
        if re.search(r"\bcontrol\b", k, re.I) and low in ("true", "yes", "y", "1"):
            v = "control"
        elif re.search(r"\bcontrol\b", k, re.I) and low in ("false", "no", "n", "0"):
            v = "case"
        elif re.search(r"diet", k, re.I) and low in ("std", "std diet", "std chow"):
            v = "standard diet"
        if mwb.NEUTRAL_KEYS.search(k) and DESIGN_NAME.search(k):
            k = "Design factor (" + re.sub(mwb.NEUTRAL_KEYS, "", k) + ")"
        out[k] = v
    return out


def judge(fac, n_groups):
    return mwb.judge(normalise(fac), n_groups)
survey_mod = load("survey_metabolights", os.path.join(HERE, "survey_metabolights.py"))

MAMMALS = {
    "homo sapiens", "mus musculus", "rattus norvegicus", "sus scrofa", "sus scrofa domesticus",
    "bos taurus", "ovis aries", "capra hircus", "canis lupus familiaris", "felis catus",
    "equus caballus", "macaca mulatta", "macaca fascicularis", "oryctolagus cuniculus",
    "cavia porcellus", "mesocricetus auratus", "callithrix jacchus",
}
EXTRA_FLUIDS = [("milk", r"\bmilk\b|colostrum"), ("other fluid", r"synovi|lavage|\bbalf\b|sweat|bile|"
                r"follicular|amniotic|tears|seminal|exhaled breath")]


def is_mammal(organism):
    o = re.split(r"[;:]", (organism or "").lower())[0].strip()
    return o in MAMMALS


def bucket(part):
    b = mwb.bucket(part)
    if b in ("other", "(unknown)"):
        for name, pat in EXTRA_FLUIDS:
            if re.search(pat, (part or "").lower()):
                return name
    return b


def unit_evidence(sid):
    """The units counted as results, and the sentence the first one came from."""
    inv_path = next(iter(glob.glob(os.path.join(ISA_DIR, sid, "i_*.txt"))), None)
    if not inv_path:
        return ""
    d = survey_mod.read_investigation(inv_path)
    text = " ".join(survey_mod.inv(d, k) for k in
                    ("Study Title", "Study Description", "Study Protocol Description", "Study Design Type"))
    text = re.sub(r"<[^>]+>", " ", text)          # some descriptions are HTML
    for m in survey_mod.UNIT.finditer(text):
        near = text[max(0, m.start() - 50): m.end() + 50]
        if survey_mod.REAGENT.search(near):
            continue
        wide = text[max(0, m.start() - 90): m.end() + 40]
        if survey_mod.RESULT.search(wide):
            return "..." + " ".join(text[max(0, m.start() - 120): m.end() + 60].split()) + "..."
    return ""


# Factors that describe the individual, not the study design. MetaboLights
# studies often record them as factors, which would otherwise make every
# participant a group of one.
PERSONAL = re.compile(r"subject|patient|participant|donor|individual|\bid\b|_id\b|replicate|sample pair|"
                      r"\bage\b|\bbmi\b|\bsex\b|gender|ethni|race|weight|height|series|batch|dataset|"
                      r"\bdate\b|\brun\b|plate|injection|order", re.I)
# A design factor names a condition of interest even when its values are yes/no.
DESIGN_KEY = re.compile(r"disease|diagnos|status|group|treat|condition|control|cohort|genotype|diet|"
                        r"smok|exposure|interven|case|arm|stag|time|visit|phase|sample type", re.I)
FLAG_VALUES = {"", "yes", "no", "y", "n", "0", "1", "true", "false", "none", "-", "--", "na", "n/a"}
MAX_LEVELS = 8          # a factor with more distinct values than this is per-person, not a design factor


def design_factors(rows, factor_cols):
    """The factor columns that define the study's groups."""
    keep = []
    for c in factor_cols:
        key = c[len("Factor Value"):].strip(" []")
        vals = [(r.get(c) or "").strip() for r in rows]
        levels = {v for v in vals if v}
        if not levels or PERSONAL.search(key):
            continue
        numeric = sum(bool(re.fullmatch(r"[-+]?\d+(\.\d+)?", v)) for v in levels)
        if len(levels) > MAX_LEVELS or (numeric > len(levels) / 2 and not DESIGN_KEY.search(key)):
            continue
        if {v.lower() for v in levels} <= FLAG_VALUES and not DESIGN_KEY.search(key):
            continue                                    # symptom checklists and other yes/no flags
        keep.append(c)
    return keep


def samples(sid):
    """One entry per sample in the study's sample sheet(s), with the group it falls in.

    Returns dicts with sample (the Sample Name), group (the key shown in the
    review file), factors, organism and part. prepare_mtbls.py uses this to
    find the samples behind each control group, so the grouping is defined once.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(ISA_DIR, sid, "s_*.txt"))):
        rows = survey_mod.read_table(path)
        if not rows:
            continue
        cols = list(rows[0].keys())
        org_col = next((c for c in cols if c and re.fullmatch(r"Characteristics\s*\[\s*Organism\s*\]", c.strip(), re.I)), None)
        part_col = next((c for c in cols if c and re.fullmatch(r"Characteristics\s*\[\s*Organism part\s*\]", c.strip(), re.I)), None)
        type_col = next((c for c in cols if c and re.fullmatch(r"Characteristics\s*\[\s*Sample type\s*\]", c.strip(), re.I)), None)
        factor_cols = design_factors(rows, [c for c in cols if c and c.startswith("Factor Value")])
        for r in rows:
            fac = OrderedDict()
            if type_col and (r.get(type_col) or "").strip():
                fac["Sample type"] = r[type_col].strip()       # lets QC / blank samples be recognised
            for c in factor_cols:
                fac[c[len("Factor Value"):].strip(" []")] = (r.get(c) or "").strip()
            out.append({
                "sample": (r.get("Sample Name") or "").strip(),
                "group": " | ".join(f"{k}:{v}" for k, v in fac.items()) or "(no factors)",
                "factors": fac,
                "organism": (r.get(org_col) or "").strip() if org_col else "",
                "part": (r.get(part_col) or "").strip() if part_col else "",
            })
    return out


def sample_groups(sid):
    """(group key, factor dict, n samples, organism, organism part) per group in the sample sheet(s)."""
    groups = OrderedDict()
    for smp in samples(sid):
        g = groups.setdefault((smp["group"], smp["organism"], smp["part"]), [smp["factors"], 0])
        g[1] += 1
    return [(k[0], v[0], v[1], k[1], k[2]) for k, v in groups.items()]


def main(all_samples):
    if not os.path.exists(SURVEY):
        sys.exit("Run survey_metabolights.py survey first.")
    survey = [r for r in csv.DictReader(open(SURVEY, encoding="utf-8"))
              if r["concentration_screen"] in ("likely", "possible")]

    kept = {}
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT, encoding="utf-8-sig")):
            if r.get("decision") or r.get("unit_confirmed") or r.get("notes"):
                kept[(r["study_id"], r["group"], r["organism_part"])] = (
                    r.get("decision", ""), r.get("unit_confirmed", ""), r.get("notes", ""))

    out = []
    for s in survey:
        sid = s["study_id"]
        groups = [g for g in sample_groups(sid) if is_mammal(g[3])]
        groups = [g for g in groups if all_samples or bucket(g[4]) in mwb.BIOFLUIDS]
        if not groups:
            continue
        evidence = unit_evidence(sid)
        n_bio = len({g[0] for g in groups if not mwb.QC.search(g[0])})
        for key, fac, n, organism, part in groups:
            sug, why = judge(fac, max(n_bio, 1))
            dec, unit, notes = kept.get((sid, key, part), ("", "", ""))
            out.append({
                "study_id": sid, "species": organism, "organism_part": part,
                "sample_group": bucket(part), "group": key, "n_samples": n,
                "suggestion": sug, "reason": why,
                "decision": dec, "unit_confirmed": unit, "notes": notes,
                "screen": s["concentration_screen"], "result_units": s["result_units"],
                "maf_median_value": s["maf_median_value"], "unit_evidence": evidence,
                "study_title": s["title"],
                "study_url": "https://www.ebi.ac.uk/metabolights/" + sid,
            })

    order = {"control": 0, "unsure": 1, "not_control": 2, "qc": 3}
    out.sort(key=lambda r: (int(r["study_id"][5:]), r["organism_part"], order[r["suggestion"]]))
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:   # -sig so Excel reads µ correctly
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    studies = {r["study_id"] for r in out}
    to_review = {r["study_id"] for r in out if r["suggestion"] in ("control", "unsure")}
    print(f"{len(out)} groups from {len(studies)} studies")
    for k, v in Counter(r["suggestion"] for r in out).most_common():
        print(f"  {k:12s} {v}")
    print(f"{len(to_review)} studies have at least one control or unsure group to review")
    print("Studies by sample group:", dict(Counter(b for _, b in {(r["study_id"], r["sample_group"]) for r in out})))
    print("Studies by species:", dict(Counter(sp for _, sp in {(r['study_id'], r['species']) for r in out})))
    if kept:
        print(f"Kept {len(kept)} decisions/units/notes from the previous review file")
    print(f"\nWrote {os.path.relpath(OUT, ROOT)}")
    print("For each study: fill in `unit_confirmed` once, and `decision` "
          "(control / not_control / exclude) for its control and unsure rows.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all-samples", action="store_true",
                   help="include feces, tissue, cells and other fluids, not only biofluids")
    main(p.parse_args().all_samples)
