"""
prepare_mtbls.py
Step 3 of the MetaboLights (MTBLS) source: turn the control groups chosen in
data/metabolights/mtbls_control_review.csv into the clean-CSV shape the shared
parser reads, so MetaboLights joins the atlas through pipeline steps 1-3 like
every other source. It mirrors pipeline/mwb/prepare_mwb.py and reuses its unit
conversion, molar masses and species names, so both repositories are handled
the same way.

Two steps:
  1. names - give every metabolite in the control studies' MAFs a structure
             (InChIKey). Writes data/metabolights/mtbls_name_map.csv.
  2. build - keep only control samples, convert to umol/L, collapse each study
             to one value per metabolite and biospecimen. Writes
             data/metabolights/mtbls_concentrations_clean.csv.

Usage:
    python pipeline/metabolights/prepare_mtbls.py names             # online lookups allowed
    python pipeline/metabolights/prepare_mtbls.py names --offline   # local matching only
    python pipeline/metabolights/prepare_mtbls.py build
    python pipeline/1_parse_concentrations.py --source MTBLS
    python pipeline/2_build_database.py
    python pipeline/3_build_explorer.py

Which studies: every review row with decision = control whose study has a
concentration unit in unit_confirmed (not blank, `unclear` or `relative`).
Fill in a unit for a pending study and re-run; nothing else needs changing.

How a metabolite gets a structure, in order (first hit wins):
  1. the MAF's HMDB ID (database_identifier HMDBxxxx) -> data/hmdb/hmdb_inchikey_lookup.csv;
  2. the MAF's InChI string, looked up exactly in a local InChI -> InChIKey table
     built from the HMDB and/or BMDB XML downloads (data/hmdb/, data/bmdb/), which
     list both for every compound; built once, cached in data/metabolights/;
  3. the InChI string converted with RDKit, if installed (pip install rdkit);
  4. the cleaned name matching an HMDB metabolite name: exactly (case-insensitive),
     or else ignoring spacing, underscores and punctuation and an L-/D- prefix
     ('aspartic_acid' -> L-Aspartic acid), preferring the L- form;
  5. unless --offline: PubChem, by InChI and then by name (answers cached in
     data/metabolights/pubchem_cache.json).
  Lipid species written by class and carbon count ("PC(34:1)", "16:1 SM") and
  kit shorthand for acylcarnitines ("C10:1") have no single structure and stay
  unresolved, as in the Workbench data.
  Rows with no structure are left out and listed in the name map, so every row
  that enters the atlas merges with the other sources on an exact InChIKey.

Values: MAF values <= 0 or non-numeric are left out (MetaboLights files use 0,
-1 and -2 for missing or below detection). Units are converted to umol/L with
prepare_mwb.unit_factor; mass units (ng/mL...) are divided by the molar mass
from the MAF's chemical formula (or the name map's), and left out if unknown.

One value per study: a study's control samples (all control groups pooled) are
summarised as mean +/- SD (min - max). If a study reports the same metabolite in
more than one MAF (assay), the one with the most samples is used, so each study
counts once per metabolite and biospecimen.

Checks, as for Workbench: each study is compared with HMDB's human values on the
metabolites both report in the same biospecimen; with at least 10 shared and a
typical value more than 30-fold away, the whole study is left out (results in
mtbls_study_check.csv). Single values more than 1000-fold from HMDB, or above
200 mmol/L outside urine, are left out (mtbls_value_check.csv).
"""
import argparse
import csv
import glob
import importlib.util
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from urllib.parse import quote

csv.field_size_limit(sys.maxsize)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
MT = os.path.join(DATA, "metabolights")
ISA_DIR = os.path.join(MT, "isa")
REVIEW = os.path.join(MT, "mtbls_control_review.csv")
SURVEY = os.path.join(MT, "mtbls_study_survey.csv")
NAME_MAP = os.path.join(MT, "mtbls_name_map.csv")
INCHI_TABLE = os.path.join(MT, "inchi_inchikey_lookup.csv")
PUBCHEM_CACHE = os.path.join(MT, "pubchem_cache.json")
OUT = os.path.join(MT, "mtbls_concentrations_clean.csv")
CHECK = os.path.join(MT, "mtbls_study_check.csv")
VALUE_CHECK = os.path.join(MT, "mtbls_value_check.csv")
HMDB_LOOKUP = os.path.join(DATA, "hmdb", "hmdb_inchikey_lookup.csv")
HMDB_PARSED = os.path.join(DATA, "parsed", "hmdb_concentrations_parsed.csv")
XML_SOURCES = [os.path.join(DATA, "hmdb", "hmdb_metabolites.xml"),
               os.path.join(DATA, "bmdb", "bmdb_metabolites.xml")]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Shared with the Workbench source. prepare_mwb is loaded first: it imports its
# own select_controls by that name, which must not be ours.
mwb = load("prepare_mwb", os.path.join(ROOT, "pipeline", "mwb", "prepare_mwb.py"))
sel = load("mtbls_select_controls", os.path.join(HERE, "select_controls.py"))

INCHIKEY_RE = mwb.INCHIKEY_RE
FIELDS = mwb.FIELDS
BIOSPECIMEN = mwb.BIOSPECIMEN
NOT_A_UNIT = {"", "unclear", "relative", "-"}
CHECK_MIN_SHARED, CHECK_MAX_LOG10 = mwb.CHECK_MIN_SHARED, mwb.CHECK_MAX_LOG10
VALUE_MAX_LOG10, VALUE_MAX_UMOL = mwb.VALUE_MAX_LOG10, mwb.VALUE_MAX_UMOL

# Studies left out after inspection, with the reason. Each was found by the
# checks below or by comparing well-known metabolites with expected values.
EXCLUDE_STUDIES = {
    "MTBLS13862": "mouse serum amino acids ~10-20x below expected (glycine 36, alanine 18 umol/L) with the "
                  "stated nmol/L; the unit or a dilution factor is likely missing - check the paper",
}

# MAF columns that describe the metabolite, not a sample.
MAF_META = {c.lower() for c in sel.survey_mod.MAF_STANDARD}


# ------------------------------------------------------------------ inputs
def control_studies():
    """{study_id: {"unit": str, "groups": {(group, part)}, "title": str}} for usable control rows."""
    out = {}
    for r in csv.DictReader(open(REVIEW, encoding="utf-8-sig")):
        if r["decision"].strip().lower() != "control":
            continue
        unit = r["unit_confirmed"].strip()
        s = out.setdefault(r["study_id"], {"unit": "", "groups": set(), "title": r["study_title"]})
        s["groups"].add((r["group"], r["organism_part"]))
        s["unit"] = s["unit"] or unit
    return {k: v for k, v in out.items() if v["unit"].lower() not in NOT_A_UNIT}


def mafs(sid):
    return sorted(glob.glob(os.path.join(ISA_DIR, sid, "m_*.tsv")))


def read_maf(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return [], []
    head = [h.strip() for h in rows[0]]
    return head, [dict(zip(head, r)) for r in rows[1:]]


def column_to_sample(sid):
    """MAF column name -> Sample Name. Most MAFs use sample names; some use assay
    names or data file names, which the assay sheet (a_*.txt) maps to samples."""
    m = {}
    for path in glob.glob(os.path.join(ISA_DIR, sid, "a_*.txt")):
        for r in sel.survey_mod.read_table(path):
            smp = (r.get("Sample Name") or "").strip()
            for k, v in r.items():
                if k and smp and v and re.search(r"assay name|data file", k, re.I):
                    m[v.strip()] = smp
    return m


def metabolite_ids(row):
    """The identifying fields of one MAF row."""
    db = (row.get("database_identifier") or "").strip()
    inchi = (row.get("inchi") or "").strip()
    return {
        "name": " ".join((row.get("metabolite_identification") or "").split()),
        "hmdb": mwb.pad_hmdb(db) if db.upper().startswith("HMDB") else "",
        "chebi": db.upper() if db.upper().startswith("CHEBI:") else "",
        "inchi": inchi if inchi.startswith("InChI=") else "",
        "formula": (row.get("chemical_formula") or "").strip(),
    }


def tidy_name(name):
    """MetaboLights names use underscores as spaces ('L_Alanine', 'Indole_lactic acid').
    Turning them into spaces first also stops prepare_mwb.clean_name from reading
    'Indole_' as a code prefix to strip."""
    return mwb.clean_name(" ".join((name or "").replace("_", " ").split()))


def name_key(name):
    """(spelling-tolerant name, stereo prefix) for matching against HMDB.

    Lower-case, letters and digits only, a leading 'x' before a digit dropped
    (R-style column names such as 'x1 methylhistidine'), and a leading L-/D-/DL-
    prefix split off, so 'aspartic acid' and 'L-Aspartic acid' share a key.
    """
    n = (name or "").strip().lower()
    n = re.sub(r"^x(?=\d)", "", n)
    m = re.match(r"^(dl|l|d)[- ](?=[a-z])", n)
    prefix = m.group(1) if m else ""
    n = n[m.end():] if m else n
    return re.sub(r"[^a-z0-9]", "", n), prefix


def entry_key(e):
    """A metabolite's identity across MAFs: its InChI or HMDB ID if given, else its name."""
    return e["inchi"] or e["hmdb"] or e["name"].lower()


# ------------------------------------------------------------------ structure lookups
def inchi_table(wanted):
    """{InChI: InChIKey} for the InChIs we need, from the HMDB/BMDB XML downloads.

    Cached in INCHI_TABLE; the XMLs are only read again for InChIs not yet in it.
    """
    table = {}
    if os.path.exists(INCHI_TABLE):
        table = {r["inchi"]: r["inchikey"] for r in csv.DictReader(open(INCHI_TABLE, encoding="utf-8"))}
    missing = set(wanted) - set(table)
    xmls = [p for p in XML_SOURCES if os.path.exists(p)]
    if missing and xmls:
        for path in xmls:
            ns = "{http://www.%s.ca}" % os.path.basename(path).split("_")[0]
            print(f"  reading InChIs from {os.path.relpath(path, ROOT)} ...")
            for _, el in ET.iterparse(path):
                if el.tag != ns + "metabolite":
                    continue
                inchi = (el.findtext(ns + "inchi") or "").strip()
                if inchi in missing:
                    ik = (el.findtext(ns + "inchikey") or "").strip()
                    if INCHIKEY_RE.match(ik):
                        table[inchi] = ik
                el.clear()
        with open(INCHI_TABLE, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["inchi", "inchikey"])
            w.writerows(sorted(table.items()))
    elif missing:
        print("  no HMDB/BMDB XML in data/hmdb or data/bmdb: InChI table lookup skipped")
    return table


def rdkit_converter():
    try:
        from rdkit import RDLogger
        from rdkit.Chem import inchi as rd_inchi
        RDLogger.DisableLog("rdApp.*")
    except ImportError:
        return None

    def convert(s):
        try:
            ik = rd_inchi.InchiToInchiKey(s)
        except Exception:
            return ""
        return ik if ik and INCHIKEY_RE.match(ik) else ""
    return convert


def pubchem_lookup(queries, workers=4):
    """{query: {"inchikey", "formula"}} from PubChem, cached. A query is ('inchi', s) or ('name', s)."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    cache = json.load(open(PUBCHEM_CACHE)) if os.path.exists(PUBCHEM_CACHE) else {}
    base = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
    s = requests.Session()
    s.headers["User-Agent"] = "metabolite-concentration-atlas (university research project)"

    def job(q):
        kind, text = q
        key = kind + ":" + text
        if key in cache:
            return
        for attempt in range(3):
            try:
                if kind == "inchi":
                    r = s.post(f"{base}/inchi/property/InChIKey,MolecularFormula/JSON",
                               data={"inchi": text}, timeout=60)
                else:
                    r = s.get(f"{base}/name/{quote(text, safe='')}/property/InChIKey,MolecularFormula/JSON",
                              timeout=60)
                if r.status_code == 200:
                    p = r.json()["PropertyTable"]["Properties"][0]
                    cache[key] = {"inchikey": p.get("InChIKey", ""), "formula": p.get("MolecularFormula", "")}
                    return
                if r.status_code in (400, 404):
                    cache[key] = {}
                    return
            except Exception:
                pass
            time.sleep(2 ** attempt)

    todo = [q for q in queries if q[0] + ":" + q[1] not in cache]
    if todo:
        # one quick probe first, so an unreachable PubChem costs seconds, not minutes of retries
        try:
            s.get(f"{base}/name/glucose/property/InChIKey/JSON", timeout=15).raise_for_status()
        except Exception as e:
            print(f"  PubChem not reachable ({type(e).__name__}): skipped. Re-run with internet access, or use --offline.")
            return cache
        print(f"  asking PubChem about {len(todo)} structures/names (cached in {os.path.relpath(PUBCHEM_CACHE, ROOT)}) ...")
        with ThreadPoolExecutor(max_workers=workers) as ex:     # PubChem allows ~5 requests/s
            list(ex.map(job, todo))
        with open(PUBCHEM_CACHE, "w") as f:
            json.dump(cache, f)
    return {k: v for k, v in cache.items()}


# ------------------------------------------------------------------ step 1: names
def names_step(offline):
    studies = control_studies()
    if not studies:
        sys.exit("No control groups with a confirmed unit in the review file yet.")
    entries = {}
    for sid in sorted(studies, key=lambda s: int(s[5:])):
        for path in mafs(sid):
            _, rows = read_maf(path)
            for row in rows:
                e = metabolite_ids(row)
                if not (e["name"] or e["inchi"] or e["hmdb"]):
                    continue
                k = entry_key(e)
                cur = entries.setdefault(k, dict(e, studies=set(), names=[]))
                for f in ("name", "hmdb", "chebi", "inchi", "formula"):
                    cur[f] = cur[f] or e[f]
                cur["studies"].add(sid)
                # the same structure can be named differently in different studies
                # ("linolenic acid", "Alpha-Linolenic acid"); every name is tried below,
                # so the result does not depend on which study is read first
                if e["name"] and e["name"] not in cur["names"]:
                    cur["names"].append(e["name"])

    look = list(csv.DictReader(open(HMDB_LOOKUP, encoding="utf-8")))
    hmdb_ik = {r["hmdb_id"]: r["inchikey"] for r in look if r["inchikey"]}
    ik_hmdb = {v: k for k, v in hmdb_ik.items()}
    by_name, by_key = {}, {}
    for r in look:
        if r["inchikey"]:
            hit = (r["hmdb_id"], r["inchikey"], r["metabolite_name"])
            by_name.setdefault(r["metabolite_name"].strip().lower(), hit)
            k, prefix = name_key(r["metabolite_name"])
            if k:
                by_key.setdefault(k, {}).setdefault(prefix, hit)

    table = inchi_table({e["inchi"] for e in entries.values() if e["inchi"]})
    rdkit = rdkit_converter()
    if not rdkit:
        print("  RDKit not installed: InChIs not in the HMDB/BMDB table stay unconverted (pip install rdkit)")

    out = []
    for k, e in entries.items():
        names = sorted(e["names"], key=str.lower) or [e["name"]]
        r = {"key": k, "name": e["name"], "clean_name": tidy_name(e["name"]),
             "other_names": " | ".join(n for n in names if n != e["name"]),
             "chebi": e["chebi"], "inchi": e["inchi"], "formula": e["formula"],
             "inchikey": "", "hmdb_id": "", "matched_name": "", "method": "",
             "studies": " ".join(sorted(e["studies"], key=lambda s: int(s[5:])))}
        if e["hmdb"] and e["hmdb"] in hmdb_ik:
            r.update(inchikey=hmdb_ik[e["hmdb"]], hmdb_id=e["hmdb"], method="maf_hmdb_id")
        elif e["inchi"] and e["inchi"] in table:
            r.update(inchikey=table[e["inchi"]], method="inchi_table")
        elif e["inchi"] and rdkit and rdkit(e["inchi"]):
            r.update(inchikey=rdkit(e["inchi"]), method="inchi_rdkit")
        else:
            cleaned = [tidy_name(n) for n in names]
            hit = next((by_name[c.lower()] for c in cleaned if c.lower() in by_name), None)
            loose = None
            for c in ([] if hit else cleaned):
                if not c.isascii():                        # garbled names ('¦Â-alanine') are not guessed at
                    continue
                key, prefix = name_key(c)
                forms = by_key.get(key, {}) if len(key) >= 4 else {}
                # an explicit L-/D- must match; with none, prefer the L- form (the one in blood)
                loose = forms.get(prefix) if prefix else (forms.get("l") or forms.get("") or forms.get("d"))
                if loose:
                    break
            if hit:
                r.update(hmdb_id=hit[0], inchikey=hit[1], matched_name=hit[2], method="hmdb_name")
            elif loose:
                r.update(hmdb_id=loose[0], inchikey=loose[1], matched_name=loose[2], method="hmdb_name_loose")
        out.append(r)

    if not offline:
        queries = [("inchi", r["inchi"]) for r in out if not r["inchikey"] and r["inchi"]]
        queries += [("name", r["clean_name"]) for r in out if not r["inchikey"] and r["clean_name"]
                    and r["clean_name"].isascii()]
        try:
            cache = pubchem_lookup(sorted(set(queries)))
        except ImportError:
            print("  requests not installed: PubChem skipped (pip install requests)")
            cache = {}
        for r in out:
            for kind, text in (("inchi", r["inchi"]), ("name", r["clean_name"])):
                hit = cache.get(kind + ":" + text) or {}
                if not r["inchikey"] and text and INCHIKEY_RE.match(hit.get("inchikey", "")):
                    r.update(inchikey=hit["inchikey"], method="pubchem_" + kind)
                    r["formula"] = r["formula"] or hit.get("formula", "")
    else:
        print("--offline: PubChem not asked; structures without a local match stay unresolved")

    for r in out:
        if r["inchikey"] and not r["hmdb_id"]:
            r["hmdb_id"] = ik_hmdb.get(r["inchikey"], "")
    out.sort(key=lambda r: (r["studies"], r["name"].lower()))
    with open(NAME_MAP, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    c = Counter(r["method"] or "unresolved" for r in out)
    print(f"\n{len(out)} distinct metabolites in {len(studies)} studies")
    for k, v in c.most_common():
        print(f"  {k:16s} {v:6d}")
    print(f"Wrote {os.path.relpath(NAME_MAP, ROOT)}")


# ------------------------------------------------------------------ step 2: build
def unit_check(rows):
    """Leave out studies and single values that cannot be right (see the docstring)."""
    study = lambda r: r["reference_texts"].split()[1].rstrip(":")
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
        print("HMDB comparison skipped: run 1_parse_concentrations.py --source HMDB first")

    per = defaultdict(list)
    for r in rows:
        k = (r["inchikey"], r["biospecimen"])
        if k in ref:
            per[study(r)].append(math.log10(mean(r) / ref[k]))
    dropped, report = {}, []
    for st in sorted({study(r) for r in rows}, key=lambda s: int(s[5:])):
        l = sorted(per.get(st, []))
        med = l[len(l) // 2] if l else None
        if st in EXCLUDE_STUDIES:
            dropped[st] = "left out: " + EXCLUDE_STUDIES[st]
        elif len(l) >= CHECK_MIN_SHARED and abs(med) > CHECK_MAX_LOG10:
            dropped[st] = "left out: likely unit error"
        report.append({"study_id": st, "species": next(r["species_common"] for r in rows if study(r) == st),
                       "metabolites": sum(1 for r in rows if study(r) == st),
                       "shared_with_hmdb": len(l),
                       "median_log10_ratio": "" if med is None else "%.2f" % med,
                       "typical_fold_vs_hmdb": "" if med is None else "%.3g" % 10 ** med,
                       "result": dropped.get(st) or ("ok" if len(l) >= CHECK_MIN_SHARED else "too few shared to check")})
    with open(CHECK, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0].keys()))
        w.writeheader()
        w.writerows(report)

    kept, bad = [], []
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
            bad.append({"study_id": study(r), "metabolite_name": r["metabolite_name"],
                        "species": r["species_common"], "biospecimen": r["biospecimen"],
                        "mean_umol_per_L": "%.4g" % v, "reason": why})
        else:
            kept.append(r)
    with open(VALUE_CHECK, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["study_id", "metabolite_name", "species", "biospecimen",
                                          "mean_umol_per_L", "reason"])
        w.writeheader()
        w.writerows(bad)
    print("Checks: %d studies left out%s; %d single values left out (see %s)"
          % (len(dropped), (" (" + ", ".join(sorted(dropped)) + ")") if dropped else "",
             len(bad), os.path.relpath(VALUE_CHECK, ROOT)))
    for r in report:
        print(f"  {r['study_id']:11s} {r['species']:8s} {r['metabolites']:4d} metabolites, "
              f"{r['shared_with_hmdb']:3d} shared with HMDB, typical {r['typical_fold_vs_hmdb'] or '-':>6s}x  {r['result']}")
    return kept


def species_of(organism):
    sci = re.split(r"[;:]", organism or "")[0].strip()
    sci = {"Sus scrofa domesticus": "Sus scrofa"}.get(sci, sci)
    return sci, mwb.COMMON.get(sci, sci), mwb.TAXON.get(sci, "")


def build_step():
    if not os.path.exists(NAME_MAP):
        sys.exit("Run `names` first.")
    nmap = {r["key"]: r for r in csv.DictReader(open(NAME_MAP, encoding="utf-8"))}
    studies = control_studies()
    stats = Counter()
    best = {}   # (study, species, biospecimen, inchikey) -> candidate with most samples

    for sid in sorted(studies, key=lambda s: int(s[5:])):
        st = studies[sid]
        uf = mwb.unit_factor(st["unit"])
        if not uf:
            print(f"  {sid}: unit '{st['unit']}' is not convertible - skipped")
            stats["studies skipped: unit not convertible"] += 1
            continue
        # control samples -> (biospecimen, species)
        ctl = {}
        for smp in sel.samples(sid):
            if (smp["group"], smp["part"]) in st["groups"] and sel.is_mammal(smp["organism"]):
                b = sel.bucket(smp["part"])
                if b in BIOSPECIMEN:
                    ctl[smp["sample"]] = (BIOSPECIMEN[b], species_of(smp["organism"]))
        if not ctl:
            print(f"  {sid}: no control samples found in the sample sheet - skipped")
            stats["studies skipped: no control samples"] += 1
            continue
        col2smp = column_to_sample(sid)

        for path in mafs(sid):
            head, rows = read_maf(path)
            cols = {}
            for c in head:
                if c.lower() in MAF_META:
                    continue
                smp = c if c in ctl else col2smp.get(c)
                if smp in ctl:
                    cols[c] = smp
            if not cols:
                stats["MAFs with no control columns"] += 1
                continue
            for row in rows:
                e = metabolite_ids(row)
                m = nmap.get(entry_key(e))
                if not m or not m["inchikey"]:
                    stats["rows left out: no structure"] += 1
                    continue
                if uf[0] == "mass":
                    mw = mwb.molar_mass(e["formula"] or m["formula"])
                    if not mw:
                        stats["rows left out: mass unit, formula unknown"] += 1
                        continue
                    factor = uf[1] / mw * 1e6
                else:
                    factor = uf[1]
                vals = defaultdict(list)
                for c, smp in cols.items():
                    try:
                        v = float(str(row.get(c, "")).strip())
                    except ValueError:
                        continue
                    if v > 0 and math.isfinite(v):
                        bio, sp = ctl[smp]
                        vals[(bio, sp)].append(v * factor)
                for (bio, sp), vs in vals.items():
                    k = (sid, sp[0], bio, m["inchikey"])
                    if k not in best or len(vs) > len(best[k]["values"]):
                        best[k] = {"values": vs, "maf": os.path.basename(path), "map": m, "sp": sp,
                                   "name": e["name"]}
        stats["studies used"] += 1

    out = []
    for (sid, _, bio, ik), c in sorted(best.items(), key=lambda kv: (int(kv[0][0][5:]),) + kv[0][1:]):
        vs, n = c["values"], len(c["values"])
        mean = sum(vs) / n
        if n >= 2:
            sd = math.sqrt(sum((v - mean) ** 2 for v in vs) / (n - 1))
            raw = f"{mwb.fmt(mean)} +/- {mwb.fmt(sd)} ({mwb.fmt(min(vs))} - {mwb.fmt(max(vs))})"
        else:
            raw = mwb.fmt(mean)
        m, (sci, common, taxon) = c["map"], c["sp"]
        out.append({
            "hmdb_id": m["hmdb_id"], "metabolite_name": m["matched_name"] or m["clean_name"] or c["name"],
            "biospecimen": bio, "concentration_value_raw": raw, "concentration_units": "umol/L",
            "subject_age": "", "subject_sex": "",
            "subject_condition": f"Control group, {n} sample{'s' if n != 1 else ''}",
            "pubmed_ids": "",
            "reference_texts": f"MetaboLights {sid}: {studies[sid]['title']}",
            "native_id": ik, "inchikey": ik,
            "species_scientific": sci, "species_common": common, "ncbi_taxon_id": taxon,
        })
    if not out:
        sys.exit("Nothing to write: no control values could be extracted.")

    out = unit_check(out)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print()
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"\n{len(out)} rows from {len({r['reference_texts'].split()[1] for r in out})} studies "
          f"({dict(Counter(r['species_common'] for r in out))}; {dict(Counter(r['biospecimen'] for r in out))})")
    print(f"Wrote {os.path.relpath(OUT, ROOT)}")
    print("Next: python pipeline/1_parse_concentrations.py --source MTBLS")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["names", "build"])
    p.add_argument("--offline", action="store_true", help="names: no PubChem lookups")
    a = p.parse_args()
    if a.step == "names":
        names_step(a.offline)
    else:
        build_step()
