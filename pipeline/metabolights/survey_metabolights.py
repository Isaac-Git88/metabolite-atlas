"""
survey_metabolights.py
Step 1 of the MetaboLights (MTBLS) source: find out how much of the repository
reports real concentrations before building an extractor for it -- the same
first step the Metabolomics Workbench source took (pipeline/mwb/survey_mwb.py).

Why MetaboLights needs a survey
-------------------------------
MetaboLights (EMBL-EBI) stores each study as ISA-Tab:
    i_Investigation.txt   title, description, design types, protocols
    s_<study>.txt         sample sheet: organism, organism part, factor values
    a_<assay>.txt         assay sheet: technology, which samples were run
    m_<...>_maf.tsv       metabolite assignment file (MAF): one row per
                          metabolite, one column per sample
Unlike Metabolomics Workbench, the MAF has no units field. Most studies are
untargeted and their MAF values are peak areas; the few that report
concentrations usually say so only in the description or protocols
("concentrations in µM", "absolute quantification"). So this survey reads the
small metadata files of every public study and screens their text for
concentration evidence. It is a screen for human review, not a decision.

Two steps
---------
  1. fetch  - list public studies, then for each study download the
              investigation, sample and assay files (small) into
              data/metabolights/isa/<MTBLS id>/ and record its MAF file names.
              MAFs are only downloaded with --maf, and then only for studies the
              screen marks likely/possible (run `survey` first). Resumable:
              progress is logged to data/metabolights/status.jsonl.
  2. survey - read every saved study and write
                data/metabolights/mtbls_study_survey.csv  one row per study
                data/metabolights/mtbls_organisms.csv     studies per organism
              and print a summary.

Usage
-----
    pip install requests
    python pipeline/metabolights/survey_metabolights.py check                 # can we reach MetaboLights?
    python pipeline/metabolights/survey_metabolights.py fetch --limit 20      # trial
    python pipeline/metabolights/survey_metabolights.py fetch --workers 4     # all public studies
    python pipeline/metabolights/survey_metabolights.py survey
    python pipeline/metabolights/survey_metabolights.py fetch --maf           # MAFs of likely/possible studies
    python pipeline/metabolights/survey_metabolights.py survey                # again, now with MAF sizes

Notes
-----
  - Written without access to MetaboLights from the build environment, so it has
    not been run against the live service. `check` and a `--limit 20` trial show
    quickly whether the endpoints below still behave as expected.
  - Keep --workers low (2-4): this is a shared public server.
  - Study list: the REST web service, falling back to the public FTP folder
    listing (served over HTTPS) if the web service fails.
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

csv.field_size_limit(sys.maxsize)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "metabolights")
ISA_DIR = os.path.join(DATA, "isa")
STATUS_FILE = os.path.join(DATA, "status.jsonl")
STUDIES_FILE = os.path.join(DATA, "studies.json")
SURVEY_FILE = os.path.join(DATA, "mtbls_study_survey.csv")

WS = "https://www.ebi.ac.uk/metabolights/ws"
FTP = "https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public"

STUDY_ID = re.compile(r"^MTBLS\d+$")


# ------------------------------------------------------------------ http helpers
def session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = "metabolite-concentration-atlas (university research project)"
    return s


def get(s, url, tries=5, stream=False):
    """GET with retries. Returns the response on 200, None on 404."""
    for attempt in range(tries):
        try:
            r = s.get(url, timeout=120, stream=stream)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(min(60, 2 ** attempt))
    raise RuntimeError("failed after retries: " + url)


def list_folder(s, url):
    """File names in an FTP-over-HTTPS folder listing (an Apache-style index page)."""
    r = get(s, url.rstrip("/") + "/")
    if r is None:
        return None
    names = re.findall(r'href="([^"?/][^"]*)"', r.text)
    return [n for n in names if not n.startswith(("http", "#", "../"))]


# ------------------------------------------------------------------ step 0: check
def check():
    s = session()
    ok = True
    for label, url in [("web service study list", WS + "/studies"),
                       ("FTP public folder", FTP + "/"),
                       ("FTP folder of MTBLS1", FTP + "/MTBLS1/")]:
        try:
            r = get(s, url, tries=2)
            print(f"  {'OK ' if r is not None else '404'}  {label}: {url}")
            if r is not None and label.startswith("FTP folder"):
                print("       files:", ", ".join(list_folder(s, url)[:12]))
        except Exception as e:
            ok = False
            print(f"  FAIL {label}: {url}\n       {e}")
    sys.exit(0 if ok else 1)


# ------------------------------------------------------------------ step 1: fetch
def study_ids(s):
    """Public study accessions: from the web service, else from the FTP listing."""
    try:
        r = get(s, WS + "/studies", tries=3)
        body = r.json() if r is not None else {}
        ids = body.get("content") if isinstance(body, dict) else body
        ids = sorted({i for i in (ids or []) if isinstance(i, str) and STUDY_ID.match(i)},
                     key=lambda i: int(i[5:]))
        if ids:
            print(f"{len(ids)} public studies listed by the web service")
            return ids
    except Exception as e:
        print("web service listing failed:", e)
    names = [n.rstrip("/") for n in (list_folder(s, FTP) or [])]
    ids = sorted({n for n in names if STUDY_ID.match(n)}, key=lambda i: int(i[5:]))
    print(f"{len(ids)} public studies listed in the FTP folder")
    return ids


def done_ids(kind):
    done = set()
    if os.path.exists(STATUS_FILE):
        for line in open(STATUS_FILE):
            r = json.loads(line)
            if r.get("kind", "isa") == kind and r["s"] in ("ok", "empty"):
                done.add(r["id"])
    return done


def fetch_isa(s, sid):
    """Download one study's investigation, sample and assay files and its file list."""
    names = list_folder(s, f"{FTP}/{sid}")
    if names is None:
        return "empty"
    folder = os.path.join(ISA_DIR, sid)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "files.json"), "w") as f:
        json.dump(names, f)
    for n in names:
        if re.match(r"^[isa]_.*\.txt$", n):
            r = get(s, f"{FTP}/{sid}/{n}")
            if r is not None:
                with open(os.path.join(folder, n), "wb") as f:
                    f.write(r.content)
    return "ok"


def fetch_mafs(s, sid):
    folder = os.path.join(ISA_DIR, sid)
    names = json.load(open(os.path.join(folder, "files.json")))
    got = 0
    for n in names:
        if is_maf(n) and not os.path.exists(os.path.join(folder, n)):
            r = get(s, f"{FTP}/{sid}/{n}", stream=True)
            if r is not None:
                with open(os.path.join(folder, n), "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                got += 1
    return "ok" if got or any(is_maf(n) for n in names) else "empty"


def fetch(workers, limit, maf, ids_arg):
    os.makedirs(ISA_DIR, exist_ok=True)
    s = session()

    if maf:
        if not os.path.exists(SURVEY_FILE):
            sys.exit("Run `survey` first: --maf downloads MAFs only for studies it marks likely/possible.")
        with open(SURVEY_FILE, newline="", encoding="utf-8") as f:
            ids = [r["study_id"] for r in csv.DictReader(f)
                   if r.get("text_screen", r["concentration_screen"]) in ("likely", "possible")
                   and r["n_maf"] != "0"]
        kind, job_fn = "maf", fetch_mafs
        print(f"{len(ids)} likely/possible studies with a MAF")
    else:
        ids = ids_arg or study_ids(s)
        with open(STUDIES_FILE, "w") as f:
            json.dump(ids, f)
        kind, job_fn = "isa", fetch_isa

    done = done_ids(kind)
    todo = [i for i in ids if i not in done]
    if limit:
        todo = todo[:limit]
    print(f"{len(done)} already done, {len(todo)} to fetch")

    lock, n = threading.Lock(), {"i": 0}
    log = open(STATUS_FILE, "a")

    def job(sid):
        try:
            status = job_fn(s, sid)
        except Exception:
            status = "fail"
        with lock:
            log.write(json.dumps({"id": sid, "kind": kind, "s": status, "t": time.time()}) + "\n")
            log.flush()
            n["i"] += 1
            if n["i"] % 25 == 0 or n["i"] == len(todo):
                print(f"  {n['i']}/{len(todo)}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(job, todo))
    log.close()
    fails = sum(1 for line in open(STATUS_FILE)
                if json.loads(line).get("kind", "isa") == kind and json.loads(line)["s"] == "fail")
    if fails:
        print(f"{fails} failed attempts logged; re-run fetch to retry them.")


# ------------------------------------------------------------------ ISA-Tab reading
def is_maf(name):
    return name.startswith("m_") and name.endswith(".tsv")


def read_investigation(path):
    """i_Investigation.txt -> {key: [values]}. Keys repeat across sections; values are pooled."""
    out = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f, delimiter="\t"):
            if not row or row[0].isupper() and len(row) == 1:
                continue
            vals = [v.strip() for v in row[1:] if v.strip()]
            if vals:
                out.setdefault(row[0].strip(), []).extend(vals)
    return out


def inv(d, key):
    return " | ".join(d.get(key, []))


def read_table(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def column(rows, pattern):
    """Values of the first column whose header matches pattern (case-insensitive)."""
    if not rows:
        return []
    for k in rows[0].keys():
        if k and re.fullmatch(pattern, k.strip(), re.I):
            return [(r.get(k) or "").strip() for r in rows]
    return []


# ------------------------------------------------------------------ concentration screen
# words that suggest a healthy / untreated group (same list as the MWB survey)
CONTROL_WORDS = re.compile(
    r"\b(control|ctrl|healthy|baseline|vehicle|sham|wild[- ]?type|wt|normal|untreated|placebo)\b", re.I)

# A concentration unit, as it appears in prose. Molar short forms are matched
# case-sensitively: "mM" is millimolar, but "mm", "nm" and "µm" are lengths
# (column size, wavelength, particle size) and must not count.
UNIT = re.compile(
    r"(?<![\w/])("
    r"[pnuµμm]M"
    r"|(?i:[pnuµμm]mol\s*/\s*(?:l|ml|dl))"
    r"|(?i:[pnuµμm]?g\s*/\s*(?:l|ml|dl))"
    r"|(?i:micromolar|millimolar|nanomolar)"
    r")(?![\w])")
# Most unit mentions in a methods section are not results: they describe
# reagents ("10 mM ammonium formate"), internal standards ("50 nM
# acetaminophen"), or what the samples were treated with ("5 uM atorvastatin").
# A mention is skipped if any of these words is within 50 characters of it.
REAGENT = re.compile(
    r"formate|acetate|buffer|phosphate|nacl|kcl|hcl|naoh|edta|tris|hepes|bicarbonate|ammonium|ammonia|"
    r"nh4|mgcl|pbs\b|dtt\b|urea|teab|tcep|pyridine|methoxyamine|"
    r"solution|standard|internal|lock\s*mass|spik|stock|reagent|methanol|acetonitrile|isopropanol|"
    r"chloroform|water|medium|media|mobile\s+phase|eluent|solvent|"
    r"dissolved|diluted|reconstitut|derivati|calibrat|d2o|tsp\b|dss\b|"
    r"treated|treatment|incubat|stimulat|exposed|exposure|supplement|administ|dose|dosed|inject|"
    r"final\s+concentration|grains|inocul|culture",
    re.I)
# Wording that says a number is a result: "concentrations were calculated in
# mM", "presented as uM", "expressed in umol/L", "absolute quantification".
RESULT = re.compile(
    r"express\w*|report\w*|present\w*|calculat\w*|given\s+in|quantified|quantitated|"
    r"absolute|per\s+lit(re|er)|normal\s+range|reference\s+(range|interval)",
    re.I)
TARGETED_DESIGN = re.compile(r"(?<!un)(?<!non-)(?<!non )targeted", re.I)
UNTARGETED = re.compile(r"untargeted|non-?targeted|relative\s+quantif\w*|semi-?quantitative|"
                        r"peak\s+(area|intensit)|fold[- ]change", re.I)
QUANT = re.compile(r"absolute(ly)?\s+quantif\w*|quantitative\s+(analysis|profiling|nmr|metabolomics)|"
                   r"concentrations?\s+of\s+\d+\s+metabolites|calibration\s+curve|standard\s+curve|"
                   r"quantified\s+(using|with|by|against)", re.I)


def unit_mentions(text):
    """(unit, kind) for each concentration unit in the text.

    kind is 'result' if the unit sits next to result wording, 'other' if not;
    mentions next to a reagent or treatment word are dropped.
    """
    out = []
    for m in UNIT.finditer(text):
        near = text[max(0, m.start() - 50): m.end() + 50]
        if REAGENT.search(near):
            continue
        wide = text[max(0, m.start() - 90): m.end() + 40]
        out.append((m.group(1), "result" if RESULT.search(wide) else "other"))
    return out


def screen(text, design):
    """likely / possible / unlikely from the study text, and the evidence.

    likely   - a concentration unit stated as a result ("calculated in mM");
    possible - a targeted design with quantification wording (calibration,
               absolute quantification), or a non-reagent unit in a study that
               does not call itself untargeted;
    unlikely - otherwise. A study that calls itself untargeted (or relative,
               or reports peak areas) needs result-unit evidence to pass.
    """
    units = unit_mentions(text)
    result_units = [u for u, k in units if k == "result"]
    targeted = bool(TARGETED_DESIGN.search(design))
    untargeted = bool(UNTARGETED.search(design) or UNTARGETED.search(text))
    quant = bool(QUANT.search(text))
    if result_units:
        verdict = "likely"
    elif (targeted and quant) or (units and not untargeted):
        verdict = "possible"
    else:
        verdict = "unlikely"
    return verdict, [u for u, _ in units], result_units, quant, targeted, untargeted


# MAF columns that describe the metabolite, not a sample.
MAF_STANDARD = {
    "database_identifier", "chemical_formula", "smiles", "inchi", "metabolite_identification",
    "mass_to_charge", "fragmentation", "modifications", "charge", "retention_time", "taxid",
    "species", "database", "database_version", "reliability", "uri", "search_engine",
    "search_engine_score", "smallmolecule_abundance_sub", "smallmolecule_abundance_stdev_sub",
    "smallmolecule_abundance_std_error_sub", "chemical_shift", "multiplicity",
    "kegg_database_identifier", "assigned_chebi_identifier", "assigned_refmet_identifier",
    "chebi_identifier_search_status", "chebi_identifier_search_time",
}
# Median sample value above which a MAF almost certainly holds peak areas or
# intensities: concentrations in uM rarely have a median this high.
RELATIVE_MEDIAN = 10_000


def maf_values(path):
    """(metabolite rows, named rows, median of positive sample values) for one MAF."""
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return 0, 0, None
    head, body = rows[0], rows[1:]
    sample_cols = [i for i, c in enumerate(head) if c.strip().lower() not in MAF_STANDARD]
    named_col = head.index("metabolite_identification") if "metabolite_identification" in head else None
    vals = []
    for r in body:
        for i in sample_cols:
            if i < len(r):
                try:
                    v = float(r[i])
                except ValueError:
                    continue
                if v > 0:
                    vals.append(v)
    named = sum(1 for r in body if named_col is not None and named_col < len(r) and r[named_col].strip())
    vals.sort()
    return len(body), named, (vals[len(vals) // 2] if vals else None)


# ------------------------------------------------------------------ step 2: survey
def survey_study(sid):
    folder = os.path.join(ISA_DIR, sid)
    files = json.load(open(os.path.join(folder, "files.json")))
    r = {"study_id": sid}

    inv_path = next((os.path.join(folder, n) for n in files if n.startswith("i_") and
                     os.path.exists(os.path.join(folder, n))), None)
    d = read_investigation(inv_path) if inv_path else {}
    design = inv(d, "Study Design Type")
    r.update({
        "title": inv(d, "Study Title")[:300],
        "release_date": inv(d, "Study Public Release Date"),
        "design_types": design[:300],
        "technology": inv(d, "Study Assay Technology Type"),
        "measurement": inv(d, "Study Assay Measurement Type"),
    })

    samples = []
    for n in files:
        if n.startswith("s_") and os.path.exists(os.path.join(folder, n)):
            samples += read_table(os.path.join(folder, n))
    organisms = Counter(v for v in column(samples, r"Characteristics\s*\[\s*Organism\s*\]") if v)
    parts = Counter(v for v in column(samples, r"Characteristics\s*\[\s*Organism part\s*\]") if v)
    factor_cols = [k for k in (samples[0].keys() if samples else []) if k and k.startswith("Factor Value")]
    groups = Counter(" | ".join(f"{k[13:-1]}:{(s.get(k) or '').strip()}" for k in factor_cols)
                     for s in samples) if factor_cols else Counter()

    text = " ".join([inv(d, "Study Title"), inv(d, "Study Description"),
                     inv(d, "Study Protocol Description"), design])
    verdict, units, result_units, quant, targeted, untargeted = screen(text, design)

    mafs = [n for n in files if is_maf(n)]
    maf_rows = maf_named = 0
    medians = []
    for n in mafs:
        p = os.path.join(folder, n)
        if os.path.exists(p):
            nr, nn, med = maf_values(p)
            maf_rows += nr
            maf_named += nn
            if med is not None:
                medians.append(med)
    maf_median = sorted(medians)[len(medians) // 2] if medians else None
    # The values overrule the text: a MAF of peak areas is not a concentration
    # study, whatever its methods mention.
    maf_on_disk = any(os.path.exists(os.path.join(folder, n)) for n in mafs)
    if maf_median is not None and maf_median > RELATIVE_MEDIAN:
        maf_check = "relative"
    elif maf_median is not None:
        maf_check = "could_be_concentration"
    elif maf_on_disk:
        # Downloaded, but no sample column holds a number: the values were
        # never deposited (often they are only in the paper), so there is
        # nothing to extract from MetaboLights.
        maf_check = "empty"
    else:
        maf_check = "not_checked"
    if maf_check == "relative":
        final = "unlikely"
    elif maf_check == "empty" and verdict != "unlikely":
        final = "no_values"
    else:
        final = verdict

    r.update({
        "organism": "; ".join(o for o, _ in organisms.most_common(4)),
        "organism_part": "; ".join(o for o, _ in parts.most_common(4)),
        "n_samples": len(samples),
        "n_groups": len(groups),
        "has_control_group": int(any(CONTROL_WORDS.search(g) for g in groups)),
        "groups": " || ".join(f"{g} (n={k})" for g, k in groups.most_common(6))[:600],
        "concentration_screen": final,
        "text_screen": verdict,
        "maf_check": maf_check,
        "maf_median_value": "" if maf_median is None else f"{maf_median:.4g}",
        "result_units": "; ".join(f"{u} ({k})" for u, k in Counter(result_units).most_common(5)),
        "units_in_text": "; ".join(f"{u} ({k})" for u, k in Counter(units).most_common(5)),
        "mentions_quantification": int(quant),
        "targeted": int(targeted),
        "untargeted": int(untargeted),
        "n_maf": len(mafs),
        "maf_downloaded": int(any(os.path.exists(os.path.join(folder, n)) for n in mafs)),
        "maf_metabolite_rows": maf_rows,
        "maf_named_rows": maf_named,
        "has_investigation": int(bool(d)),
    })
    return r


def survey():
    if not os.path.isdir(ISA_DIR):
        sys.exit("Nothing fetched yet - run `fetch` first.")
    sids = sorted((n for n in os.listdir(ISA_DIR)
                   if STUDY_ID.match(n) and os.path.exists(os.path.join(ISA_DIR, n, "files.json"))),
                  key=lambda i: int(i[5:]))
    out, bad = [], 0
    for sid in sids:
        try:
            out.append(survey_study(sid))
        except Exception as e:
            bad += 1
            print("  could not read", sid, "-", e)

    fields = ["study_id", "title", "release_date", "organism", "organism_part", "technology",
              "measurement", "design_types", "concentration_screen", "text_screen", "maf_check",
              "maf_median_value", "result_units", "units_in_text", "mentions_quantification",
              "targeted", "untargeted", "n_samples", "n_groups", "has_control_group",
              "groups", "n_maf", "maf_downloaded", "maf_metabolite_rows", "maf_named_rows",
              "has_investigation"]
    with open(SURVEY_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(out)

    orgs = Counter()
    for r in out:
        for o in (r["organism"] or "(blank)").split("; "):
            orgs[(o, r["concentration_screen"])] += 1
    with open(os.path.join(DATA, "mtbls_organisms.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["organism", "concentration_screen", "n_studies"])
        for (o, v), k in sorted(orgs.items(), key=lambda x: -x[1]):
            w.writerow([o, v, k])

    n = len(out)
    print(f"\n{n} studies surveyed ({bad} unreadable)\n")
    print("Concentration screen:")
    for v in ("likely", "possible", "no_values", "unlikely"):
        k = sum(r["concentration_screen"] == v for r in out)
        print(f"  {v:9s} {k:6d}  ({100 * k / max(n, 1):.1f}%)")
    cand = [r for r in out if r["concentration_screen"] in ("likely", "possible")]
    if any(r["concentration_screen"] == "no_values" for r in out):
        print("  (no_values: the text suggests concentrations, but the MAF holds no numbers)")
    print(f"\nLikely/possible studies by organism (top 12):")
    for o, k in Counter(r["organism"] or "(blank)" for r in cand).most_common(12):
        print(f"  {k:5d}  {o}")
    print(f"\nLikely/possible by organism part (top 12):")
    for o, k in Counter((r["organism_part"] or "(blank)").lower() for r in cand).most_common(12):
        print(f"  {k:5d}  {o}")
    print(f"\n  {sum(r['has_control_group'] for r in cand)} of {len(cand)} have a group named like a control")
    print(f"\nWrote {os.path.relpath(SURVEY_FILE, ROOT)} and data/metabolights/mtbls_organisms.csv")


# ------------------------------------------------------------------ main
if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["check", "fetch", "survey", "all"])
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0, help="fetch at most this many studies (trial run)")
    p.add_argument("--maf", action="store_true",
                   help="download the MAFs of studies the survey marks likely/possible")
    p.add_argument("--ids", help="comma-separated study IDs to fetch, e.g. MTBLS1,MTBLS2")
    a = p.parse_args()
    os.makedirs(DATA, exist_ok=True)
    if a.step == "check":
        check()
    if a.step in ("fetch", "all"):
        fetch(a.workers, a.limit, a.maf, a.ids.split(",") if a.ids else None)
    if a.step in ("survey", "all"):
        survey()
