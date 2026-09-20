"""
extract_ymdb_concentrations.py
Open every YMDB metabolite link and extract all concentration values into one CSV.

Two steps:
  1. fetch   - download each metabolite's XML page (https://www.ymdb.ca/compounds/YMDBxxxxx.xml)
               into data/ymdb/xml/ as .xml.gz. Resumable: already-downloaded IDs are skipped, so you can
               stop and restart at any time. Progress is logged to status.jsonl.
  2. extract - read every saved XML and write one row per concentration measurement
               to data/ymdb/ymdb_concentrations_all.csv.

Usage:
    pip install requests
    python pipeline/ymdb/extract_ymdb_concentrations.py fetch --workers 8
    python pipeline/ymdb/extract_ymdb_concentrations.py extract
    python pipeline/ymdb/extract_ymdb_concentrations.py all      # fetch then extract
  data/ymdb/xml/ and data/ymdb/status.jsonl are working files (~70 MB); they are gitignored.

Notes:
  - The YMDB server is slow (often 10-60 s per page) and returns 502 errors when busy.
    The script retries with growing waits. Around 8-16 workers worked well; more just caused
    more 502s. The full run of 16,500 IDs took roughly 10 hours.
  - In the XML, a metabolite's <concentrations> block holds several measurements as flat,
    repeated sibling tags (growth_media, concentration, units, error, strain, reference, ...),
    with no wrapper per measurement. Each new <growth_media> tag starts a new measurement.
    (Reading it with a simple find() would keep only the first measurement.)
"""
import argparse
import csv
import gzip
import html
import json
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "ymdb")
XML_DIR = os.path.join(DATA, "xml")
STATUS_FILE = os.path.join(DATA, "status.jsonl")
URL = "https://www.ymdb.ca/compounds/{}.xml"


# ---------------------------------------------------------------- step 1: fetch
def load_ids(links_csv, max_id):
    if links_csv and os.path.exists(links_csv):
        with open(links_csv, newline="", encoding="utf-8") as f:
            return [row["ymdb_id"] for row in csv.DictReader(f)]
    return [f"YMDB{n:05d}" for n in range(1, max_id + 1)]


def fetch(ids, workers):
    import requests

    os.makedirs(XML_DIR, exist_ok=True)
    done = set()
    if os.path.exists(STATUS_FILE):
        for line in open(STATUS_FILE):
            r = json.loads(line)
            if r["s"] in ("ok", "404"):
                done.add(r["id"])
    todo = [i for i in ids if i not in done]
    print(f"{len(ids)} IDs, {len(done)} already done, {len(todo)} to fetch")

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (academic research; metabolite concentration atlas)"
    lock = threading.Lock()
    log = open(STATUS_FILE, "a")
    counter = {"n": 0}

    def job(ymdb_id):
        status = "fail"
        for attempt in range(8):
            try:
                r = session.get(URL.format(ymdb_id), timeout=120)
                if r.status_code == 404:
                    status = "404"          # ID does not exist
                    break
                if r.status_code == 200 and b"<compound" in r.content[:500]:
                    with gzip.open(os.path.join(XML_DIR, f"{ymdb_id}.xml.gz"), "wb") as f:
                        f.write(r.content)
                    status = "ok"
                    break
                status = f"http{r.status_code}"
            except Exception:
                status = "error"
            time.sleep(min(300, 20 * 2 ** attempt))   # back off: 20s, 40s, 80s ... max 5 min
        with lock:
            log.write(json.dumps({"id": ymdb_id, "s": status, "t": time.time()}) + "\n")
            log.flush()
            counter["n"] += 1
            if counter["n"] % 100 == 0:
                print(f"  {counter['n']}/{len(todo)} fetched")

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(job, todo))

    failed = []
    for line in open(STATUS_FILE):
        r = json.loads(line)
        if r["s"] not in ("ok", "404"):
            failed.append(r["id"])
    print("Fetch finished.", f"Still failing (re-run to retry): {sorted(set(failed))}" if failed else "No failures.")


# ---------------------------------------------------------------- step 2: extract
def text(el, tag):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def extract(out_csv):
    rows, n_pages = [], 0
    for fname in sorted(os.listdir(XML_DIR)):
        path = os.path.join(XML_DIR, fname)
        src = gzip.open(path) if fname.endswith(".gz") else path
        root = ET.parse(src).getroot()
        n_pages += 1
        base = {
            "ymdb_id": text(root, "ymdb_id") or fname.split(".")[0],
            "name": text(root, "name"),
            "species": text(root, "species") or "Saccharomyces cerevisiae",
            "hmdb_id": text(root, "hmdb_id"),
            "kegg_id": text(root, "kegg_id"),
            "inchikey": text(root, "inchikey"),
            "formula": text(root, "chemical_formula"),
        }
        for block in root.iter("concentrations"):
            cur = None
            for child in block:
                # each <growth_media> starts a new measurement
                if child.tag == "growth_media" or cur is None:
                    if cur is not None:
                        rows.append(cur)
                    cur = dict(base, refs=[], pmids=[])
                if child.tag == "reference":
                    cur["refs"].append(text(child, "reference_text"))
                    cur["pmids"].append(text(child, "pubmed_id"))
                elif len(child) == 0:
                    # html.unescape turns "&#181;M" into "µM"
                    cur[child.tag] = html.unescape((child.text or "").strip())
            if cur is not None:
                rows.append(cur)

    out = []
    for r in rows:
        r["reference"] = " | ".join(x for x in r.pop("refs") if x)
        r["pubmed_id"] = " | ".join(x for x in r.pop("pmids") if x)
        if any(r.get(k) for k in ("concentration", "growth_media", "error")):   # skip empty blocks
            out.append(r)

    cols = ["ymdb_id", "name", "species", "growth_media", "concentration", "concentration_units",
            "error", "strain", "internal", "reference", "pubmed_id",
            "hmdb_id", "kegg_id", "inchikey", "formula"]
    cols += sorted({k for r in out for k in r} - set(cols))   # keep any unexpected fields too
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print(f"Read {n_pages} pages -> {len(out)} concentration rows for "
          f"{len({r['ymdb_id'] for r in out})} metabolites -> {out_csv}")


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["fetch", "extract", "all"])
    p.add_argument("--links", default=os.path.join(DATA, "ymdb_all_metabolite_links.csv"))
    p.add_argument("--max-id", type=int, default=16500, help="used if the links CSV is missing")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default=os.path.join(DATA, "ymdb_concentrations_all.csv"))
    a = p.parse_args()
    if a.step in ("fetch", "all"):
        fetch(load_ids(a.links, a.max_id), a.workers)
    if a.step in ("extract", "all"):
        extract(a.out)
