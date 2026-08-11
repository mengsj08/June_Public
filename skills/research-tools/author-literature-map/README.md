# Author Literature Map

Build a per-author literature map whose every claim traces to a verifiable
record. The hard part of an author map is **author identity** — bibliographic
databases split one person across several IDs and lag on the newest year — so
this toolkit treats identity as a human-gated step and makes every count
machine-verifiable.

It renders one static HTML map from a single JSON ledger (`AUTHOR_MAP.json`), so
the metric cards, the year histogram, and the paper table can never disagree,
and it flags the map **STALE** when the underlying evidence changes.

> This is the **open, self-contained** toolkit: the ledger + renderer + the
> pluggable source-supplement legs (PubMed, Semantic Scholar) + the identity
> gate. **You bring your own confirmed author-id list and a works CSV** (e.g. an
> OpenAlex export) — see *Bring your own author list* below. The two-pass
> identity-disambiguation engine that produces those buckets is not included.

## Why this design

- **Identity is human-gated, not auto-decided.** A gate script refuses to build
  a "confirmed" map until a human has signed off on which author IDs are one
  person. A same-name author in another field would otherwise poison the map.
- **One ledger, one source of truth.** Every count is computed once in
  `AUTHOR_MAP.json`; the HTML is a pure projection. No double-counting, no
  drift between the headline number and the breakdown.
- **Provenance you can re-check.** The ledger records a SHA256 for every input
  file. Re-render after the evidence changes and the page shows a STALE banner.
- **Pluggable multi-source, de-duplicated.** Beyond your base works CSV, drop in
  `*_supplement.csv` legs (PubMed year-drift catch, Semantic Scholar). They fold
  in automatically and de-duplicate across sources by DOI/PMID. Identity-unsafe
  rows (e.g. a bare name search) route to human review, never the mainline.

## Quickstart (30 seconds, no network)

```bash
cd author-literature-map
# Build the ledger from the bundled example, then render the HTML map:
python3 scripts/build_author_map_verdict.py --run-dir example --author "Jane Doe (example)"
python3 scripts/render_author_map.py       --run-dir example --author "Jane Doe (example)"
open example/index.html    # or: xdg-open / start
```

You'll get a static map of 5 example works with a source label on every row,
a year histogram, and audit counts for the review / excluded buckets.

## Requirements

- Python 3.9+ (standard library only). `PyYAML` is optional — used to read a
  `profile.yaml` for the identity gate; everything else runs without it.
- Network only for the optional online supplement legs (PubMed / Semantic
  Scholar). The ledger + renderer are fully offline.

## Bring your own author list

This toolkit renders and verifies a map; it does **not** disambiguate identity
for you. The expected input is a **run directory** containing at least a
main-map CSV of the author's confirmed works, named one of:

- `works_included_main_map.csv`, or
- any `*_high_confidence_missing.csv` / `*_main_map.csv`

Minimum columns the renderer understands (extra columns are ignored):

| column | meaning |
|---|---|
| `title` | paper title |
| `year` | publication year |
| `doi` and/or `pmid` | provenance id (a row with no `doi`/`pmid`/`venue` is dropped to an audit count, never rendered as an unlabelled claim) |
| `venue` | journal / source (optional but recommended) |
| `theme` | optional grouping label |

Optional sibling CSVs surface as audit counts: `works_review_candidates.csv`
(needs human review) and `works_excluded_homonym_candidates.csv` (same-name /
excluded). How you produce these buckets is up to you — an OpenAlex works
export filtered to your confirmed author IDs is a common starting point.

## Add online source supplements (optional)

Each online source emits one `<name>_supplement.csv` into the run directory; the
ledger folds all `*_supplement.csv` in and de-duplicates across sources.

```bash
# PubMed year-drift catch (public NCBI E-utilities; --api-key optional):
python3 scripts/pubmed_author_supplement.py \
  --fau "Doe Jane" --years 2023-2026 \
  --openalex-csv example/works_included_main_map.csv --out example

# Semantic Scholar (anchored id -> mainline; bare name search -> routed to review):
python3 scripts/s2_author_supplement.py \
  --author "Jane Doe" --s2-author-id <confirmed S2 author id> \
  --openalex-csv example/works_included_main_map.csv --out example

# Rebuild the ledger + re-render (supplements fold in automatically):
python3 scripts/build_author_map_verdict.py --run-dir example --author "Jane Doe"
python3 scripts/render_author_map.py       --run-dir example --author "Jane Doe"
```

Both legs degrade gracefully: if the API rate-limits or the network fails, they
write what they have and exit 0 — the map still builds.

## Identity gate (optional but recommended)

If you keep a `profile.yaml` describing the confirmed author, the gate refuses to
treat a map as confirmed until it says so:

```yaml
name: "Jane Doe"
profile_status: confirmed          # anything else blocks the "confirmed" build
accepted_openalex_author_ids:
  - A5000000001
homonym_risk: "low: single dominant author id, clear DOI overlap"
```

```bash
python3 scripts/assert_profile_confirmed.py --profile profile.yaml && echo "gate passed"
```

## Files

| path | what it does |
|---|---|
| `scripts/build_author_map_verdict.py` | builds `AUTHOR_MAP.json` — the single source of every count, with per-source breakdown + input SHA256s |
| `scripts/render_author_map.py` | renders one static `index.html` purely from the ledger; STALE banner on evidence drift |
| `scripts/pubmed_author_supplement.py` | PubMed `[FAU] AND [dp]` year supplement (public E-utilities) |
| `scripts/s2_author_supplement.py` | Semantic Scholar author supplement (anchored → mainline, name-search → review) |
| `scripts/assert_profile_confirmed.py` | identity-gate precondition (exit non-zero unless the profile is confirmed) |
| `scripts/build_researcher_profile.py` | optional plain-text researcher profile summary from the run |
| `references/method.md` | the full method: two-pass identity discipline, the gate, display rules |
| `example/` | a synthetic run you can build + render immediately |

## License

MIT — see `LICENSE`.
