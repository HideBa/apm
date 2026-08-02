#!/usr/bin/env python3
"""verify_refs.py — reference integrity checks for paper-preflight.

Parses a bibliography (BibTeX .bib OR Hayagriva .yml), extracts in-text citation
keys from the paper source(s), verifies each reference's metadata against Crossref,
and reports:
  - metadata diffs (title / authors / year / venue) vs the canonical record
  - initial-only author names and entry-vs-record name mismatches (the no-guess rule)
  - orphan citations (cited but not in the bibliography)
  - unused entries (in the bibliography but never cited)

Network is optional: without it, parsing / initials / orphan / unused still run and
each external check is marked {"unverified": "network unavailable"}.

Usage:
  python3 verify_refs.py --bib refs.bib --paper main.typ [--paper ch1.typ] --out refs.json
  python3 verify_refs.py --bib refs.yml --paper main.tex --no-network

Stdlib only. YAML support uses PyYAML if present; otherwise Hayagriva files fall
back to a minimal parser that covers the common flat cases.
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

CROSSREF = "https://api.crossref.org/works"
TIMEOUT = 12


# --------------------------------------------------------------------------- #
# Bibliography parsing
# --------------------------------------------------------------------------- #
def parse_bibtex(text):
    """Return list of dicts: {key, type, fields{...}} from BibTeX text."""
    entries = []
    # Find @type{key, ... } blocks by matching balanced braces.
    i = 0
    for m in re.finditer(r"@(\w+)\s*\{", text):
        etype = m.group(1).lower()
        if etype in ("comment", "string", "preamble"):
            continue
        start = m.end()
        depth = 1
        j = start
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[start : j - 1]
        # first comma separates key from fields
        comma = body.find(",")
        if comma == -1:
            continue
        key = body[:comma].strip()
        fields = _parse_bibtex_fields(body[comma + 1 :])
        entries.append({"key": key, "type": etype, "fields": fields})
    return entries


def _parse_bibtex_fields(s):
    fields = {}
    pos = 0
    while pos < len(s):
        eqm = re.search(r"(\w[\w\-]*)\s*=\s*", s[pos:])
        if not eqm:
            break
        name = eqm.group(1).lower()
        vstart = pos + eqm.end()
        if vstart >= len(s):
            break
        ch = s[vstart]
        if ch == "{":
            depth = 1
            k = vstart + 1
            while k < len(s) and depth:
                if s[k] == "{":
                    depth += 1
                elif s[k] == "}":
                    depth -= 1
                k += 1
            val = s[vstart + 1 : k - 1]
            pos = k
        elif ch == '"':
            k = vstart + 1
            while k < len(s) and s[k] != '"':
                k += 1
            val = s[vstart + 1 : k]
            pos = k + 1
        else:  # bare value (number or macro) up to comma
            k = vstart
            while k < len(s) and s[k] not in ",\n":
                k += 1
            val = s[vstart:k]
            pos = k
        fields[name] = _clean(val)
        nextc = s.find(",", pos)
        pos = nextc + 1 if nextc != -1 else len(s)
    return fields


def _clean(v):
    v = re.sub(r"\s+", " ", v).strip()
    v = v.replace("{", "").replace("}", "").replace("\\&", "&")
    return v.strip()


def parse_hayagriva(text):
    """Return list of {key, type, fields{...}} from a Hayagriva YAML file."""
    data = None
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except Exception:
        data = _mini_yaml(text)
    entries = []
    if not isinstance(data, dict):
        return entries
    for key, body in data.items():
        if not isinstance(body, dict):
            continue
        fields = {}
        fields["title"] = _hstr(body.get("title"))
        fields["year"] = _hyear(body.get("date"))
        # authors
        auth = body.get("author")
        fields["author"] = _hauthors(auth)
        # venue / journal / parent title
        parent = body.get("parent")
        if isinstance(parent, dict):
            fields["journal"] = _hstr(parent.get("title"))
        elif isinstance(parent, list) and parent:
            fields["journal"] = _hstr(parent[0].get("title") if isinstance(parent[0], dict) else None)
        for dk in ("doi", "serial-number"):
            v = body.get(dk)
            if isinstance(v, dict):
                v = v.get("doi")
            if v:
                fields["doi"] = str(v)
                break
        entries.append({"key": str(key), "type": str(body.get("type", "")).lower(), "fields": {k: v for k, v in fields.items() if v}})
    return entries


def _hstr(v):
    if isinstance(v, dict):
        return str(v.get("value", "")).strip()
    return str(v).strip() if v is not None else ""


def _hyear(v):
    if v is None:
        return ""
    m = re.search(r"\d{4}", str(v))
    return m.group(0) if m else ""


def _hauthors(a):
    if a is None:
        return ""
    if isinstance(a, str):
        return a
    if isinstance(a, dict):
        return _name_from_dict(a)
    if isinstance(a, list):
        return " and ".join(_name_from_dict(x) if isinstance(x, dict) else str(x) for x in a)
    return str(a)


def _name_from_dict(d):
    given = d.get("given-name") or d.get("given") or ""
    family = d.get("name") or d.get("family-name") or d.get("family") or ""
    if family and given:
        return f"{family}, {given}"
    return family or given or str(d)


def _mini_yaml(text):
    """Indentation-aware fallback YAML parser for the Hayagriva subset.

    Handles nested mappings, lists of scalars, and lists of mappings — enough to
    parse author lists (`- given-name:` / `name:` or `- Family, Given`), `parent`,
    and `serial-number`. Not a full YAML implementation, but covers real .yml bibs
    when PyYAML isn't installed.
    """
    lines = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))

    def unquote(v):
        v = v.strip()
        if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
            return v[1:-1]
        return v

    def parse_block(idx, min_indent):
        """Return (value, next_idx). Value is dict, list, or scalar-map."""
        # Peek: is this a list block (starts with '- ') or a mapping block?
        if idx >= len(lines):
            return {}, idx
        indent0, content0 = lines[idx]
        if content0.startswith("- "):
            result = []
            while idx < len(lines):
                indent, content = lines[idx]
                if indent < min_indent or not content.startswith("- "):
                    break
                item = content[2:].strip()
                if ":" in item and not _looks_like_name(item):
                    # inline first key of a mapping list item
                    sub = {}
                    k, _, v = item.partition(":")
                    if v.strip():
                        sub[k.strip()] = unquote(v)
                    idx += 1
                    # consume deeper lines belonging to this item
                    while idx < len(lines) and lines[idx][0] > indent:
                        ci, cc = lines[idx]
                        kk, _, vv = cc.partition(":")
                        if vv.strip():
                            sub[kk.strip()] = unquote(vv)
                        idx += 1
                    result.append(sub)
                else:
                    result.append(unquote(item))
                    idx += 1
            return result, idx
        # mapping block
        result = {}
        while idx < len(lines):
            indent, content = lines[idx]
            if indent < min_indent:
                break
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                result[key] = unquote(val)
                idx += 1
            else:
                # nested block belongs to this key
                idx += 1
                if idx < len(lines) and lines[idx][0] > indent:
                    sub, idx = parse_block(idx, lines[idx][0])
                    result[key] = sub
                else:
                    result[key] = {}
        return result, idx

    out = {}
    idx = 0
    while idx < len(lines):
        indent, content = lines[idx]
        if indent != 0:
            idx += 1
            continue
        key, _, val = content.partition(":")
        idx += 1
        if idx < len(lines) and lines[idx][0] > 0:
            sub, idx = parse_block(idx, lines[idx][0])
            out[key.strip()] = sub
        else:
            out[key.strip()] = unquote(val)
    return out


def _looks_like_name(s):
    """A list item like 'Smith, John' is a scalar name, not a mapping."""
    k = s.split(":", 1)[0]
    return " " in k or "," in s.split(":", 1)[0]


# --------------------------------------------------------------------------- #
# Author-name analysis (the no-guess rule)
# --------------------------------------------------------------------------- #
def split_authors(raw):
    if not raw:
        return []
    parts = re.split(r"\s+and\s+|;\s*", raw)
    return [p.strip() for p in parts if p.strip()]


def given_family(author):
    """Return (given, family) best-effort from one author string."""
    if "," in author:
        family, given = author.split(",", 1)
        return given.strip(), family.strip()
    toks = author.split()
    if len(toks) == 1:
        return "", toks[0]
    return " ".join(toks[:-1]), toks[-1]


def is_initial_only(given):
    """True if the given-name portion is only initials, e.g. 'T.' or 'T. J.'"""
    g = given.strip()
    if not g:
        return False
    return bool(re.fullmatch(r"(?:[A-Z]\.?\s*){1,3}", g))


# --------------------------------------------------------------------------- #
# Crossref verification
# --------------------------------------------------------------------------- #
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "paper-preflight/0.1 (mailto:preflight@example.org)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def crossref_by_doi(doi):
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    return _get(f"{CROSSREF}/{urllib.parse.quote(doi)}").get("message")


def crossref_by_title(title):
    q = urllib.parse.urlencode({"query.bibliographic": title, "rows": 3})
    items = _get(f"{CROSSREF}?{q}").get("message", {}).get("items", [])
    return items


def _cr_title(msg):
    t = msg.get("title") or []
    return t[0] if t else ""


def _cr_year(msg):
    for k in ("published-print", "published-online", "issued", "created"):
        dp = (msg.get(k) or {}).get("date-parts")
        if dp and dp[0]:
            return str(dp[0][0])
    return ""


def _cr_venue(msg):
    for k in ("container-title", "short-container-title"):
        v = msg.get(k) or []
        if v:
            return v[0]
    return ""


def _cr_authors(msg):
    out = []
    for a in msg.get("author", []) or []:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        out.append({"given": given, "family": family})
    return out


def _sim(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def verify_entry(entry, no_network):
    f = entry["fields"]
    rec = {
        "key": entry["key"],
        "title": f.get("title", ""),
        "doi": f.get("doi", ""),
        "year": f.get("year", ""),
        "issues": [],
        "author_flags": [],
    }
    # ---- author / initials analysis (offline) ----
    authors = split_authors(f.get("author", ""))
    parsed_authors = []
    for a in authors:
        g, fam = given_family(a)
        info = {"raw": a, "given": g, "family": fam, "initial_only": is_initial_only(g)}
        parsed_authors.append(info)
        if info["initial_only"]:
            rec["author_flags"].append(
                {"family": fam, "given": g, "flag": "initial-only", "note": "Given name is an initial; do NOT expand unless verified."}
            )
    rec["authors_parsed"] = parsed_authors

    if no_network:
        rec["metadata_status"] = "unverified: network disabled"
        return rec

    # ---- external verification ----
    msg = None
    doi_error = None
    # 1) Try DOI. A 404 here is a signal (wrong or fabricated DOI), not a fatal
    #    error — fall through to a title search so we can still judge the entry.
    if f.get("doi"):
        try:
            msg = crossref_by_doi(f["doi"])
            rec["resolved_by"] = "doi"
        except Exception as e:
            doi_error = type(e).__name__
            rec["doi_lookup"] = f"failed: {doi_error} (DOI did not resolve on Crossref)"
    # 2) Title fallback (also runs when the DOI 404'd).
    if msg is None and f.get("title"):
        try:
            cands = crossref_by_title(f["title"])
            if cands:
                best = max(cands, key=lambda c: _sim(f["title"], _cr_title(c)))
                if _sim(f["title"], _cr_title(best)) >= 0.72:
                    msg = best
                    rec["resolved_by"] = "title"
                    rec["title_match_score"] = round(_sim(f["title"], _cr_title(best)), 3)
        except Exception as e:
            if doi_error is None:  # only network-block the title path if DOI didn't already run
                rec["metadata_status"] = f"unverified: {type(e).__name__}"
                return rec

    if msg is None:
        if doi_error:
            rec["metadata_status"] = (
                "SUSPECT: DOI did not resolve AND no title match on Crossref — "
                "verify this reference exists (possible hallucination); check via Scholar/Exa."
            )
            rec["issues"].append({"field": "existence", "yours": f.get("doi", ""), "record": "no match", "severity": "blocking"})
        else:
            rec["metadata_status"] = "not-found: no Crossref match (try Scholar/Exa; may be a book/report/preprint)"
        return rec

    rec["metadata_status"] = "resolved"
    rec["crossref_doi"] = msg.get("DOI", "")
    # title
    ct = _cr_title(msg)
    if ct and f.get("title") and _sim(f["title"], ct) < 0.9:
        rec["issues"].append({"field": "title", "yours": f["title"], "record": ct, "severity": "review"})
    # year
    cy = _cr_year(msg)
    if cy and f.get("year") and cy != re.sub(r"\D", "", f["year"])[:4]:
        rec["issues"].append({"field": "year", "yours": f.get("year"), "record": cy, "severity": "blocking"})
    # venue
    cv = _cr_venue(msg)
    if cv and f.get("journal") and _sim(f["journal"], cv) < 0.8:
        rec["issues"].append({"field": "venue", "yours": f.get("journal"), "record": cv, "severity": "review"})
    # doi mismatch
    if f.get("doi") and msg.get("DOI") and re.sub(r"^https?://(dx\.)?doi\.org/", "", f["doi"], flags=re.I).lower() != msg["DOI"].lower():
        rec["issues"].append({"field": "doi", "yours": f["doi"], "record": msg["DOI"], "severity": "blocking"})
    # ---- author cross-check (no-guess rule) ----
    cr_auth = _cr_authors(msg)
    _crosscheck_authors(rec, parsed_authors, cr_auth)
    return rec


def _crosscheck_authors(rec, yours, record):
    """Compare each of your authors to the Crossref record by family name."""
    for ya in yours:
        match = None
        for ra in record:
            if ra["family"] and _sim(ya["family"], ra["family"]) >= 0.85:
                match = ra
                break
        if not match:
            continue
        rec_given = match["given"]
        rec_initial_only = is_initial_only(rec_given) or (len(rec_given.replace(".", "").strip()) <= 1)
        if not ya["initial_only"] and ya["given"] and rec_initial_only:
            # You have a full name; record only has an initial -> cannot confirm -> possible fabrication.
            rec["author_flags"].append(
                {
                    "family": ya["family"],
                    "given": ya["given"],
                    "flag": "possible-fabrication",
                    "note": f"Your entry has full given name '{ya['given']}' but Crossref shows only '{rec_given}'. Cannot verify; safe fix is to reduce to the initial.",
                    "severity": "blocking",
                }
            )
        elif ya["given"] and rec_given and not rec_initial_only and not ya["initial_only"]:
            if _sim(ya["given"], rec_given) < 0.7:
                rec["author_flags"].append(
                    {
                        "family": ya["family"],
                        "given": ya["given"],
                        "flag": "name-mismatch",
                        "note": f"Given name '{ya['given']}' vs Crossref '{rec_given}'. Confirm from source.",
                        "severity": "review",
                    }
                )


# --------------------------------------------------------------------------- #
# In-text citation extraction
# --------------------------------------------------------------------------- #
def extract_citations(text):
    keys = set()
    # Typst: @key   and  #cite(<key>) / #cite(label:...)
    for m in re.finditer(r"(?<![\w@])@([A-Za-z0-9_:.\-]+)", text):
        keys.add(m.group(1).rstrip(".,;:"))
    for m in re.finditer(r"#cite\(\s*<?([A-Za-z0-9_:.\-]+)>?", text):
        keys.add(m.group(1))
    # LaTeX: \cite{a,b}, \citep{...}, \citet{...}, \parencite{...}, \autocite{...}, \textcite{...}
    for m in re.finditer(r"\\[a-zA-Z]*cite[a-zA-Z]*\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}", text):
        for k in m.group(1).split(","):
            k = k.strip()
            if k:
                keys.add(k)
    return keys


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def load_bib(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.lower().endswith((".yml", ".yaml")) or (not path.lower().endswith(".bib") and "@" not in text[:200]):
        return parse_hayagriva(text)
    return parse_bibtex(text)


def main():
    ap = argparse.ArgumentParser(description="Reference integrity checks for paper-preflight.")
    ap.add_argument("--bib", required=True, help="Path to .bib or Hayagriva .yml")
    ap.add_argument("--paper", action="append", default=[], help="Paper source file (repeatable)")
    ap.add_argument("--out", help="Write JSON here (default: stdout)")
    ap.add_argument("--no-network", action="store_true", help="Skip Crossref; offline checks only")
    args = ap.parse_args()

    entries = load_bib(args.bib)
    bib_keys = {e["key"] for e in entries}

    cited = set()
    for p in args.paper:
        try:
            with open(p, encoding="utf-8") as fh:
                cited |= extract_citations(fh.read())
        except OSError as e:
            print(f"warning: could not read {p}: {e}", file=sys.stderr)

    orphans = sorted(cited - bib_keys) if args.paper else []
    unused = sorted(bib_keys - cited) if args.paper else []

    results = [verify_entry(e, args.no_network) for e in entries]

    summary = {
        "n_entries": len(entries),
        "n_cited": len(cited),
        "n_resolved": sum(1 for r in results if r.get("metadata_status") == "resolved"),
        "n_with_issues": sum(1 for r in results if r["issues"] or r["author_flags"]),
        "orphans": orphans,
        "unused": unused,
        "network": "disabled" if args.no_network else "enabled",
    }
    out = {"summary": summary, "references": results}
    payload = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload)
    # Always print a short human summary to stderr for the driving agent.
    print(
        f"[verify_refs] {summary['n_entries']} entries, {summary['n_cited']} cited, "
        f"{summary['n_resolved']} resolved, {summary['n_with_issues']} flagged, "
        f"{len(orphans)} orphans, {len(unused)} unused (network {summary['network']}).",
        file=sys.stderr,
    )
    if not args.out:
        print(payload)


if __name__ == "__main__":
    main()
