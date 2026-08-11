# Author Literature Map — method

An author map is only as good as its **author identity**. This document is the
method the toolkit assumes; the scripts implement the machine-checkable parts of
it. The identity-disambiguation engine that produces the input buckets is *not*
part of this toolkit — see "The two-pass shape" for what it must give you.

## Why identity is the hard part

A single bibliographic author id is not trustworthy on its own: databases split
one person across several ids (drift/split), and they lag on the newest year —
an "exact author" query can return 0 papers for the current year while PubMed
already indexes several. So the reliable shape is two passes with a human in the
middle:

1. **Identity pass** — gather candidate author ids and, for each, observable
   evidence: overlap with a seed set of the author's known DOIs (the strongest
   signal), affiliation hits, topic hits, and same-name-in-another-field signals.
2. **Human correction gate** — a person confirms which ids are the same person.
3. **Full pass** — pull all works under the confirmed ids and split them into
   three buckets: mainline (confirmed), needs-review, excluded/same-name.

This toolkit owns steps around the gate and the rendering; you supply the buckets.

## The correction gate is mandatory and human

Never let a machine decide which author ids are "the same person." Present the
candidates + their evidence to a human and have them write a `profile.yaml`:

```yaml
name: "Jane Doe"
profile_status: confirmed          # anything else must block a "confirmed" build
target_scope: "colorectal cancer screening / GI endoscopy"
accepted_openalex_author_ids:
  - A5000000001
  - A5000000002
accepted_orcids: []
strong_venues: [Endoscopy, Gut, Gastroenterology]
include_keywords: [colonoscopy, endoscopy, colorectal, polyp, adenoma]
exclude_keywords: []               # see the pitfall below — usually empty
homonym_risk: "low: single dominant author id, clear seed-DOI overlap"
notes: "confirmed 2026-01-01"
```

`assert_profile_confirmed.py` enforces this in code: it exits non-zero unless
`profile_status: confirmed` and `accepted_openalex_author_ids` is non-empty, so a
pipeline cannot build a confirmed map from an unreviewed profile. It accepts both
this flat schema and a nested `authors: [ {...} ]` form.

Gating uses **observable attributes only** (seed-DOI overlap, affiliation, topic,
venue). A common surname with a single initial is ambiguous — never match it on
the initial alone.

## Pitfall: `exclude_keywords` is a same-name splitter, not a topic filter

`exclude_keywords` drops any record whose title/venue/abstract text matches — so
it is only meaningful when a *real* different person shares the name in another
field and you want to cut that person's papers out. If the identity is a clean
single author id with no real homonym, **leave it empty**. Otherwise generic
technical words (`engineering`, `physics`, `chemistry`, `materials`) will wrongly
delete the author's own methods/AI papers.

Diagnostic: if your excluded bucket resolves to only one author id, it isn't
splitting a same-name person — the exclusions are pure false deletions. Clear
`exclude_keywords` and rebuild. Inclusion should come from the accepted author
ids + include_keywords, not from generic-domain exclusion.

## Display / provenance rules (enforced by the renderer)

- **One ledger is the single source of truth.** `AUTHOR_MAP.json` computes every
  count once — the metric cards, the year histogram, and the paper table all
  derive from the same `works` list, so they always reconcile.
- **Every rendered work carries a visible source label** (venue / DOI / PMID). A
  row with no verifiable source is dropped from the mainline into an audit count,
  never shown as an unlabelled first-screen claim.
- **Mainline only on the first screen.** Needs-review, excluded/same-name, and
  unlabelled-dropped are surfaced as audit *counts*, not rendered as content.
- **STALE on drift.** The ledger stores a SHA256 per input file; re-rendering
  after any input changes shows a visible STALE banner. Regenerate the ledger to
  clear it.

## Multi-source supplements

The base map comes from your works CSV. Additional online sources are optional
*supplement legs*, each writing one `<name>_supplement.csv` into the run dir. The
ledger folds all `*_supplement.csv` in and de-duplicates across sources by
DOI/PMID (base first, then each supplement), so a paper surfaced by two sources
is counted once.

- **PubMed** (`pubmed_author_supplement.py`) — `"<FAU>"[FAU] AND <year>[dp]` per
  year via public NCBI E-utilities; catches years the base source lags on. Name-
  anchored, so its rows default to the mainline; a capped year is reported as
  `truncated_years` rather than silently trimmed.
- **Semantic Scholar** (`s2_author_supplement.py`) — venue-only journals and
  citation counts the base source may miss. **Identity discipline:** with a
  confirmed `--s2-author-id` the rows are mainline; a bare name search cannot be
  trusted (a homonym would poison the map), so those rows are written
  `route=review` and the ledger routes them to human review, never the mainline.

## Sources this method uses

Batch data from open scholarly APIs (OpenAlex as the backbone in the two-pass
engine; PubMed and Semantic Scholar as supplement legs) plus, optionally, a local
reference library as an identity seed. It deliberately does not scrape closed
mirrors, and treats general web search only as a low-frequency identity anchor,
not as a batch source.
