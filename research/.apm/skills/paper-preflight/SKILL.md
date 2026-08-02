---
name: paper-preflight
description: "Pre-submission integrity check for a research paper (Typst+Hayagriva or LaTeX+BibTeX). Verifies every reference is REAL and its metadata correct (DOI, title, authors, year, venue) against Crossref/OpenAlex and Scholar/Exa; checks that in-text claims don't contradict the cited source; NEVER guesses or expands an author's name from an initial; flags orphan/unused citations; and catches inconsistent abbreviations, terminology, and spelling. Produces a findings report plus suggested edits. Use this WHENEVER the user is about to submit, is finalizing, or asks to check/verify/proofread references, citations, DOIs, bibliography, acronyms, or terminology in a paper — even if they don't say the word 'preflight'. Triggers: before I submit, pre-submission check, final check my paper, check my references, verify my citations, are my DOIs correct, did I cite this right, check my bibliography, are my references real, check abbreviations/terminology consistency, 投稿前チェック, 参考文献チェック, 引用チェック."
metadata:
  version: "0.1.0"
  last_updated: "2026-08-02"
  status: draft
  task_type: verification
---

# Paper Preflight — Pre-Submission Integrity Check

The last thing you do before submitting a paper. This is a **verification** pass, not a writing pass: the goal is to catch the mistakes that quietly damage credibility — a wrong DOI, a hallucinated author name, a citation that claims something the source never said, an acronym used before it's defined, the same concept called three different things.

This skill is deliberately standalone. It works on a bare paper directory (a `.typ` or `.tex` plus a `.bib` or Hayagriva `.yml`) and does not require any larger pipeline. It **complements** format-only citation linters (which check that every `\cite` resolves and the style is uniform) by focusing on the harder question: *is the reference true, and did we represent it faithfully?*

## Why these checks matter

AI-assisted writing (and tired human writing) fails in a few characteristic ways, and each check below targets one:

- **Hallucinated references** — a plausible-looking entry for a paper that doesn't exist. Caught by resolving every reference against an authority (Crossref/OpenAlex).
- **Corrupted metadata** — right paper, wrong year/venue/DOI, or an author's name subtly mangled. Caught by diffing your entry against the canonical record.
- **Invented author names** — the single most insidious failure. When a source lists an author as `T. John`, the initial `T.` is *all we know*. Expanding it to `Thomas John` is a fabrication unless the full name is independently verified. See the iron rule below.
- **Claim drift** — the paper says a source "found X" when it actually found "X under condition Y" or the opposite. Caught by reading the source where reachable.
- **Inconsistency** — abbreviations defined twice or used before definition, US/UK spelling mixed, the same concept named inconsistently. Caught mechanically plus a judgment pass.

## The iron rule: never invent an author's name

This is the one hard rule in the skill, because getting it wrong means printing a real person's name incorrectly.

**When a name is given only as an initial, treat the initial as the complete known information. Never expand `T. John` to `Thomas John`, `Tomoko John`, or anything else — unless you have verified the full first name from an authoritative record for *that specific paper* (the publisher page, the DOI record, the PDF byline).**

Concretely:
- If your `.bib`/`.yml` already has only an initial, and the canonical record (Crossref/OpenAlex) also has only an initial, report the name as *unverifiable-full-name* and leave it exactly as the initial. Do not "help."
- If your entry has a *full* first name but the canonical record has only an initial, flag it as **possible fabrication** — you cannot confirm the full name, so the safe correction is to reduce it to the initial (never the reverse), and tell the user to confirm from the source.
- If your entry and the canonical record disagree on a name (different spelling, different initial), flag it and show both; let the human decide.
- The same caution applies to middle initials, particles (van, de, al-), and CJK name ordering. When unsure, surface it — don't normalize silently.

The mindset: **it is always better to leave an initial as an initial than to guess a name.** A reviewer who sees `T. John` assumes brevity; a reviewer who sees a wrong full name assumes carelessness — or catches a fabrication.

## Workflow

Work through these in order. Steps 1–3 are mostly mechanical (the bundled scripts do the heavy lifting); steps 4–5 need your judgment.

### 1. Locate the inputs

Find the paper source(s) and the bibliography. Typical layouts:
- Typst: `*.typ` + a Hayagriva `*.yml` (or `*.bib`) referenced via `#bibliography(...)`.
- LaTeX: `*.tex` + `*.bib` referenced via `\bibliography{...}` or `\addbibresource{...}`.

If there are several source files (`main.typ` + chapters), collect them all — citations and abbreviations can live anywhere. If you can't tell which files matter, ask the user rather than guessing.

### 2. Verify references (run the script)

Run `scripts/verify_refs.py`. It parses the bibliography (BibTeX **and** Hayagriva YAML), extracts every in-text citation key from the source, and:
- resolves each reference against **Crossref** by DOI, or by title when there's no DOI, and diffs title / authors / year / venue;
- flags **initial-only author names** and **entry-vs-record name mismatches** (feeding the iron rule above);
- reports **orphans** (cited but missing from the bibliography) and **unused** entries (defined but never cited).

```bash
python3 scripts/verify_refs.py --bib <path-to-bib-or-yml> --paper <path.typ|.tex> [--paper <more>] --out refs.json
```

It writes machine-readable JSON and prints a summary. If the network is unavailable, it still does everything offline (parsing, initials, orphans/unused) and marks each external check `unverified: network unavailable` — report that honestly rather than pretending the metadata is confirmed.

For references the script couldn't resolve on Crossref (books, reports, niche venues, preprints), fall back to the project's search skills — Google Scholar (`gs-*`) or Exa — to confirm the work exists and grab canonical metadata. Record what you found and how confident you are.

### 3. Check consistency (run the script)

Run `scripts/check_consistency.py` on the source(s). It surfaces the mechanical inconsistencies:
- acronyms **used before defined**, **defined more than once**, **defined but never reused**, or **used but never defined**;
- **spelling variants** co-occurring (US/UK, e.g. *behavior/behaviour*; *modeling/modelling*);
- **hyphenation / spacing variants** of the same term (*pre-processing / preprocessing*, *data set / dataset*).

```bash
python3 scripts/check_consistency.py --paper <path.typ|.tex> [--paper <more>] --out consistency.json
```

The script finds *candidates*. Not every co-occurrence is an error (a paper may legitimately quote UK spelling in a title). Use judgment when you promote a candidate to a finding.

### 4. Claim fidelity (your judgment)

For the paper's most load-bearing citations — the ones supporting a central argument, a surprising number, or a "prior work showed X" claim — check that the source actually says what the paper attributes to it. This is best-effort by design:
- Where the source text is reachable (open-access PDF, abstract, publisher HTML), read the relevant part and compare.
- Where it isn't reachable, **do not guess**. Mark the claim `unverifiable — needs human read` and move on. A confident-looking but unverified fidelity check is worse than an honest gap.
- Prioritize: you don't need to verify "[5] is a well-known method." You do need to verify "[5] reported a 40% improvement." Numbers, comparisons, and causal claims are where drift hides.

### 5. Compile the report and suggested edits

Merge the script outputs and your judgment into one report (format below), then prepare concrete suggested edits for the fixable items. Present edits as a reviewable list — the user accepts or rejects each; do not silently rewrite the paper. For anything touching an author name, default to the *safe* direction (reduce to initial, never invent) and say so.

## Report structure

Use this template. Lead with a one-line verdict and counts so the user can triage at a glance, then group findings by severity.

```markdown
# Paper Preflight Report — <paper name>

**Verdict:** <ready to submit | N blocking issues | N issues to review>
Refs checked: <n> · Verified: <n> · Unverifiable: <n> · Consistency findings: <n>

## 🔴 Blocking (fix before submitting)
- **[<citekey>] <one-line issue>** — <what's wrong> · <location> · **Fix:** <suggested edit>

## 🟡 Review (likely issues, needs your call)
- ...

## ⚪ Unverifiable (needs a human)
- **[<citekey>] full author name not confirmable** — record shows only `T. John`; left as-is per no-guess rule. Confirm from the source PDF if you want the full name.
- **[<citekey>] claim not verified** — source text not reachable; please confirm "<the claim>".

## Suggested edits
<numbered list of concrete before→after edits the user can accept/reject>
```

Severity guide: **Blocking** = wrong/fabricated metadata, hallucinated reference, orphan citation, name that looks invented. **Review** = probable inconsistency, low-confidence metadata match, unused entry. **Unverifiable** = honestly could not confirm; hand back to the human.

## Bundled resources

- `scripts/verify_refs.py` — bibliography parsing, Crossref/DOI verification, initial detection, orphan/unused. Run it; don't reimplement it.
- `scripts/check_consistency.py` — acronym, spelling, and hyphenation consistency scan.
- `references/formats.md` — parsing notes and gotchas for BibTeX, Hayagriva YAML, and citation syntax in `.typ` vs `.tex`. Read it if a source file uses an unusual citation style and the script misses citations.
