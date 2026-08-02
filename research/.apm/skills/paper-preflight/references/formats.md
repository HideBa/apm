# Format notes — parsing bibliographies and citations

Read this only if `verify_refs.py` seems to miss citations or misparse an entry.

## Citation syntax the extractor handles

| Source | Patterns recognized |
|--------|---------------------|
| Typst  | `@key`, `#cite(<key>)`, `#cite(label: <key>)` |
| LaTeX  | `\cite{}`, `\citep{}`, `\citet{}`, `\parencite{}`, `\autocite{}`, `\textcite{}`, `\footcite{}` and other `\...cite...{}` forms, including optional `[pre][post]` args and comma-separated keys |

If a project uses a custom citation macro (e.g. `\mycite{}`), the extractor may miss it. Note the macro and either add it to the regex in `extract_citations` or count those citations manually.

Typst gotcha: `@key` also appears in code and email addresses. The extractor ignores `@` preceded by a word char, which removes most false positives, but skim the orphan list — a stray `@something` from prose can show up.

## BibTeX

- The parser matches balanced braces, so nested `{...}` in titles is fine.
- Values in `"..."` or `{...}` or bare (numbers/macros) are all handled.
- `@string` macros are **not** expanded. If a `.bib` relies heavily on string macros for journal names, venue diffs may be noisy — verify those by eye.
- Multiple authors are separated by ` and ` (BibTeX convention). `Last, First and Last, First`.

## Hayagriva YAML (Typst's native format)

Typical entry:
```yaml
smith2020:
  type: article
  title: A Study of Things
  author:
    - given-name: T.
      name: Smith
    - Doe, Jane
  date: 2020
  parent:
    type: periodical
    title: Journal of Things
  serial-number:
    doi: 10.1234/abcd
```

- `author` may be a string, a `Family, Given` string, or a mapping with `given-name`/`name`.
- `date` may be a full date or just a year; the parser extracts the first 4-digit year.
- DOI can live under `serial-number.doi` or a top-level `doi`.
- If PyYAML isn't installed, a minimal fallback parser runs — it covers flat scalar fields but not nested author mappings well. Install PyYAML (`pip install pyyaml`) for reliable Hayagriva parsing, or convert to `.bib`.

## When Crossref can't resolve an entry

Books, technical reports, standards, theses, and some preprints aren't in Crossref (or are under a different DOI). `verify_refs.py` marks these `not-found`. Fall back to:
- Google Scholar via the `gs-*` skills, or Exa search, to confirm the work exists and grab metadata.
- The publisher/repository page for the canonical author list (critical for the no-guess author rule).

Record the source you used and your confidence so the report is auditable.
