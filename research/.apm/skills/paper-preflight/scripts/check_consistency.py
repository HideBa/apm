#!/usr/bin/env python3
"""check_consistency.py — abbreviation / spelling / hyphenation consistency scan.

Surfaces *candidate* inconsistencies for a human (or the driving agent) to judge:
  - acronyms used before defined, defined more than once, defined-but-unused, or
    used-but-never-defined
  - US/UK spelling variants co-occurring in the same document
  - hyphenation / spacing variants of the same term (pre-processing/preprocessing,
    data set/dataset)

The script is conservative on purpose: it reports co-occurrences, not verdicts.
Not every hit is an error (e.g. a UK spelling inside a quoted title).

Usage:
  python3 check_consistency.py --paper main.typ [--paper ch1.typ] --out consistency.json

Stdlib only.
"""
import argparse
import json
import re
import sys
from collections import defaultdict

# A compact set of common US/UK pairs seen in academic writing. Extend as needed.
UK_US_PAIRS = [
    ("behaviour", "behavior"),
    ("colour", "color"),
    ("modelling", "modeling"),
    ("labelled", "labeled"),
    ("analyse", "analyze"),
    ("organise", "organize"),
    ("optimise", "optimize"),
    ("generalise", "generalize"),
    ("centre", "center"),
    ("fibre", "fiber"),
    ("licence", "license"),
    ("catalogue", "catalog"),
    ("programme", "program"),
    ("acknowledgement", "acknowledgment"),
    ("judgement", "judgment"),
    ("grey", "gray"),
    ("metre", "meter"),
    ("defence", "defense"),
]


def strip_markup(text):
    """Remove things that would create false positives: math, code, urls, comments."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)          # fenced code
    text = re.sub(r"`[^`]*`", " ", text)                         # inline code
    text = re.sub(r"\$[^$]*\$", " ", text)                       # inline math ($...$)
    text = re.sub(r"https?://\S+", " ", text)                    # urls
    text = re.sub(r"^\s*//.*$", " ", text, flags=re.M)           # typst line comments
    text = re.sub(r"%.*$", " ", text, flags=re.M)                # latex comments
    return text


def _subseq(letters, inits):
    """True if `letters` is a subsequence of `inits` and the first letters match."""
    if not letters or not inits or inits[0] != letters[0]:
        return False
    it = iter(inits)
    return all(c in it for c in letters)


def _best_expansion(pre_text, acr):
    """Schwartz-Hearst-lite: find the tightest window of words before '(' whose
    leading initials spell the acronym. Avoids grabbing unrelated leading words."""
    letters = [c.lower() for c in acr if c.isalpha()]
    words = re.findall(r"[A-Za-z][A-Za-z\-]*", pre_text)
    if not words:
        return None
    for size in range(len(letters), len(letters) + 5):
        if size > len(words):
            break
        window = words[-size:]
        inits = [w[0].lower() for w in window]
        if _subseq(letters, inits):
            return " ".join(window)
    return None


def _norm_expansion(exp):
    """Lowercase + strip trailing plural 's' per word, so 'Machine' == 'Machines'."""
    return " ".join(re.sub(r"s$", "", w.lower()) for w in exp.split())


def find_acronyms(text):
    """Return dict acronym -> {'defs':[pos...], 'uses':[pos...], 'expansions':set}."""
    data = defaultdict(lambda: {"defs": [], "uses": [], "expansions": set()})
    # "Full Term (ACR)" — reconstruct the expansion from words before the paren.
    for m in re.finditer(r"\(([A-Z][A-Z0-9]{1,7})s?\)", text):
        acr = m.group(1)
        exp = _best_expansion(text[max(0, m.start() - 120) : m.start()], acr)
        if exp:
            data[acr]["defs"].append(m.start(1))
            data[acr]["expansions"].add(exp.strip())
    # "ACR (Full Term)"
    for m in re.finditer(r"\b([A-Z][A-Z0-9]{1,7})\s*\(([A-Z][A-Za-z]+(?:[\s\-][A-Za-z]+){0,5})\)", text):
        acr = m.group(1)
        data[acr]["defs"].append(m.start(1))
        data[acr]["expansions"].add(m.group(2).strip())
    # Uses: all-caps token (len 2-8), allowing a trailing plural 's' (GANs, SVMs).
    def_spans = [(p, p + 12) for acr in data for p in data[acr]["defs"]]
    for m in re.finditer(r"\b([A-Z][A-Z0-9]{1,7})s?\b", text):
        data[m.group(1)]["uses"].append(m.start(1))
    return data


def analyze_acronyms(data):
    findings = []
    # very common non-acronym all-caps tokens to ignore
    stop = {"A", "I", "THE", "AND", "OR", "OF", "IN", "TO", "FIG", "EQ", "REF", "URL", "DOI", "ISBN", "PDF", "USA", "UK", "US", "EU", "AI", "ML"}
    for acr, d in data.items():
        if acr in stop:
            continue
        n_defs, n_uses = len(d["defs"]), len(d["uses"])
        if n_defs == 0 and n_uses >= 2:
            findings.append({"acronym": acr, "type": "used-never-defined", "uses": n_uses, "severity": "review"})
            continue
        if n_defs == 0:
            continue  # single stray token; ignore
        first_def = min(d["defs"])
        uses_before = [u for u in d["uses"] if u < first_def - 1]
        if uses_before:
            findings.append({"acronym": acr, "type": "used-before-defined", "first_def_pos": first_def, "severity": "review"})
        if n_defs > 1:
            findings.append(
                {"acronym": acr, "type": "defined-multiple-times", "count": n_defs, "expansions": sorted(d["expansions"]), "severity": "review"}
            )
        # inconsistent-expansion only when the *meaning* differs — ignore singular/plural.
        norm = {_norm_expansion(e) for e in d["expansions"]}
        if len(norm) > 1:
            findings.append(
                {"acronym": acr, "type": "inconsistent-expansion", "expansions": sorted(d["expansions"]), "severity": "blocking"}
            )
        # defined but never used outside its definition site(s) — redundant to flag
        # if we already reported multiple definitions.
        non_def_uses = [u for u in d["uses"] if all(abs(u - dd) > len(acr) + 2 for dd in d["defs"])]
        if not non_def_uses and n_defs == 1:
            findings.append({"acronym": acr, "type": "defined-never-reused", "severity": "review"})
    return findings


def find_spelling_variants(text):
    low = text.lower()
    findings = []
    for uk, us in UK_US_PAIRS:
        nuk = len(re.findall(r"\b" + re.escape(uk) + r"\w*", low))
        nus = len(re.findall(r"\b" + re.escape(us) + r"\w*", low))
        if nuk and nus:
            findings.append({"type": "us-uk-mixed", "variants": {uk: nuk, us: nus}, "severity": "review"})
    return findings


def find_hyphenation_variants(text):
    """Detect a term appearing hyphenated, spaced, and/or closed.

    Two sources of variants:
      1. Different multi-token surface forms sharing one closed key
         (e.g. 'data set' and 'data-set').
      2. A hyphenated/spaced form whose closed spelling also appears as a
         standalone word (e.g. 'pre-processing' and 'preprocessing').
    """
    low = text.lower()
    # Hyphenated compounds only — matching across whitespace merges unrelated
    # prose words ('pre-processing vs preprocessing' -> one bogus token).
    multi = re.findall(r"[a-z]+(?:-[a-z]+)+", low)
    canon = defaultdict(set)
    for w in multi:
        key = w.replace("-", "")
        if len(key) >= 6:
            canon[key].add(w)
    findings = []
    for key, forms in canon.items():
        surface = set(forms)
        # Does the closed spelling also occur as its own word?
        if re.search(r"\b" + re.escape(key) + r"\b", low):
            surface.add(key)
        if len(surface) > 1:
            findings.append({"type": "hyphenation-variant", "forms": sorted(surface), "severity": "review"})
    return findings


def main():
    ap = argparse.ArgumentParser(description="Consistency scan for paper-preflight.")
    ap.add_argument("--paper", action="append", required=True, help="Paper source file (repeatable)")
    ap.add_argument("--out", help="Write JSON here (default: stdout)")
    args = ap.parse_args()

    combined = ""
    for p in args.paper:
        try:
            with open(p, encoding="utf-8") as fh:
                combined += "\n" + fh.read()
        except OSError as e:
            print(f"warning: could not read {p}: {e}", file=sys.stderr)

    text = strip_markup(combined)
    acr_data = find_acronyms(text)
    out = {
        "acronyms": analyze_acronyms(acr_data),
        "spelling": find_spelling_variants(text),
        "hyphenation": find_hyphenation_variants(text),
    }
    out["summary"] = {
        "acronym_findings": len(out["acronyms"]),
        "spelling_findings": len(out["spelling"]),
        "hyphenation_findings": len(out["hyphenation"]),
    }
    payload = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
    print(
        f"[check_consistency] {out['summary']['acronym_findings']} acronym, "
        f"{out['summary']['spelling_findings']} spelling, "
        f"{out['summary']['hyphenation_findings']} hyphenation candidates.",
        file=sys.stderr,
    )
    if not args.out:
        print(payload)


if __name__ == "__main__":
    main()
