"""
Step 4 -- build the normalised SQLite database and the reference-range table.

Five related tables (metabolites, biospecimens, concentration_units,
references, measurements) plus reference_ranges: the summary statistics the
project exists to produce, one row per metabolite x biospecimen.

Method, and its limits -- state these in the report:
  Each measurement contributes one representative value: the mean as reported,
  or the midpoint of a reported range where no mean was given. Studies are
  pooled UNWEIGHTED, because HMDB does not record sample sizes, so a study of 8
  subjects counts the same as one of 800. The statistics therefore describe the
  spread of reported values across the literature, not a sample-weighted
  population distribution. One-sided detection limits ("<0.5") are retained in
  measurements but excluded from the statistics, since they give no point
  estimate.

Metabolite identity across species -- two levels, deliberately kept apart:

  Same metabolite   Rows merge into one metabolite only when their FULL standard
                    InChIKeys agree. Merging on the connectivity layer instead
                    would be wrong within a species: it collapses L-isoleucine
                    with L-alloisoleucine, and ornithine with D-ornithine, which
                    are different metabolites with different normal ranges.

  Related structure The connectivity layer (the key's first block) is stored as
                    inchikey_block, and v_cross_species pairs ranges across
                    species on it. HMDB and YMDB often record the same molecule
                    with different stereo detail, so this recovers about 650
                    yeast-human pairs where exact keys match only 144. The
                    pairing is offered as a view, never as a merge, so the
                    stereochemistry caveat stays visible to whoever uses it.

  Each metabolite keeps its own metabolite_id -- the HMDB accession where there
  is one, otherwise the source's own id -- so a metabolite that exists in only
  one database (186 yeast-only ones, mostly lipids) still loads.

Input:  data/hmdb_concentrations_parsed.csv, data/ymdb_concentrations_parsed.csv,
        and any other data/<source>_concentrations_parsed.csv
        data/hmdb_inchikey_lookup.csv -- InChIKeys for HMDB metabolites, which
        HMDB's concentration records do not carry
Output: data/metabolite_atlas.db

Usage:
    pip install pandas
    python pipeline/4_build_database.py
"""

import sqlite3
import pandas as pd
from pathlib import Path

# Paths are anchored to this script's own folder, so every step runs correctly
# from any working directory. Inputs and generated data live in data/, the
# website in explorer/.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
EXPLORER = ROOT / "explorer"

# Every parsed source found here is loaded; a missing one is simply skipped, so
# the atlas grows by adding a file rather than by editing this script.
CSV_PATHS = [
    DATA / "hmdb_concentrations_parsed.csv",
    DATA / "ymdb_concentrations_parsed.csv",
    DATA / "bmdb_concentrations_parsed.csv",
    DATA / "ecmdb_concentrations_parsed.csv",
]
INCHIKEY_LOOKUP = DATA / "hmdb_inchikey_lookup.csv"
DB_PATH = DATA / "metabolite_atlas.db"

SCHEMA = """
-- Species is recorded per measurement, not per source database. The
-- HMDB-family databases each cover one organism, but MetaboLights and
-- Metabolomics Workbench carry many organisms per repository, so the organism
-- has to live on the row.
CREATE TABLE species (
    species_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scientific_name TEXT NOT NULL UNIQUE,   -- Homo sapiens
    common_name     TEXT NOT NULL,          -- Human
    ncbi_taxon_id   INTEGER                 -- stable external identifier
);

-- One row per distinct molecule, across every source database. metabolite_id
-- is the HMDB accession where there is one and the source's own identifier
-- otherwise (e.g. YMDB01248 for a yeast lipid HMDB has never catalogued).
CREATE TABLE metabolites (
    metabolite_id   TEXT PRIMARY KEY,
    metabolite_name TEXT NOT NULL,
    hmdb_id         TEXT,
    ymdb_id         TEXT,
    inchikey        TEXT,           -- full standard InChIKey, where known
    inchikey_block  TEXT,           -- connectivity layer: what identity is matched on
    n_sources       INTEGER NOT NULL
);

CREATE INDEX idx_met_inchikey_block ON metabolites(inchikey_block);
CREATE INDEX idx_met_hmdb           ON metabolites(hmdb_id);

CREATE TABLE biospecimens (
    biospecimen_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE
);

-- unit_class distinguishes the three kinds of measurement HMDB mixes together.
-- is_comparable = 1 marks the volumetric measurements that can be plotted on a
-- shared concentration axis; creatinine-normalised and fecal-mass rows are
-- retained but excluded from comparison.
CREATE TABLE concentration_units (
    unit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_name       TEXT NOT NULL UNIQUE,   -- as written in HMDB
    unit_std        TEXT NOT NULL,          -- display label (uM -> umol/L)
    unit_class      TEXT NOT NULL,          -- volumetric | mass_per_volume | creatinine_normalised
                                            -- | mass_normalised | unclassified
    is_comparable   INTEGER NOT NULL        -- 1 = may appear in concentration plots
);

CREATE TABLE "references" (
    reference_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pubmed_id       TEXT UNIQUE,
    reference_text  TEXT
);

CREATE TABLE measurements (
    measurement_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    species_id              INTEGER NOT NULL REFERENCES species(species_id),
    source_db               TEXT NOT NULL,   -- HMDB | YMDB | BMDB | ECMDB | ...
    metabolite_id           TEXT NOT NULL REFERENCES metabolites(metabolite_id),
    biospecimen_id          INTEGER NOT NULL REFERENCES biospecimens(biospecimen_id),
    unit_id                 INTEGER NOT NULL REFERENCES concentration_units(unit_id),

    -- the source string, kept verbatim so every number stays traceable
    concentration_value_raw TEXT NOT NULL,

    -- parsed numerics (any may be NULL depending on how the source reported it)
    value_mean              REAL,
    value_sd                REAL,
    value_min               REAL,
    value_max               REAL,
    value_bound_type        TEXT,     -- <, <=, >, >= for censored values
    value_representative    REAL,     -- one number per row, for plotting
    representative_source   TEXT,     -- reported_mean | range_midpoint

    -- parse provenance
    parse_pattern           TEXT NOT NULL,
    parse_ok                INTEGER NOT NULL,
    needs_review            INTEGER NOT NULL,
    parse_note              TEXT,

    subject_age             TEXT,
    subject_sex             TEXT,
    subject_condition       TEXT,
    reference_id            INTEGER REFERENCES "references"(reference_id)
);

CREATE INDEX idx_meas_species     ON measurements(species_id);
CREATE INDEX idx_meas_source      ON measurements(source_db);
CREATE INDEX idx_meas_metabolite  ON measurements(metabolite_id);
CREATE INDEX idx_meas_biospecimen ON measurements(biospecimen_id);
CREATE INDEX idx_meas_unit        ON measurements(unit_id);
CREATE INDEX idx_meas_parse_ok    ON measurements(parse_ok);
CREATE INDEX idx_met_name         ON metabolites(metabolite_name);

-- Everything the interface is allowed to plot: comparable units, successfully
-- parsed, with a usable numeric value.
CREATE VIEW v_comparable AS
SELECT
    ms.measurement_id,
    ms.species_id,
    sp.common_name      AS species,
    sp.scientific_name  AS species_scientific,
    ms.source_db,
    ms.metabolite_id,
    m.hmdb_id,
    m.metabolite_name,
    b.name              AS biospecimen,
    u.unit_std          AS unit,
    ms.value_representative,
    ms.value_mean, ms.value_sd, ms.value_min, ms.value_max,
    ms.representative_source,
    ms.needs_review,
    ms.subject_age, ms.subject_sex, ms.subject_condition,
    ms.reference_id,
    ms.concentration_value_raw
FROM measurements ms
JOIN species sp            ON sp.species_id = ms.species_id
JOIN metabolites m         ON m.metabolite_id = ms.metabolite_id
JOIN biospecimens b        ON b.biospecimen_id = ms.biospecimen_id
JOIN concentration_units u ON u.unit_id = ms.unit_id
WHERE u.is_comparable = 1
  AND ms.parse_ok = 1
  AND ms.value_representative IS NOT NULL;

-- Audit view: what was set aside, and why. Useful for the report, and for
-- showing the exclusion in the interface rather than hiding it.
CREATE VIEW v_excluded AS
SELECT
    u.unit_std AS unit,
    u.unit_class,
    CASE
        WHEN u.is_comparable = 0 THEN 'non-comparable unit'
        WHEN ms.parse_ok = 0     THEN 'value could not be parsed'
        ELSE 'no numeric value'
    END AS reason,
    COUNT(*) AS n
FROM measurements ms
JOIN concentration_units u ON u.unit_id = ms.unit_id
WHERE u.is_comparable = 0 OR ms.parse_ok = 0 OR ms.value_representative IS NULL
GROUP BY 1, 2, 3;

-- Cross-species pairing: the same structure measured in two organisms, matched
-- on the InChIKey connectivity layer so that stereochemistry recorded
-- differently by two databases does not hide the pair. Rows stay separate
-- metabolites; this view only puts them side by side, and same_full_inchikey
-- says whether the match is exact or connectivity-only.
CREATE VIEW v_cross_species AS
SELECT
    a.species           AS species_a,
    a.metabolite_id     AS metabolite_id_a,
    a.metabolite_name   AS metabolite_name_a,
    a.biospecimen       AS biospecimen_a,
    a.median            AS median_a,
    b.species           AS species_b,
    b.metabolite_id     AS metabolite_id_b,
    b.metabolite_name   AS metabolite_name_b,
    b.biospecimen       AS biospecimen_b,
    b.median            AS median_b,
    a.unit              AS unit,
    ma.inchikey_block   AS inchikey_block,
    CASE WHEN ma.inchikey IS NOT NULL AND ma.inchikey = mb.inchikey
         THEN 1 ELSE 0 END AS same_full_inchikey
FROM reference_ranges a
JOIN metabolites ma ON ma.metabolite_id = a.metabolite_id
JOIN metabolites mb ON mb.inchikey_block = ma.inchikey_block
JOIN reference_ranges b ON b.metabolite_id = mb.metabolite_id
WHERE a.species_id < b.species_id
  AND a.unit = b.unit
  AND ma.inchikey_block IS NOT NULL;

-- Materialised summary statistics: one row per species x metabolite x
-- biospecimen. This is the "reference range" the project set out to produce.
-- Species is part of the key: the same metabolite in the same biofluid is a
-- different normal range in a different organism, which is the whole point of
-- a cross-species atlas.
CREATE TABLE reference_ranges (
    species_id      INTEGER NOT NULL REFERENCES species(species_id),
    species         TEXT NOT NULL,
    metabolite_id   TEXT NOT NULL REFERENCES metabolites(metabolite_id),
    hmdb_id         TEXT,
    metabolite_name TEXT NOT NULL,
    biospecimen     TEXT NOT NULL,
    unit            TEXT NOT NULL,
    n_measurements  INTEGER NOT NULL,
    n_references    INTEGER NOT NULL,
    mean            REAL,
    median          REAL,
    sd              REAL,
    p25             REAL,
    p75             REAL,
    range_low       REAL,
    range_high      REAL,
    n_needs_review  INTEGER NOT NULL,
    PRIMARY KEY (species_id, metabolite_id, biospecimen)
);

CREATE INDEX idx_rr_name        ON reference_ranges(metabolite_name);
CREATE INDEX idx_rr_biospecimen ON reference_ranges(biospecimen);
CREATE INDEX idx_rr_species      ON reference_ranges(species);
"""


def to_num(series):
    return pd.to_numeric(series, errors="coerce")


def resolve_metabolites(df):
    """Give every row a metabolite_id, and decide which rows are the same molecule.

    Two rows describe the same metabolite when either is true:
      * their full standard InChIKeys agree -- the structure, stereochemistry
        included; or
      * one database says so: a YMDB row carrying an HMDB cross-reference is
        that HMDB metabolite, on YMDB's own authority.

    Connectivity-only matches are deliberately NOT merged here (see the module
    docstring): they would collapse L-isoleucine with L-alloisoleucine and
    D-ornithine with ornithine. They are offered instead through v_cross_species.

    Rows with neither a key nor a cross-reference keep their own identifier, so
    a metabolite only one database knows about still loads.
    """
    native = df["native_id"].fillna("").replace("", pd.NA).fillna(df["hmdb_id"])
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # every row's identifiers become one connected group
    row_keys = []
    for ik, hid, nid in zip(df["inchikey"].fillna(""), df["hmdb_id"].fillna(""),
                            native.fillna("")):
        keys = [k for k in ("ik:" + ik if ik else "", "id:" + hid if hid else "",
                            "id:" + str(nid) if nid else "") if k]
        if not keys:
            keys = ["row:%d" % len(row_keys)]
        for k in keys[1:]:
            union(keys[0], k)
        row_keys.append(keys[0])

    group = pd.Series([find(k) for k in row_keys], index=df.index)

    canonical, rows = {}, {}
    for g, chunk in df.assign(_g=group, _native=native).groupby("_g", sort=False):
        hmdb_ids = sorted({i for i in chunk["hmdb_id"].dropna() if i})
        ymdb_ids = sorted({str(i) for i in chunk["_native"].dropna()
                           if str(i).startswith("YMDB")})
        ids = sorted({str(i) for i in chunk["_native"].dropna() if i})
        chosen = hmdb_ids[0] if hmdb_ids else (ids[0] if ids else g)
        canonical[g] = chosen
        ik = sorted({k for k in chunk["inchikey"].dropna() if k})
        rows[chosen] = {
            "metabolite_id": chosen,
            # the most common spelling, so a one-off name does not win
            "metabolite_name": chunk["metabolite_name"].value_counts().index[0],
            "hmdb_id": hmdb_ids[0] if hmdb_ids else None,
            "ymdb_id": ymdb_ids[0] if ymdb_ids else None,
            "inchikey": ik[0] if ik else None,
            "inchikey_block": (ik[0].split("-")[0] if ik else None),
            "n_sources": chunk["source_db"].nunique(),
        }

    df = df.assign(metabolite_id=group.map(canonical))
    return df, pd.DataFrame(list(rows.values()))


def main():
    paths = [p for p in CSV_PATHS if p.exists()]
    if not paths:
        raise FileNotFoundError(
            "No parsed CSVs found in %s. Run 3_parse_concentrations.py first." % DATA
        )

    frames = []
    for path in paths:
        part = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        print("Reading %-42s %s rows" % (path.name, format(len(part), ",")))
        frames.append(part)
    df = pd.concat(frames, ignore_index=True)
    for col in ["native_id", "inchikey"]:
        if col not in df.columns:
            df[col] = pd.NA
    print("  %s rows in total" % format(len(df), ","))

    # HMDB's concentration records carry no structure key, so the InChIKeys come
    # from the lookup table built alongside them (see data/hmdb_inchikey_lookup.csv).
    if INCHIKEY_LOOKUP.exists():
        look = pd.read_csv(INCHIKEY_LOOKUP, dtype=str, keep_default_na=False,
                           na_values=[""]).dropna(subset=["inchikey"])
        mapping = dict(zip(look["hmdb_id"], look["inchikey"]))
        filled = df["inchikey"].isna() & df["hmdb_id"].map(mapping).notna()
        df.loc[filled, "inchikey"] = df.loc[filled, "hmdb_id"].map(mapping)
        print("  InChIKeys added from the lookup table: %s rows"
              % format(int(filled.sum()), ","))
    else:
        print("  %s not found: rows keep whatever InChIKey their source gave"
              % INCHIKEY_LOOKUP.name)

    df, metabolites_table = resolve_metabolites(df)

    for col in ["value_mean", "value_sd", "value_min", "value_max",
                "value_representative"]:
        df[col] = to_num(df[col])
    for col in ["parse_ok", "needs_review", "is_comparable"]:
        df[col] = to_num(df[col]).fillna(0).astype(int)

    if DB_PATH.exists():
        # v2 is rebuilt from the CSV each run; v1 (metabolite_atlas.db) is
        # never touched.
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    # --- species: one row per organism present in the parsed CSV ---
    species = (df[["species_scientific", "species_common", "ncbi_taxon_id"]]
               .dropna(subset=["species_scientific"])
               .drop_duplicates("species_scientific")
               .rename(columns={"species_scientific": "scientific_name",
                                "species_common": "common_name",
                                "ncbi_taxon_id": "ncbi_taxon_id"})
               .sort_values("scientific_name"))
    species["ncbi_taxon_id"] = to_num(species["ncbi_taxon_id"])
    species.to_sql("species", conn, if_exists="append", index=False)
    species_map = dict(conn.execute(
        "SELECT scientific_name, species_id FROM species").fetchall())
    print("  species:             %s" % format(len(species), ","))
    for r in conn.execute("SELECT common_name, scientific_name, ncbi_taxon_id FROM species"):
        print("      %-10s %-26s taxon %s" % (r[0], r[1], r[2]))

    # --- metabolites: one row per molecule, shared across sources ---
    metabolites_table.to_sql("metabolites", conn, if_exists="append", index=False)
    shared = int((metabolites_table["n_sources"] > 1).sum())
    print("  metabolites:         %s  (%s found in more than one source)"
          % (format(len(metabolites_table), ","), format(shared, ",")))

    # --- biospecimens ---
    biospecimens = pd.DataFrame({"name": sorted(df["biospecimen"].dropna().unique())})
    biospecimens.to_sql("biospecimens", conn, if_exists="append", index=False)
    bio_map = dict(conn.execute("SELECT name, biospecimen_id FROM biospecimens").fetchall())
    print("  biospecimens:        %s" % format(len(biospecimens), ","))

    # --- units, carrying the agreed classification through from the parser ---
    units = (df[["concentration_units", "unit_std", "unit_class", "is_comparable"]]
             .dropna(subset=["concentration_units"])
             .drop_duplicates("concentration_units")
             .rename(columns={"concentration_units": "unit_name"})
             .sort_values("unit_name"))
    units.to_sql("concentration_units", conn, if_exists="append", index=False)
    unit_map = dict(conn.execute("SELECT unit_name, unit_id FROM concentration_units").fetchall())
    print("  concentration_units: %s" % format(len(units), ","))
    for r in conn.execute("SELECT unit_std, unit_class, is_comparable FROM concentration_units"):
        print("      %-22s %-22s comparable=%d" % r)

    # --- references ---
    refs = (df[["pubmed_ids", "reference_texts"]]
            .dropna(subset=["pubmed_ids"])
            .drop_duplicates("pubmed_ids")
            .rename(columns={"pubmed_ids": "pubmed_id",
                             "reference_texts": "reference_text"}))
    refs.to_sql("references", conn, if_exists="append", index=False)
    ref_map = dict(conn.execute('SELECT pubmed_id, reference_id FROM "references"').fetchall())
    print("  references:          %s" % format(len(refs), ","))

    # --- measurements ---
    measurements = pd.DataFrame({
        "species_id": df["species_scientific"].map(species_map),
        "source_db": df["source_db"],
        "metabolite_id": df["metabolite_id"],
        "biospecimen_id": df["biospecimen"].map(bio_map),
        "unit_id": df["concentration_units"].map(unit_map),
        "concentration_value_raw": df["concentration_value_raw"],
        "value_mean": df["value_mean"],
        "value_sd": df["value_sd"],
        "value_min": df["value_min"],
        "value_max": df["value_max"],
        "value_bound_type": df["value_bound_type"],
        "value_representative": df["value_representative"],
        "representative_source": df["representative_source"],
        "parse_pattern": df["parse_pattern"],
        "parse_ok": df["parse_ok"],
        "needs_review": df["needs_review"],
        "parse_note": df["parse_note"],
        "subject_age": df["subject_age"],
        "subject_sex": df["subject_sex"],
        "subject_condition": df["subject_condition"],
        "reference_id": df["pubmed_ids"].map(ref_map),
    })
    measurements.to_sql("measurements", conn, if_exists="append", index=False)
    print("  measurements:        %s" % format(len(measurements), ","))
    conn.commit()

    # --- reference ranges -------------------------------------------------
    # Computed in pandas because SQLite has no median or percentile function.
    #
    # Methodological note: summary statistics are computed over one
    # representative value per measurement (the reported mean, or the midpoint
    # of a reported range). Studies are NOT weighted by their sample size,
    # because HMDB does not record n for most entries. Censored values ("<0.5")
    # carry no representative value and are excluded from the statistics,
    # though they remain in the measurements table.
    comp = pd.read_sql_query("SELECT * FROM v_comparable", conn)
    print("\n  comparable, parsed, plottable: %s rows" % format(len(comp), ","))

    grouped = comp.groupby(["species_id", "species", "metabolite_id", "hmdb_id",
                            "metabolite_name", "biospecimen", "unit"], dropna=False)
    rr = grouped.agg(
        n_measurements=("value_representative", "size"),
        n_references=("reference_id", lambda s: s.nunique()),
        mean=("value_representative", "mean"),
        median=("value_representative", "median"),
        sd=("value_representative", "std"),
        p25=("value_representative", lambda s: s.quantile(0.25)),
        p75=("value_representative", lambda s: s.quantile(0.75)),
        n_needs_review=("needs_review", "sum"),
    ).reset_index()

    # Observed range: widen to any explicitly reported min/max, since a study
    # reporting "37 (10 - 76)" tells us more about the range than its mean does.
    lows = comp["value_min"].fillna(comp["value_representative"])
    highs = comp["value_max"].fillna(comp["value_representative"])
    bounds = (comp.assign(_lo=lows, _hi=highs)
                  .groupby(["species_id", "metabolite_id", "biospecimen"])
                  .agg(range_low=("_lo", "min"), range_high=("_hi", "max"))
                  .reset_index())
    rr = rr.merge(bounds, on=["species_id", "metabolite_id", "biospecimen"], how="left")

    rr = rr[["species_id", "species", "metabolite_id", "hmdb_id", "metabolite_name",
             "biospecimen", "unit",
             "n_measurements", "n_references", "mean", "median", "sd",
             "p25", "p75", "range_low", "range_high", "n_needs_review"]]
    rr.to_sql("reference_ranges", conn, if_exists="append", index=False)
    print("  reference_ranges:    %s (species x metabolite x biospecimen)" % format(len(rr), ","))
    print("    with 3+ measurements: %s" % format(int((rr["n_measurements"] >= 3).sum()), ","))

    conn.commit()

    print("\n  by species:")
    for r in conn.execute("""SELECT species, COUNT(*), COUNT(DISTINCT metabolite_id)
                               FROM reference_ranges GROUP BY 1 ORDER BY 2 DESC"""):
        print("      %-10s %6s ranges across %s metabolites"
              % (r[0], format(r[1], ","), format(r[2], ",")))

    print("\nExcluded from comparable plots (kept in the database):")
    for unit, cls, reason, n in conn.execute(
            "SELECT unit, unit_class, reason, n FROM v_excluded ORDER BY n DESC"):
        print("  %-22s %-22s %-26s %s" % (unit, cls, reason, format(n, ",")))

    conn.close()
    print("\nWrote %s" % DB_PATH)


if __name__ == "__main__":
    main()
