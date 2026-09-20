"""
0_extract_ymdb_downloads.py
Convert YMDB's four official download files (https://www.ymdb.ca/downloads) to CSV.

The downloads are committed in data/ymdb/downloads/:
    ymdb.json.zip (read directly, no need to unzip), ymdb.sdf,
    protein_sequences.fasta, gene_sequences.fasta

Outputs (data/ymdb/):
    ymdb_json_full.csv.gz        every JSON record, all 48 fields; list fields kept as JSON text
    json_tables/*.csv            the same JSON split into linked tables (metabolites,
                                 concentrations, synonyms, pathways, references, proteins)
    ymdb_sdf_full.csv            every SDF record: all data fields + the MOL block
    ymdb_protein_sequences.csv   one row per protein (FASTA)
    ymdb_gene_sequences.csv      one row per gene (FASTA)

Findings (June 2019 download files):
  - ymdb.json is malformed: some records are joined with no comma, so json.load() fails.
    It is read here record by record with raw_decode(). It holds only 17 metabolites,
    although YMDB has 16,042 -- the official "full database" export is incomplete.
  - ymdb.sdf has 2,025 metabolites and no concentration data (structure/properties only).
  - The FASTA files hold the same 995 proteins; no concentration data.
  - Concentrations for all metabolites therefore come from the website instead:
    see ymdb_links.py and extract_ymdb_concentrations.py.
"""
import csv
import gzip
import html
import json
import os
import re
import zipfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data", "ymdb")
DOWNLOADS = os.path.join(DATA, "downloads")
LIST_FIELDS = ["synonyms", "pathways", "growth_conditions", "references", "proteins"]


def read_json_records(path):
    """Read ymdb.json (or ymdb.json.zip) even though records are not always comma-separated."""
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            s = z.read("ymdb.json").decode("utf-8")
    else:
        s = open(path, encoding="utf-8").read()
    dec = json.JSONDecoder()
    i, n, recs = s.index("[") + 1, len(s), []
    while i < n:
        while i < n and s[i] in " \n\r\t,]":
            i += 1
        if i >= n:
            break
        obj, i = dec.raw_decode(s, i)
        recs.append(obj)
    return recs


def extract_json():
    path = os.path.join(DOWNLOADS, "ymdb.json")
    if not os.path.exists(path):
        path += ".zip"
    if not os.path.exists(path):
        print("skip JSON: ymdb.json(.zip) not found"); return
    recs = read_json_records(path)

    # 1) full file, one row per metabolite, nested fields as JSON text (nothing dropped)
    cols = []
    for r in recs:
        cols += [k for k in r if k not in cols]
    out = os.path.join(DATA, "ymdb_json_full.csv.gz")
    with gzip.open(out, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in recs:
            w.writerow({k: json.dumps(r.get(k), ensure_ascii=False) if isinstance(r.get(k), (list, dict))
                        else ("" if r.get(k) is None else r.get(k)) for k in cols})

    # 2) linked tables
    met, conc, syn, pw, ref, prot = [], [], [], [], [], []
    for r in recs:
        mid, nm = r["ymdb_id"], r["name"]
        met.append({k: v for k, v in r.items() if k not in LIST_FIELDS})
        for g in r.get("growth_conditions") or []:
            conc.append({"ymdb_id": mid, "name": nm, "species": "Saccharomyces cerevisiae",
                         "growth_media": g.get("growth_media"), "concentration": g.get("concentration"),
                         "concentration_units": html.unescape(g.get("concentration_units") or ""),
                         "error": g.get("error")})
        for s in r.get("synonyms") or []:
            syn.append({"ymdb_id": mid, "synonym": s if isinstance(s, str) else s.get("name", str(s))})
        for p in r.get("pathways") or []:
            pw.append({"ymdb_id": mid, **p})
        for x in r.get("references") or []:
            ref.append({"ymdb_id": mid, **x})
        for p in r.get("proteins") or []:
            d = {k: v for k, v in p.items() if not isinstance(v, (list, dict))}
            d["n_reactions"] = len(p.get("reactions") or [])
            d["n_pathways"] = len(p.get("pathways") or [])
            d["go_classes"] = "; ".join(str(g.get("description", g) if isinstance(g, dict) else g)
                                        for g in p.get("go_classes") or [])
            d["enzyme_classes"] = "; ".join(map(str, p.get("enzyme_classes") or []))
            prot.append({"ymdb_id": mid, "metabolite": nm, **d})
    tdir = os.path.join(DATA, "json_tables")
    os.makedirs(tdir, exist_ok=True)
    for name, rows in [("metabolites", met), ("concentrations", conc), ("synonyms", syn),
                       ("pathways", pw), ("references", ref), ("proteins", prot)]:
        pd.DataFrame(rows).to_csv(os.path.join(tdir, f"ymdb_{name}.csv"), index=False)
    print(f"JSON: {len(recs)} records -> {out} and json_tables/")


def extract_sdf():
    path = os.path.join(DOWNLOADS, "ymdb.sdf")
    if not os.path.exists(path):
        print("skip SDF: ymdb.sdf not found"); return
    s = open(path, encoding="utf-8", errors="replace").read()
    rows, cols = [], ["YMDB_ID"]
    for block in (b for b in s.split("$$$$") if b.strip()):
        block = block.lstrip("\r\n")
        end = block.find("M  END")
        mol = block[:end + 6] if end >= 0 else ""
        d = {}
        body = block[end + 6:] if end >= 0 else block
        for m in re.finditer(r"^>\s*<([^>]+)>[^\n]*\n(.*?)(?=\n\s*\n|\Z)", body, re.S | re.M):
            d[m.group(1)] = m.group(2).strip()
            if m.group(1) not in cols:
                cols.append(m.group(1))
        d["MOLFILE"] = mol
        rows.append(d)
    cols.append("MOLFILE")
    out = os.path.join(DATA, "ymdb_sdf_full.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"SDF: {len(rows)} records -> {out}")


def extract_fasta(fname, kind, outname):
    path = os.path.join(DOWNLOADS, fname)
    if not os.path.exists(path):
        print(f"skip {fname}: not found"); return
    recs, header, seq = [], None, []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\r\n")
        if line.startswith(">"):
            if header is not None:
                recs.append((header, "".join(seq)))
            header, seq = line[1:], []
        elif line.strip():
            seq.append(line.strip())
    if header is not None:
        recs.append((header, "".join(seq)))
    rows = []
    for h, s in recs:
        # header looks like: ymdb_P38143 Glutathione peroxidase 2 (YMDB00693,YMDB00888,...)
        m = re.match(r"^(\S+)\s+(.*?)\s*\(([^()]*)\)\s*$", h)
        if m:
            fid, name, ids = m.groups()
        else:
            fid, _, name = h.partition(" ")
            ids = ""
        ids = [i.strip() for i in ids.split(",") if i.strip()]
        rows.append({"fasta_id": fid, "uniprot_id": fid.replace("ymdb_", ""), "protein_name": name,
                     "ymdb_ids": ";".join(ids), "n_metabolites": len(ids),
                     f"{kind}_sequence_length": len(s), f"{kind}_sequence": s, "fasta_header": h})
    out = os.path.join(DATA, outname)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"{fname}: {len(rows)} records -> {out}")


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    extract_json()
    extract_sdf()
    extract_fasta("protein_sequences.fasta", "protein", "ymdb_protein_sequences.csv")
    extract_fasta("gene_sequences.fasta", "gene", "ymdb_gene_sequences.csv")
