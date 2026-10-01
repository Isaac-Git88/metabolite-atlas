"""
prepare_mwb.py
Step 4 of the Metabolomics Workbench (MWB) source: turn the control groups chosen
in data/mwb/mwb_control_review.csv into the clean-CSV shape the shared parser
reads, so MWB joins the atlas through the shared pipeline steps 1-3 like every other source.

Two steps:
  1. names - give every metabolite name in the control analyses a structure
             (InChIKey). Writes data/mwb/mwb_name_map.csv.
  2. build - keep only control-group samples, convert to umol/L, collapse each
             study to one value per metabolite. Writes
             data/mwb/mwb_concentrations_clean.csv.

Usage:
    python pipeline/mwb/prepare_mwb.py names            # uses the RefMet web service (cached)
    python pipeline/mwb/prepare_mwb.py names --offline  # local matching only
    python pipeline/mwb/prepare_mwb.py build
    python pipeline/1_parse_concentrations.py --source MWB
    python pipeline/2_build_database.py
    python pipeline/3_build_explorer.py

How names get a structure, in order:
  1. the study's own InChIKey column, where it gave one (about 1% of rows);
  2. the study's own HMDB ID column -> data/hmdb/hmdb_inchikey_lookup.csv;
  3. the cleaned name matches an HMDB metabolite name exactly (case-insensitive);
  4. RefMet, the Metabolomics Workbench's own name standard: the name is
     matched to a RefMet standard name, which carries a formula and, through
     PubChem, an InChIKey. Answers are cached in data/mwb/refmet_cache.json.
  Names that get no structure are left out and listed in the name map, so
  every row that enters the atlas merges with the other sources on an exact
  InChIKey match - the same rule the yeast and E. coli data follow.

Units: everything is converted to umol/L. Molar units (nM, uM, mM, nmol/mL...)
are a fixed scaling. Mass units (ng/mL, mg/dL...) are divided by the
metabolite's molar mass, computed from its formula; if the formula is unknown
the row is left out rather than guessed.

One value per study: a study's control samples (all control groups pooled,
e.g. both sexes or several baseline timepoints) are summarised as
mean +/- SD (min - max). If a study measured the same metabolite in more than one
analysis, the analysis with the most samples is used, so each study counts
once per metabolite and biospecimen - the same way HMDB counts one value per
publication. Zero, negative and non-numeric values (below detection limit,
missing) are left out.

Unit check: a study's unit label is sometimes wrong (one labels micromolar
values "mM"). Each human study is compared with HMDB on the metabolites both
report in the same biospecimen. If at least 10 are shared and the study's
typical value is more than 30-fold away (|median log10 ratio| > 1.5), the
whole study is left out - not corrected, because the true unit is a guess.
Every study's result is written to data/mwb/mwb_study_check.csv.
The same check runs for every species against HMDB's human values (blood
chemistry rarely differs 30-fold between mammals). Studies found wrong by
inspection are in EXCLUDE_STUDIES with their reason. Finally, single values
more than 1000-fold from HMDB, or above 200 mmol/L outside urine, are left out
and listed in data/mwb/mwb_value_check.csv.
"""
import argparse
import csv
import gzip
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
MWB = os.path.join(DATA, "mwb")
MWTAB_DIR = os.path.join(MWB, "mwtab")
REVIEW = os.path.join(MWB, "mwb_control_review.csv")
NAME_MAP = os.path.join(MWB, "mwb_name_map.csv")
CACHE = os.path.join(MWB, "refmet_cache.json")
OUT = os.path.join(MWB, "mwb_concentrations_clean.csv")
HMDB_LOOKUP = os.path.join(DATA, "hmdb", "hmdb_inchikey_lookup.csv")
HMDB_PARSED = os.path.join(DATA, "parsed", "hmdb_concentrations_parsed.csv")
CHECK = os.path.join(MWB, "mwb_study_check.csv")
VALUE_CHECK = os.path.join(MWB, "mwb_value_check.csv")
CHECK_MIN_SHARED, CHECK_MAX_LOG10 = 10, 1.5
VALUE_MAX_LOG10 = 3          # a single value >1000-fold from HMDB is left out
VALUE_MAX_UMOL = 2e5         # >200 mmol/L is impossible for one metabolite outside urine

# Studies left out after inspection, with the reason. Each was found by the
# checks below or by looking at the largest values per study.
EXCLUDE_STUDIES = {
    "ST000633": "neuromodulators in rat plasma ~1000x above physiological (dopamine 7 umol/L) - unit label likely wrong",
    "ST001160": "values ~100x below physiological (taurine 0.6 umol/L) - unit label likely wrong",
    "ST002086": "NMR lipoprotein panel (lipoprotein fractions, not single metabolites); 'TG' mis-matched to thioguanine",
    "ST003105": "labelled mM but values ~1000x above physiological - unit label likely wrong",
    "ST003746": "steroid hormones ~10,000x above physiological (corticosterone 24 mmol/L) - unit label likely wrong",
    "ST005031": "plasma acetate 23 mmol/L, implausible; short-chain fatty acid panel not trusted",
}
BASE = "https://www.metabolomicsworkbench.org/rest"

sys.path.insert(0, HERE)
from select_controls import bucket, sample_type  # noqa: E402  same rules as the review

INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
BIOSPECIMEN = {"blood": "Blood", "urine": "Urine",
               "csf": "Cerebrospinal Fluid (CSF)", "saliva": "Saliva"}
COMMON = {"Homo sapiens": "Human", "Mus musculus": "Mouse", "Rattus norvegicus": "Rat",
          "Bos taurus": "Cow", "Macaca mulatta": "Rhesus macaque", "Canis lupus familiaris": "Dog",
          "Oncorhynchus mykiss": "Rainbow trout", "Cervus nippon": "Sika deer",
          "Megalobrama amblycephala": "Blunt snout bream", "Ovis aries": "Sheep",
          "Sus scrofa": "Pig", "Saccharomyces cerevisiae": "Yeast", "Escherichia coli": "E. coli"}
TAXON = {"Homo sapiens": 9606, "Mus musculus": 10090, "Rattus norvegicus": 10116, "Bos taurus": 9913,
         "Macaca mulatta": 9544, "Canis lupus familiaris": 9615, "Oncorhynchus mykiss": 8022,
         "Cervus nippon": 9863, "Megalobrama amblycephala": 75352, "Ovis aries": 9940, "Sus scrofa": 9823}

FIELDS = ["hmdb_id", "metabolite_name", "biospecimen",
          "concentration_value_raw", "concentration_units",
          "subject_age", "subject_sex", "subject_condition",
          "pubmed_ids", "reference_texts", "native_id", "inchikey",
          "species_scientific", "species_common", "ncbi_taxon_id"]


# ------------------------------------------------------------------ shared helpers
def load_json_gz(an):
    with gzip.open(os.path.join(MWTAB_DIR, an + ".json.gz"), "rt") as f:
        return json.load(f)


def group_key(fac):
    """Exactly as select_controls.py builds it, so review rows match samples."""
    fac = fac if isinstance(fac, dict) else {"Factor": str(fac or "")}
    return " | ".join(f"{k}:{v}" for k, v in fac.items())


def data_block(d):
    for k, v in d.items():
        if k.endswith("_METABOLITE_DATA") and isinstance(v, dict):
            return v
    return {}


def control_analyses():
    chosen = defaultdict(set)
    for r in csv.DictReader(open(REVIEW, encoding="utf-8-sig")):
        if r["decision"].strip().lower() == "control":
            chosen[r["analysis_id"]].add(r["group"])
    return chosen


def clean_name(name):
    n = " ".join(str(name or "").split())
    n = re.sub(r"[\^'*†‡]+$", "", n).strip()
    n = re.sub(r"^([A-Z])_([A-Z]-)", r"\1,\2", n)                # "N_N-dimethyl" -> "N,N-dimethyl"
    m = re.match(r"^[A-Za-z0-9]{1,10}_(?=.*[a-z]{3})(.+)$", n)   # "1MH_1-Methylhistidine" -> name
    if m:
        n = m.group(1)
    n = re.sub(r"\s*\((is|internal standard)\)\s*$", "", n, flags=re.I)
    return n.strip()


def pad_hmdb(h):
    h = str(h or "").strip().upper()
    m = re.match(r"^HMDB0*(\d+)$", h)
    return "HMDB%07d" % int(m.group(1)) if m else ""


# ------------------------------------------------------------------ molar mass from a formula
ATOMIC = {"H": 1.008, "C": 12.011, "N": 14.007, "O": 15.999, "P": 30.974, "S": 32.06, "Cl": 35.45,
          "Br": 79.904, "I": 126.904, "F": 18.998, "Na": 22.990, "K": 39.098, "Ca": 40.078,
          "Mg": 24.305, "Fe": 55.845, "Zn": 65.38, "Cu": 63.546, "Se": 78.971, "Co": 58.933,
          "Si": 28.085, "B": 10.81, "Li": 6.94, "Mn": 54.938, "As": 74.922, "Hg": 200.59}


def molar_mass(formula):
    f = re.sub(r"[+\-]\d*$", "", str(formula or "").strip())
    if not f or not re.fullmatch(r"([A-Z][a-z]?\d*)+", f):
        return None
    total = 0.0
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", f):
        if el not in ATOMIC:
            return None
        total += ATOMIC[el] * (int(n) if n else 1)
    return total or None


# ------------------------------------------------------------------ units -> umol/L
PREFIX = {"": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
          "milli": 1e-3, "micro": 1e-6, "nano": 1e-9, "pico": 1e-12, "femto": 1e-15}
VOLUME = {"l": 1.0, "dl": 0.1, "ml": 1e-3, "ul": 1e-6}


def unit_factor(unit):
    """('molar', f) where umol/L = value * f, ('mass', f) where g/L = value * f, or None."""
    u = " ".join(str(unit or "").lower().replace("µ", "u").replace("μ", "u").split())
    u = re.sub(r"^(concentration|conc\.?)\s*", "", u).strip(" ()")
    u = re.sub(r"\s*\((plasma|serum|blood|urine)\)$", "", u)
    u = re.sub(r"\s*(-|of)\s*(plasma|serum|blood|urine)$", "", u)            # "umol/L of plasma", "nmol/L-serum"
    u = re.sub(r"\s+(plasma|serum|blood|urine)$", "", u)
    u = re.sub(r"^micro\s*molars?$", "um", u)
    u = u.replace("micromolar", "um").replace("millimolar", "mm").replace("nanomolar", "nm")
    m = re.fullmatch(r"(p|n|u|m|f)?m", u)                                  # uM, nM, mM
    if m:
        return "molar", PREFIX[m.group(1) or ""] / 1e-6
    m = re.fullmatch(r"(milli|micro|nano|pico|femto|p|n|u|m|f)?(mol|mole|moles|g)\s*(/|per)\s*"
                     r"(100\s*)?(l|dl|ml|ul)", u)
    if not m:
        return None
    pre, what, _, hundred, vol = m.groups()
    per_l = PREFIX[pre or ""] / (VOLUME[vol] * (100 if hundred else 1))
    if what == "g":
        return "mass", per_l
    return "molar", per_l / 1e-6


# ------------------------------------------------------------------ step 1: names
def collect_names():
    """Every distinct metabolite in the control analyses, with any IDs the study gave."""
    names = {}
    for an in sorted(control_analyses()):
        d = load_json_gz(an)
        blk = data_block(d)
        units_kind = (unit_factor(blk.get("Units")) or ("?",))[0]
        ids = {}
        for m in blk.get("Metabolites") or []:
            low = {k.lower().strip(): str(v).strip() for k, v in m.items()}
            nm = low.get("metabolite") or low.get("metabolite_name") or ""
            ids[nm] = {
                "inchikey": next((v for k, v in low.items() if "inchi" in k and INCHIKEY_RE.match(v)), ""),
                "hmdb": next((pad_hmdb(v) for k, v in low.items() if "hmdb" in k and pad_hmdb(v)), ""),
                "refmet": low.get("refmet name/standardized name*") or low.get("standardized name") or "",
            }
        for row in blk.get("Data") or []:
            nm = row.get("Metabolite") or row.get("metabolite_name") or ""
            if not nm:
                continue
            e = names.setdefault(nm, {"inchikey": "", "hmdb": "", "refmet": "", "needs_mass": False})
            for k, v in ids.get(nm, {}).items():
                e[k] = e[k] or v
            e["needs_mass"] |= units_kind == "mass"
    return names


def refmet_lookup(names, workers):
    import requests
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [n for n in names if n not in cache]
    print(f"RefMet: {len(names)} names, {len(names) - len(todo)} cached, {len(todo)} to ask")
    s = requests.Session()
    s.headers["User-Agent"] = "metabolite-concentration-atlas (university research project)"

    def get(url):
        for attempt in range(4):
            try:
                r = s.get(url, timeout=60)
                if r.status_code == 200:
                    t = r.text.strip()
                    return json.loads(t) if t and t not in ("[]", "{}") else {}
                if r.status_code in (400, 404):
                    return {}
            except Exception:
                pass
            time.sleep(2 ** attempt)
        return None

    def first(x):
        if isinstance(x, dict) and x and all(isinstance(v, dict) for v in x.values()):
            return next(iter(x.values()))
        return x if isinstance(x, dict) else {}

    def job(name):
        out = {}
        m = first(get(f"{BASE}/refmet/match/{quote(name, safe='')}"))
        if m is None:
            return name, None
        ref = (m or {}).get("refmet_name", "")
        if ref and ref != "-":
            out.update(refmet_name=ref, formula=m.get("formula", ""))
            info = first(get(f"{BASE}/refmet/name/{quote(ref, safe='')}/all")) or {}
            out["formula"] = out["formula"] or info.get("formula", "")
            ik = next((v for k, v in info.items() if "inchi" in k.lower() and INCHIKEY_RE.match(str(v))), "")
            cid = str(info.get("pubchem_cid", "") or "").strip()
            if not ik and cid.isdigit():
                c = first(get(f"{BASE}/compound/pubchem_cid/{cid}/inchi_key")) or {}
                ik = next((v for v in c.values() if INCHIKEY_RE.match(str(v))), "")
            out["inchikey"] = ik
            out["pubchem_cid"] = cid
        return name, out

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for name, res in ex.map(job, todo):
            if res is not None:
                cache[name] = res
            done += 1
            if done % 100 == 0:
                json.dump(cache, open(CACHE, "w"))
                print(f"  {done}/{len(todo)}")
    json.dump(cache, open(CACHE, "w"))
    return cache


def names_step(offline, workers):
    names = collect_names()
    look = list(csv.DictReader(open(HMDB_LOOKUP, encoding="utf-8")))
    hmdb_ik = {r["hmdb_id"]: r["inchikey"] for r in look if r["inchikey"]}
    by_name = {}
    for r in look:
        if r["inchikey"]:
            by_name.setdefault(r["metabolite_name"].strip().lower(), (r["hmdb_id"], r["inchikey"]))
    ik_hmdb = {v: k for k, v in hmdb_ik.items()}

    rows, need_refmet = {}, []
    for raw, e in names.items():
        cn = clean_name(raw)
        r = {"name": raw, "clean_name": cn, "inchikey": "", "hmdb_id": "", "matched_name": "",
             "formula": "", "method": ""}
        if e["inchikey"]:
            r.update(inchikey=e["inchikey"], method="study_inchikey")
        elif e["hmdb"] and e["hmdb"] in hmdb_ik:
            r.update(inchikey=hmdb_ik[e["hmdb"]], hmdb_id=e["hmdb"], method="study_hmdb_id")
        else:
            for cand in (cn, e["refmet"]):
                hit = by_name.get(str(cand).strip().lower())
                if hit:
                    r.update(hmdb_id=hit[0], inchikey=hit[1], matched_name=cand, method="hmdb_name")
                    break
        if r["inchikey"] and not r["hmdb_id"]:
            r["hmdb_id"] = ik_hmdb.get(r["inchikey"], "")
        if not r["inchikey"] or e["needs_mass"]:
            need_refmet.append(cn or raw)
        rows[raw] = r

    if not offline and need_refmet:
        cache = refmet_lookup(sorted(set(need_refmet)), workers)
        for raw, r in rows.items():
            c = cache.get(r["clean_name"] or raw) or {}
            r["formula"] = r["formula"] or c.get("formula", "")
            if not r["inchikey"]:
                hit = by_name.get(c.get("refmet_name", "").strip().lower())
                if hit:
                    r.update(hmdb_id=hit[0], inchikey=hit[1], matched_name=c["refmet_name"], method="refmet_name")
                elif c.get("inchikey"):
                    r.update(inchikey=c["inchikey"], matched_name=c.get("refmet_name", ""), method="refmet_pubchem")
                    r["hmdb_id"] = ik_hmdb.get(r["inchikey"], "")
    elif offline:
        print("--offline: RefMet not asked; names without a local match stay unresolved")

    out = sorted(rows.values(), key=lambda r: r["name"].lower())
    with open(NAME_MAP, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    c = Counter(r["method"] or "unresolved" for r in out)
    print(f"\n{len(out)} distinct names")
    for k, v in c.most_common():
        print(f"  {k:16s} {v:6d}")
    print(f"Wrote {os.path.relpath(NAME_MAP, ROOT)}")


# ------------------------------------------------------------------ step 2: build
def unit_check(rows):
    """Leave out studies and single values that cannot be right (see the docstring)."""
    study = lambda r: r["reference_texts"].split()[2]
    mean = lambda r: float(r["concentration_value_raw"].split()[0])
    ref = {}
    if os.path.exists(HMDB_PARSED):
        look = {r["hmdb_id"]: r["inchikey"] for r in csv.DictReader(open(HMDB_LOOKUP, encoding="utf-8"))}
        vals = defaultdict(list)
        for r in csv.DictReader(open(HMDB_PARSED, encoding="utf-8")):
            ik = look.get(r["hmdb_id"])
            if ik and r["is_comparable"] == "1" and r["value_representative"]:
                vals[(ik, r["biospecimen"])].append(float(r["value_representative"]))
        ref = {k: sorted(v)[len(v) // 2] for k, v in vals.items() if sorted(v)[len(v) // 2] > 0}
    else:
        print("HMDB comparison skipped: run 1_parse_concentrations.py for HMDB first")

    per = defaultdict(list)
    for r in rows:
        k = (r["inchikey"], r["biospecimen"])
        if k in ref:
            per[study(r)].append(math.log10(mean(r) / ref[k]))
    dropped, report = {}, []
    for st in sorted({study(r) for r in rows}):
        l = sorted(per.get(st, []))
        med = l[len(l) // 2] if l else None
        if st in EXCLUDE_STUDIES:
            dropped[st] = "left out: " + EXCLUDE_STUDIES[st]
        elif len(l) >= CHECK_MIN_SHARED and abs(med) > CHECK_MAX_LOG10:
            dropped[st] = "left out: likely unit-label error"
        report.append({"study_id": st, "species": next(r["species_common"] for r in rows if study(r) == st),
                       "shared_with_hmdb": len(l),
                       "median_log10_ratio": "" if med is None else "%.2f" % med,
                       "typical_fold_vs_hmdb": "" if med is None else "%.3g" % 10 ** med,
                       "result": dropped.get(st) or ("ok" if len(l) >= CHECK_MIN_SHARED else "too few shared to check")})
    with open(CHECK, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0].keys()))
        w.writeheader()
        w.writerows(report)

    kept, bad_values = [], []
    for r in rows:
        if study(r) in dropped:
            continue
        k, v = (r["inchikey"], r["biospecimen"]), mean(r)
        why = ""
        if k in ref and abs(math.log10(v / ref[k])) > VALUE_MAX_LOG10:
            why = "%.3g-fold from HMDB median (%.4g umol/L)" % (v / ref[k], ref[k])
        elif r["biospecimen"] != "Urine" and v > VALUE_MAX_UMOL:
            why = "above 200 mmol/L"
        if why:
            bad_values.append({"study_id": study(r), "metabolite_name": r["metabolite_name"],
                               "species": r["species_common"], "biospecimen": r["biospecimen"],
                               "mean_umol_per_L": "%.4g" % v, "reason": why})
        else:
            kept.append(r)
    with open(VALUE_CHECK, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["study_id", "metabolite_name", "species", "biospecimen",
                                          "mean_umol_per_L", "reason"])
        w.writeheader()
        w.writerows(bad_values)
    print("Checks: %d studies left out (%s); %d single values left out (see %s)"
          % (len(dropped), ", ".join(sorted(dropped)), len(bad_values), os.path.relpath(VALUE_CHECK, ROOT)))
    return kept


def fmt(x):
    return "%.6g" % x


def build_step():
    if not os.path.exists(NAME_MAP):
        sys.exit("Run `names` first.")
    nmap = {r["name"]: r for r in csv.DictReader(open(NAME_MAP, encoding="utf-8"))}
    titles = {}
    for r in csv.DictReader(open(os.path.join(MWB, "mwb_analysis_survey.csv"), encoding="utf-8")):
        titles[r["study_id"]] = r["study_title"]

    stats = Counter()
    best = {}   # (study, species, biospecimen, inchikey) -> candidate with most samples
    for an, groups in sorted(control_analyses().items()):
        d = load_json_gz(an)
        st = (d.get("METABOLOMICS WORKBENCH") or {}).get("STUDY_ID", "")
        subj = d.get("SUBJECT") or {}
        species = (subj.get("SUBJECT_SPECIES") or "").strip()
        if not species or ";" in species or "," in species:
            stats["analysis skipped: species unclear"] += 1
            continue
        try:
            taxon = int(str(subj.get("TAXONOMY_ID", "")).strip())
        except ValueError:
            taxon = TAXON.get(species, "")
        blk = data_block(d)
        uf = unit_factor(blk.get("Units"))
        if not uf:
            stats["analysis skipped: unit not convertible (%s)" % blk.get("Units")] += 1
            continue

        ssf = d.get("SUBJECT_SAMPLE_FACTORS") or []
        all_groups = [s.get("Factors") for s in ssf if isinstance(s, dict)]
        default_bio = bucket(sample_type(d, [g for g in all_groups if isinstance(g, dict)]) or titles.get(st, ""))
        sample_bio = {}
        for s in ssf:
            if not isinstance(s, dict):
                continue
            key = group_key(s.get("Factors"))
            if key not in groups:
                continue
            fac = s.get("Factors") if isinstance(s.get("Factors"), dict) else {}
            src = next((str(v) for k, v in fac.items() if re.search(r"sample ?(source|type)|tissue|matrix", k, re.I)), "")
            b = bucket(src) if src and bucket(src) in BIOSPECIMEN else default_bio
            if b in BIOSPECIMEN:
                sample_bio[str(s.get("Sample ID", "")).strip()] = BIOSPECIMEN[b]
        if not sample_bio:
            stats["analysis skipped: no biofluid control samples"] += 1
            continue

        for row in blk.get("Data") or []:
            nm = row.get("Metabolite") or row.get("metabolite_name") or ""
            m = nmap.get(nm)
            if not m or not m["inchikey"]:
                stats["rows left out: no structure"] += 1
                continue
            if uf[0] == "mass":
                mw = molar_mass(m["formula"])
                if not mw:
                    stats["rows left out: mass unit, formula unknown"] += 1
                    continue
                factor = uf[1] / mw * 1e6
            else:
                factor = uf[1]
            vals = defaultdict(list)
            for sid, bio in sample_bio.items():
                try:
                    v = float(str(row.get(sid, "")).strip())
                except ValueError:
                    continue
                if v > 0 and math.isfinite(v):
                    vals[bio].append(v * factor)
            for bio, vs in vals.items():
                k = (st, species, bio, m["inchikey"])
                if k not in best or len(vs) > len(best[k]["values"]):
                    best[k] = {"values": vs, "analysis": an, "map": m, "taxon": taxon, "name": nm}

    out = []
    for (st, species, bio, ik), c in sorted(best.items()):
        vs, n = c["values"], len(c["values"])
        mean = sum(vs) / n
        if n >= 2:
            sd = math.sqrt(sum((v - mean) ** 2 for v in vs) / (n - 1))
            raw = f"{fmt(mean)} +/- {fmt(sd)} ({fmt(min(vs))} - {fmt(max(vs))})"
        else:
            raw = fmt(mean)
        m = c["map"]
        out.append({
            "hmdb_id": m["hmdb_id"], "metabolite_name": m["matched_name"] or m["clean_name"] or c["name"],
            "biospecimen": bio, "concentration_value_raw": raw, "concentration_units": "umol/L",
            "subject_age": "", "subject_sex": "",
            "subject_condition": f"Control group, {n} sample{'s' if n != 1 else ''}",
            "pubmed_ids": "",
            "reference_texts": f"Metabolomics Workbench {st} ({c['analysis']}): {titles.get(st, '')}",
            "native_id": ik, "inchikey": ik,
            "species_scientific": species, "species_common": COMMON.get(species, species),
            "ncbi_taxon_id": c["taxon"],
        })
    out = unit_check(out)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)

    print(f"Rows written: {len(out):,} (one per study x species x biospecimen x metabolite)")
    print(f"Studies: {len({r['reference_texts'].split()[2] for r in out})}   "
          f"metabolites: {len({r['inchikey'] for r in out}):,}")
    print("By species:", dict(Counter(r["species_common"] for r in out).most_common()))
    print("By biospecimen:", dict(Counter(r["biospecimen"] for r in out).most_common()))
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v:,}")
    print(f"\nWrote {os.path.relpath(OUT, ROOT)}")
    print("Next: python pipeline/1_parse_concentrations.py --source MWB")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["names", "build"])
    p.add_argument("--offline", action="store_true", help="names: skip the RefMet web service")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    names_step(a.offline, a.workers) if a.step == "names" else build_step()
