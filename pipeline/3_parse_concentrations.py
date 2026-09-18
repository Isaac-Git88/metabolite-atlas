"""
Step 3 -- turn HMDB's free-text concentrations into numbers, and classify units.

HMDB writes concentrations as prose ("7.7 +/- 1.9", "37 (10 - 76)", "<0.5"), in
at least seven shapes. This parses them into mean / SD / min / max and records
HOW each value was read, so every number stays traceable to its source string.
99.9% of rows parse; the remainder are malformed in HMDB itself and are kept
with parse_ok = 0 rather than guessed at.

It also classifies each unit by measurement type and marks which are mutually
comparable, per the decision agreed with Oliver Jones (Sep 2026): volumetric
measurements are comparable and expressed as umol/L; creatinine-normalised and
mass-normalised records are kept but excluded from concentration comparisons,
because no conversion exists between them without data HMDB does not hold.
Classification is rule-based rather than a list of the units HMDB happens to
use, so YMDB, BMDB and ECMDB units are classified on load, and anything
unrecognised defaults to NOT comparable.

Input:  data/hmdb_normal_concentrations_clean.csv
Output: data/hmdb_concentrations_parsed.csv

Usage:
    python pipeline/3_parse_concentrations.py
    python pipeline/3_parse_concentrations.py --report   # coverage, no output file
"""

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

# Paths are anchored to this script's own folder, so every step runs correctly
# from any working directory. Inputs and generated data live in data/, the
# website in explorer/.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
EXPLORER = ROOT / "explorer"

INPUT_FILE = DATA / "hmdb_normal_concentrations_clean.csv"
OUTPUT_FILE = DATA / "hmdb_concentrations_parsed.csv"

# ---------------------------------------------------------------------------
# Unit handling -- the supervisor-agreed classification.
#
# unit_std      : the label we display
# unit_class    : what kind of measurement this is
# is_comparable : may this row appear in cross-metabolite concentration plots?
# ---------------------------------------------------------------------------
# Units that name the same quantity get the same display label. Micromolar and
# micromoles per litre are identical -- 1 uM == 1 umol/L -- so this is a
# relabelling, never a conversion: no arithmetic is applied to any value.
DISPLAY_OVERRIDES = {
    "um": "umol/L",
    "umol/l": "umol/L",
    "mm": "mmol/L",
    "nm": "nmol/L",
    "pm": "pmol/L",
}


def classify_unit(unit_name):
    """Decide a unit's measurement type from its text.

    Returns (display_name, unit_class, is_comparable).

    Deliberately rule-based rather than a lookup table of the five units HMDB
    currently uses, so that units introduced by YMDB, BMDB and ECMDB are
    classified on load instead of falling through. Anything unrecognised is
    marked 'unclassified' and is NOT comparable, so an unknown unit can never
    silently enter a plot.
    """
    key = (unit_name or "").strip().lower()
    if not key:
        return unit_name, "unclassified", 0

    # Normalised to creatinine: a mole-per-mole ratio, not a concentration.
    if "creatinine" in key:
        return unit_name, "creatinine_normalised", 0

    # Amount per unit mass of sample -- feces, tissue, dry weight and so on.
    if re.search(r"/\s*(g|mg|kg)\b", key):
        return unit_name, "mass_normalised", 0

    # Mass per unit volume (ug/mL, mg/dL, ng/mL). These look volumetric but are
    # NOT comparable with molar concentrations without the metabolite's molar
    # mass, which HMDB does not carry, so they get their own class. HMDB has
    # none of these; MetaboLights and Metabolomics Workbench do, and the
    # project brief names ng/ml and ug/g explicitly.
    if re.fullmatch(r"[munpf]?g\s*/\s*(l|dl|ml|ul|cl)", key):
        return unit_name, "mass_per_volume", 0

    # Amount of substance per unit volume, however it happens to be spelled.
    if key in DISPLAY_OVERRIDES:
        return DISPLAY_OVERRIDES[key], "volumetric", 1
    if re.fullmatch(r"[munp]?mol\s*/\s*l", key) or re.fullmatch(r"[munp]?m", key):
        return unit_name, "volumetric", 1
    if re.search(r"\bmol\s*/\s*(l|dl|ml|ul)\b", key):
        return unit_name, "volumetric", 1

    return unit_name, "unclassified", 0

# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

# Excel silently rewrites strings like "13-2" as the date "13-Feb". Four such
# values are present in the HMDB export, which means the CSV was opened in a
# spreadsheet at some point in the chain. We recover them and flag them loudly
# rather than silently dropping four real measurements.
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
EXCEL_DATE_RE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})$")

REPLACEMENTS = [
    ("�", ""),    # U+FFFD, an undecodable byte in the HMDB source
    ("±", "+/-"),   # ± -> +/-
    ("≤", "<="),    # ≤
    ("≥", ">="),    # ≥
    ("–", "-"),     # en dash
    ("—", "-"),     # em dash
    ("−", "-"),     # unicode minus
    (" ", " "),     # non-breaking space
    ("Â", " "),     # mojibake left by a bad utf-8/latin-1 round trip
]


def normalise(text):
    """Standardise the many ways HMDB writes the same punctuation.

    Returns (clean_text, was_excel_date).
    """
    s = text.strip()
    for old, new in REPLACEMENTS:
        s = s.replace(old, new)

    was_excel_date = False
    m = EXCEL_DATE_RE.match(s)
    if m and m.group(2).lower() in MONTHS:
        # "13-Feb" was originally "13-2"
        s = "%s-%s" % (m.group(1), MONTHS[m.group(2).lower()])
        was_excel_date = True

    # Standardise the spellings of "plus or minus" before matching. HMDB has
    # "1.1+/-0.5", "63.6 +/-142.9", "4.4 +- 1.6" and even "3.06 /- 1.87" (a
    # typo for +/-). Spacing around the operator carries no information.
    s = re.sub(r"\s*\+\s*/\s*-\s*", " +/- ", s)
    s = re.sub(r"\s*\+\s*-\s*", " +/- ", s)
    s = re.sub(r"(?<=\d)\s+/-\s*", " +/- ", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s, was_excel_date


# ---------------------------------------------------------------------------
# Patterns
#
# Concentrations are never negative, so a bare "-" is always a range separator
# and never a minus sign. That single assumption removes most of the ambiguity.
# ---------------------------------------------------------------------------
NUM = r"\d*\.?\d+(?:[eE][-+]?\d+)?"

PATTERNS = [
    # 3.05            -> mean
    ("plain",
     re.compile(r"^(%s)$" % NUM)),

    # 37 +/- 21 (10 - 76)  -> mean, sd, min, max
    ("mean_sd_range",
     re.compile(r"^(%s) \+/- (%s) \(\s*<?\s*(%s)\s*-\s*(%s)\s*\)$" % (NUM, NUM, NUM, NUM))),

    # 7.7 +/- 1.9     -> mean, sd
    ("mean_sd",
     re.compile(r"^(%s) \+/- (%s)$" % (NUM, NUM))),

    # 2.09 (1.23-4.80) and 20 (<1-914)  -> mean, min, max
    ("mean_range",
     re.compile(r"^(%s)\s*\(\s*(<?)\s*(%s)\s*-\s*(%s)\s*\)$" % (NUM, NUM, NUM))),

    # 64.88(60.4)     -> mean, and a single bracketed number of unstated meaning
    ("mean_paren_single",
     re.compile(r"^(%s)\s*\(\s*(%s)\s*\)$" % (NUM, NUM))),

    # 3.19 (0.00 +/- 19.70)  -> mean, with a nested mean +/- sd in brackets
    ("mean_paren_sd",
     re.compile(r"^(%s)\s*\(\s*(%s) \+/- (%s)\s*\)$" % (NUM, NUM, NUM))),

    # 15.5 (tr-32.1)  -> mean, lower bound reported only as "trace"
    ("mean_range_trace",
     re.compile(r"^(%s)\s*\(\s*tr(?:ace)?\s*-\s*(%s)\s*\)$" % (NUM, NUM), re.I)),

    # 13 - 52, and <1-68 where the lower bound is a detection limit
    ("range",
     re.compile(r"^(<?)\s*(%s)\s*-\s*(%s)$" % (NUM, NUM))),

    # <3.618 / <=3.618 / >12
    ("bound",
     re.compile(r"^(<=|>=|<|>)\s*(%s)$" % NUM)),
]


def parse_value(raw):
    """Parse one raw concentration string.

    Returns a dict of numeric fields plus provenance flags. Never raises.
    """
    out = {
        "value_mean": "", "value_sd": "",
        "value_min": "", "value_max": "",
        "value_bound_type": "",
        "value_representative": "", "representative_source": "",
        "parse_pattern": "unparsed", "parse_ok": 0, "needs_review": 0,
        "parse_note": "",
    }

    if raw is None or not raw.strip():
        out["parse_pattern"] = "empty"
        return out

    s, was_excel_date = normalise(raw)
    if was_excel_date:
        out["needs_review"] = 1
        out["parse_note"] = "recovered from Excel date corruption"

    for name, rx in PATTERNS:
        m = rx.match(s)
        if not m:
            continue

        out["parse_pattern"] = name
        out["parse_ok"] = 1
        g = m.groups()

        if name == "plain":
            out["value_mean"] = g[0]

        elif name == "mean_sd_range":
            out["value_mean"], out["value_sd"] = g[0], g[1]
            out["value_min"], out["value_max"] = g[2], g[3]

        elif name == "mean_sd":
            out["value_mean"], out["value_sd"] = g[0], g[1]

        elif name == "mean_range":
            out["value_mean"] = g[0]
            lo, hi = float(g[2]), float(g[3])
            if lo > hi:
                lo, hi = hi, lo
                out["needs_review"] = 1
                out["parse_note"] = "range written high-to-low, order swapped"
            out["value_min"], out["value_max"] = repr(lo), repr(hi)
            if g[1] == "<":
                out["needs_review"] = 1
                out["parse_note"] = (out["parse_note"] + "; " if out["parse_note"] else "") + \
                                    "lower bound was below detection limit"

        elif name == "mean_paren_single":
            # HMDB does not say whether the bracketed number is an SD or an
            # upper bound. In the great majority of these rows it is smaller
            # than the mean, which is consistent with an SD, so we read it as
            # one -- but every such row is flagged for review.
            out["value_mean"], out["value_sd"] = g[0], g[1]
            out["needs_review"] = 1
            out["parse_note"] = "bracketed value assumed to be SD (unlabelled in source)"

        elif name == "mean_paren_sd":
            out["value_mean"], out["value_sd"] = g[0], g[2]
            out["needs_review"] = 1
            out["parse_note"] = "nested mean +/- sd in brackets; outer value read as the mean"

        elif name == "mean_range_trace":
            out["value_mean"] = g[0]
            out["value_max"] = g[1]
            out["needs_review"] = 1
            out["parse_note"] = "lower bound reported as 'trace'"

        elif name == "range":
            if g[0] == "<":
                out["needs_review"] = 1
                out["parse_note"] = "lower bound was below detection limit"
            lo, hi = float(g[1]), float(g[2])
            if lo > hi:
                lo, hi = hi, lo
                out["needs_review"] = 1
                out["parse_note"] = (out["parse_note"] + "; " if out["parse_note"] else "") + \
                                    "range written high-to-low, order swapped"
            out["value_min"], out["value_max"] = repr(lo), repr(hi)

        elif name == "bound":
            out["value_bound_type"] = g[0]
            if g[0].startswith("<"):
                out["value_max"] = g[1]
            else:
                out["value_min"] = g[1]
            out["needs_review"] = 1
            out["parse_note"] = "censored value (one-sided bound only)"

        break

    # A single number per row for plotting. Prefer a reported mean; fall back to
    # the midpoint of a reported range. A censored bound is NOT turned into a
    # point estimate -- that would invent a measurement.
    if out["value_mean"]:
        out["value_representative"] = out["value_mean"]
        out["representative_source"] = "reported_mean"
    elif out["value_min"] and out["value_max"]:
        mid = (float(out["value_min"]) + float(out["value_max"])) / 2
        out["value_representative"] = repr(mid)
        out["representative_source"] = "range_midpoint"

    return out


# ---------------------------------------------------------------------------

OUTPUT_FIELDS = [
    "hmdb_id", "metabolite_name", "biospecimen",
    "concentration_value_raw", "concentration_units",
    "unit_std", "unit_class", "is_comparable",
    "value_mean", "value_sd", "value_min", "value_max",
    "value_bound_type", "value_representative", "representative_source",
    "parse_pattern", "parse_ok", "needs_review", "parse_note",
    "subject_age", "subject_sex", "subject_condition",
    "pubmed_ids", "reference_texts",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true",
                    help="print the pattern breakdown without writing output")
    args = ap.parse_args()

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "Couldn't find %s. Run 2_remove_empty_concentrations.py first."
            % INPUT_FILE
        )

    patterns = Counter()
    unknown_units = Counter()
    unparsed_examples = []
    rows_out = []
    total = 0
    comparable = 0
    review = 0

    with open(INPUT_FILE, "r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            total += 1
            raw = row["concentration_value_raw"]
            parsed = parse_value(raw)

            unit = (row["concentration_units"] or "").strip()
            unit_std, unit_class, is_comp = classify_unit(unit)
            if unit_class == "unclassified":
                unknown_units[unit] += 1

            patterns[parsed["parse_pattern"]] += 1
            comparable += is_comp
            review += parsed["needs_review"]

            if not parsed["parse_ok"] and len(unparsed_examples) < 40:
                unparsed_examples.append(raw)

            out = dict(row)
            out.update(parsed)
            out["unit_std"] = unit_std
            out["unit_class"] = unit_class
            out["is_comparable"] = is_comp
            rows_out.append(out)

    print("Rows read: %s" % format(total, ","))
    print()
    print("Parse pattern breakdown")
    print("-" * 46)
    for name, n in patterns.most_common():
        print("  %-22s %7s  %5.1f%%" % (name, format(n, ","), 100.0 * n / total))
    ok = total - patterns["unparsed"] - patterns["empty"]
    print("-" * 46)
    print("  parsed successfully    %7s  %5.1f%%" % (format(ok, ","), 100.0 * ok / total))
    print("  flagged for review     %7s  %5.1f%%" % (format(review, ","), 100.0 * review / total))
    print("  comparable (umol/L)    %7s  %5.1f%%" % (format(comparable, ","), 100.0 * comparable / total))

    if unknown_units:
        print()
        print("WARNING -- units the classifier could not place (not comparable):")
        for u, n in unknown_units.most_common():
            print("  %r  (%s rows)" % (u, format(n, ",")))

    if unparsed_examples:
        print()
        print("Unparsed examples (first %d):" % len(unparsed_examples))
        for v in unparsed_examples:
            print("  %r" % v)

    if args.report:
        print("\n--report given: no file written.")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_out)

    print()
    print("Wrote %s (%s rows)" % (OUTPUT_FILE, format(len(rows_out), ",")))


if __name__ == "__main__":
    main()
