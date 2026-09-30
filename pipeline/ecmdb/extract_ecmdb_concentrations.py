"""
Step 2 (E. coli) -- fetch every ECMDB compound page and extract its concentrations.

ECMDB's download files carry structures and identifiers but no measured
concentrations; those appear only on each compound's own page. This reads the
XML version of every page (https://ecmdb.ca/compounds/ECMDBxxxxx.xml) and pulls
out each measurement with the conditions it was made under.

Unlike YMDB, no ID guessing is needed: ecmdb.json lists every compound, so the
ID list comes from the extract of that file and every request hits a real page.

Two steps:
  fetch    download each compound's XML into data/ecmdb/xml/ as .xml.gz.
           Resumable -- already-downloaded IDs are skipped, progress is logged
           to data/ecmdb/status.jsonl.
  extract  read the saved pages and write one row per concentration measurement
           to data/ecmdb/ecmdb_concentrations_all.csv.

ECMDB records more context per measurement than YMDB or HMDB: growth medium,
growth system, temperature, strain, growth phase, and the count of molecules per
cell. All of it is kept, because for a single-celled organism those conditions
are what the concentration depends on.

The <concentrations> block lists several measurements as repeated flat tags with
no wrapper per measurement, so each new <growth_media> starts a new record --
reading it with find() would keep only the first.

Usage:
    pip install requests
    python pipeline/ecmdb/extract_ecmdb_concentrations.py all --workers 8
    python pipeline/ecmdb/extract_ecmdb_concentrations.py extract   # rebuild the CSV only
"""
import argparse
import csv
import gzip
import html
import json
import os
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "ecmdb")
XML_DIR = os.path.join(DATA, "xml")
STATUS_FILE = os.path.join(DATA, "status.jsonl")
ID_SOURCE = os.path.join(DATA, "ecmdb_metabolites.csv")
URL = "https://ecmdb.ca/compounds/{}.xml"

# the fields a measurement can carry, in the order they appear on the page
MEASUREMENT_TAGS = ["growth_media", "growth_system", "concentration", "concentration_units",
                    "internal", "error", "temperature", "strain", "growth_status",
                    "molecules", "molecules_error"]


def load_ids():
    if not os.path.exists(ID_SOURCE):
        raise FileNotFoundError(
            "Couldn't find %s. Run pipeline/ecmdb/extract_ecmdb_downloads.py first." % ID_SOURCE)
    with open(ID_SOURCE, newline="", encoding="utf-8") as fh:
        return [r["met_id"] for r in csv.DictReader(fh) if r.get("met_id")]


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
    print("%s compounds, %s already fetched, %s to go"
          % (format(len(ids), ","), format(len(done), ","), format(len(todo), ",")))

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (academic research; metabolite concentration atlas)"
    lock = threading.Lock()
    log = open(STATUS_FILE, "a")
    counter = {"n": 0}

    def job(cid):
        status = "fail"
        for attempt in range(6):
            try:
                r = session.get(URL.format(cid), timeout=90)
                if r.status_code == 404:
                    status = "404"
                    break
                if r.status_code == 200 and b"<compound" in r.content[:500]:
                    with gzip.open(os.path.join(XML_DIR, "%s.xml.gz" % cid), "wb") as f:
                        f.write(r.content)
                    status = "ok"
                    break
                status = "http%d" % r.status_code
            except Exception:
                status = "error"
            time.sleep(min(120, 10 * 2 ** attempt))
        with lock:
            log.write(json.dumps({"id": cid, "s": status, "t": time.time()}) + "\n")
            log.flush()
            counter["n"] += 1
            if counter["n"] % 250 == 0:
                print("  %s/%s" % (format(counter["n"], ","), format(len(todo), ",")))

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(job, todo))

    failed = sorted({json.loads(l)["id"] for l in open(STATUS_FILE)
                     if json.loads(l)["s"] not in ("ok", "404")})
    still = [f for f in failed if not os.path.exists(os.path.join(XML_DIR, "%s.xml.gz" % f))]
    print("Fetch finished." if not still else
          "Fetch finished, %d still failing (re-run to retry): %s" % (len(still), still[:10]))


def text(el, tag):
    x = el.find(tag)
    return (x.text or "").strip() if x is not None and x.text else ""


def extract(out_csv):
    rows, pages = [], 0
    for fname in sorted(os.listdir(XML_DIR)):
        path = os.path.join(XML_DIR, fname)
        root = ET.parse(gzip.open(path) if fname.endswith(".gz") else path).getroot()
        pages += 1
        base = {
            "ecmdb_id": text(root, "accession") or fname.split(".")[0],
            "name": text(root, "name"),
            "species": "Escherichia coli",
            "hmdb_id": text(root, "hmdb_id"),
            "kegg_id": text(root, "kegg_id"),
            "inchikey": text(root, "inchikey"),
            "formula": text(root, "chemical_formula"),
            "cellular_location": "; ".join(
                (e.text or "").strip() for e in root.iter("cellular_location") if (e.text or "").strip()),
        }
        for block in root.iter("concentrations"):
            cur = None
            for child in block:
                if child.tag == "growth_media" or cur is None:
                    if cur is not None:
                        rows.append(cur)
                    cur = dict(base, refs=[], pmids=[])
                if child.tag == "reference":
                    cur["refs"].append(text(child, "reference_text"))
                    cur["pmids"].append(text(child, "pubmed_id"))
                elif len(child) == 0 and child.tag in MEASUREMENT_TAGS:
                    # "&#181;M" arrives HTML-escaped inside the XML text
                    cur[child.tag] = html.unescape((child.text or "").strip())
            if cur is not None:
                rows.append(cur)

    out = []
    for r in rows:
        r["reference"] = " | ".join(x for x in r.pop("refs") if x)
        r["pubmed_id"] = " | ".join(x for x in r.pop("pmids") if x)
        if any(r.get(k) for k in ("concentration", "growth_media", "error")):
            out.append(r)

    cols = ["ecmdb_id", "name", "species", "growth_media", "growth_system", "concentration",
            "concentration_units", "error", "temperature", "strain", "growth_status",
            "molecules", "molecules_error", "internal", "reference", "pubmed_id",
            "hmdb_id", "kegg_id", "inchikey", "formula", "cellular_location"]
    cols += sorted({k for r in out for k in r} - set(cols))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print("Read %s pages -> %s measurements for %s metabolites -> %s"
          % (format(pages, ","), format(len(out), ","),
             format(len({r["ecmdb_id"] for r in out}), ","), out_csv))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["fetch", "extract", "all"])
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default=os.path.join(DATA, "ecmdb_concentrations_all.csv"))
    a = p.parse_args()
    if a.step in ("fetch", "all"):
        fetch(load_ids(), a.workers)
    if a.step in ("extract", "all"):
        extract(a.out)
