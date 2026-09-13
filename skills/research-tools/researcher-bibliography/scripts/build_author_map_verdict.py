#!/usr/bin/env python3
"""Build AUTHOR_MAP.json — the single machine-verifiable source for one author map.

Why this exists
---------------
The map used to be computed twice: the metric cards counted the main-map rows
while the year/theme bars were read from separate `*_manifest.csv` files. When a
PubMed supplement was folded in, the two paths diverged and the page numbers no
longer reconciled. This script computes every count ONCE from the actual work
rows and writes one JSON artifact; the renderer then only draws from that JSON,
so the numbers can never disagree.

It is also the provenance anchor: it records a SHA256 for every input CSV it
read, so a later render (or an external check) can detect that the underlying
evidence changed and flag the map STALE.

Fully parameter-driven — nothing about any specific author is baked in. It runs
on whatever `--run-dir` / `--author` you pass, and writes into that run only.

Read-only over inputs; writes one JSON file (default: <run-dir>/AUTHOR_MAP.json).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml  # optional; profile.yaml parsing degrades gracefully without it
except Exception:  # pragma: no cover
    yaml = None

SCHEMA_VERSION = "1"

MAIN_CSV_CANDIDATES = ["works_included_main_map.csv", "works_main_map.csv"]
MAIN_CSV_SUFFIXES = ["_high_confidence_missing.csv", "_main_map.csv"]
REVIEW_EXACT = "works_review_candidates.csv"
REVIEW_SUFFIX = "_needs_human_review.csv"
EXCLUDED_EXACT = "works_excluded_homonym_candidates.csv"
EXCLUDED_SUFFIX = "_excluded_or_homonym_suspect.csv"


# ---------- shared parsing helpers (imported by render_author_map.py) ----------

def find_csv(run_dir: Path, exact: list[str], suffixes: list[str]) -> Path | None:
    for name in exact:
        p = run_dir / name
        if p.exists():
            return p
    for p in sorted(run_dir.glob("*.csv")):
        if any(p.name.endswith(s) for s in suffixes):
            return p
    return None


def read_rows(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def col(row: dict, *names: str) -> str:
    low = {k.lower(): k for k in row}
    for n in names:
        k = low.get(n.lower())
        if k and row.get(k):
            return str(row[k]).strip()
    return ""


def source_label(row: dict) -> str:
    doi = col(row, "doi")
    pmid = col(row, "pmid")
    # NB: do not alias "source" here — the PubMed supplement CSV has a literal
    # `source` column holding the provenance marker ("pubmed_supplement"), which
    # would be mis-read as a venue. All real bucket CSVs name the venue "venue".
    venue = col(row, "venue", "journal")
    parts = []
    if venue:
        parts.append(venue)
    if doi:
        parts.append(f"DOI {doi}")
    elif pmid:
        parts.append(f"PMID {pmid}")
    return " · ".join(parts) if parts else ""


def work_url(row: dict) -> str:
    doi = col(row, "doi")
    if doi:
        return f"https://doi.org/{doi}"
    return col(row, "pubmed_url", "url", "openalex_url")


def safe_int(value: str) -> int | None:
    try:
        return int(str(value).strip()[:4])
    except (ValueError, TypeError):
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


# ---------- profile.yaml (tolerates flat AND nested `authors:` schemas) --------

def load_profile(path: Path | None) -> dict | None:
    """Return a flat profile dict, or None. Handles both the flat schema
    documented in method.md and the nested `authors: [ {...} ]` schema."""
    if not path or not path.exists() or yaml is None:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "profile_status" in data or "accepted_openalex_author_ids" in data:
        return data
    authors = data.get("authors")
    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
        return authors[0]
    return None


# ---------- the one computation path -------------------------------------------

def norm_doi(value: str) -> str:
    return (value or "").strip().lower().replace("https://doi.org/", "").replace(
        "http://doi.org/", "")


def dedup_keys(row: dict) -> tuple[str, str]:
    return norm_doi(col(row, "doi")), str(col(row, "pmid")).strip()


def discover_supplements(run_dir: Path, extra: list[Path]) -> list[Path]:
    """All per-source supplement CSVs feeding this map. Any `*_supplement.csv`
    dropped in the run dir (pubmed_supplement.csv, s2_supplement.csv, …) is folded
    in automatically — that is how a new online source leg is added, mirroring
    research-lit's pluggable multi-source model. Explicit --supplement paths win."""
    found = {p.resolve(): p for p in sorted(run_dir.glob("*_supplement.csv"))}
    for p in extra:
        if p and p.exists():
            found[p.resolve()] = p
    return list(found.values())


def build_verdict(run_dir: Path, author: str, profile_path: Path | None,
                  supplements: list[Path] | None = None,
                  second_opinion_path: Path | None = None) -> dict:
    main_csv = find_csv(run_dir, MAIN_CSV_CANDIDATES, MAIN_CSV_SUFFIXES)
    if not main_csv:
        raise SystemExit(f"No main-map CSV found in {run_dir}")
    review_csv = find_csv(run_dir, [REVIEW_EXACT], [REVIEW_SUFFIX])
    excluded_csv = find_csv(run_dir, [EXCLUDED_EXACT], [EXCLUDED_SUFFIX])

    main_rows = read_rows(main_csv)
    review_rows = read_rows(review_csv)
    excluded_rows = read_rows(excluded_csv)

    supplement_files = discover_supplements(run_dir, supplements or [])

    # Every mainline row goes through ONE labelling pass, and every row is
    # cross-source de-duplicated by DOI/PMID — OpenAlex first, then each
    # supplement in turn, so a paper already covered upstream is never
    # double-counted regardless of which source surfaced it (research-lit's
    # dedup discipline). Rows with no verifiable source (no DOI / PMID / venue)
    # are dropped from the mainline and counted as an audit pointer — never
    # rendered on the first screen as an unlabelled claim.
    works: list[dict] = []
    unlabeled = 0
    seen: set[str] = set()
    review_routed = 0  # supplement rows an unconfirmed identity can't put on the mainline
    by_source: Counter = Counter()

    def mark_seen(row: dict) -> bool:
        """Register a row's identity keys; return True if it was already seen."""
        d, p = dedup_keys(row)
        keys = [f"doi:{d}"] if d else []
        if p:
            keys.append(f"pmid:{p}")
        if any(k in seen for k in keys):
            return True
        seen.update(keys)
        return False

    for r in main_rows:
        mark_seen(r)  # OpenAlex mainline defines the baseline seen-set
        label = source_label(r)
        if not label:
            unlabeled += 1
            continue
        works.append({
            "year": safe_int(col(r, "year")), "title": col(r, "title"),
            "url": work_url(r), "source_label": label, "theme": col(r, "theme"),
            "source": "openalex_main", "supplement": False,
        })
        by_source["openalex_main"] += 1

    for sup in supplement_files:
        stem = sup.name[:-len("_supplement.csv")] or sup.stem
        for r in read_rows(sup):
            src = col(r, "source") or f"{stem}_supplement"
            if mark_seen(r):
                continue  # already covered by OpenAlex or an earlier supplement
            label = source_label(r)
            if not label:
                unlabeled += 1
                continue
            # Identity-safe routing: a supplement row that was NOT anchored to a
            # confirmed author id (e.g. an S2 name-search hit) must not land on
            # the mainline — it goes to human review, honouring the PI gate.
            if col(r, "route").lower() == "review":
                review_routed += 1
                continue
            works.append({
                "year": safe_int(col(r, "year")), "title": col(r, "title"),
                "url": work_url(r), "source_label": label, "theme": col(r, "theme"),
                "source": src, "supplement": True,
            })
            by_source[src] += 1

    # Histograms derive from the SAME `works` list the table renders, so the
    # metric total and the bars are guaranteed to reconcile.
    yc = Counter(w["year"] for w in works if w["year"])
    year_histogram = sorted(((y, n) for y, n in yc.items()), reverse=True)
    tc = Counter(w["theme"] for w in works if w["theme"])
    theme_histogram = tc.most_common()

    years = [w["year"] for w in works if w["year"]]
    year_range = [min(years), max(years)] if years else [None, None]

    prof = load_profile(profile_path)
    if prof is None:
        profile_status = "absent"
        accepted_ids: list[str] = []
        homonym_risk = ""
    else:
        profile_status = str(prof.get("profile_status") or "unconfirmed")
        accepted_ids = list(prof.get("accepted_openalex_author_ids") or [])
        homonym_risk = str(prof.get("homonym_risk") or "")

    # Fall back to the full-pass summary for accepted IDs when no profile is
    # co-located (a finished full run records its confirmed split ids there).
    summary = {}
    sp = next(iter(run_dir.glob("*summary*.json")), None)
    if sp:
        try:
            summary = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            summary = {}
    if not accepted_ids:
        accepted_ids = list(summary.get("main_openalex_split_ids") or [])

    # Cross-model identity second opinion (method.md "Pass 1.5"): auto-discover the
    # co-located file if not passed. It reaches the ledger as a hashed pointer, not
    # a re-computed verdict — advisory evidence the PI weighed, made machine-visible.
    so_path = second_opinion_path
    if so_path is None:
        cand = run_dir / "identity_second_opinion.md"
        so_path = cand if cand.exists() else None
    second_opinion = None
    if so_path and so_path.exists():
        second_opinion = {"present": True, "path": so_path.name,
                          "sha256": sha256_file(so_path)}

    # Hash-key convention: files INSIDE the run dir key on their name relative to
    # it; files OUTSIDE (e.g. a profile.yaml kept in the run's parent) key on their
    # absolute path. stale_inputs() resolves each key the same way, so an input that
    # lives outside the run dir is no longer mis-resolved to run_dir/<name> and
    # falsely flagged STALE.
    run_resolved = run_dir.resolve()

    def hash_key(p: Path) -> str:
        rp = p.resolve()
        try:
            return str(rp.relative_to(run_resolved))
        except ValueError:
            return str(rp)

    input_hashes: dict[str, str] = {}
    for p in [main_csv, review_csv, excluded_csv, profile_path, so_path] + supplement_files:
        if p and p.exists():
            input_hashes[hash_key(p)] = sha256_file(p)

    supplement_total = sum(n for s, n in by_source.items() if s != "openalex_main")

    return {
        "skill": "author-literature-map",
        "schema_version": SCHEMA_VERSION,
        "author": author,
        "run_dir": str(run_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile_status": profile_status,
        "accepted_openalex_author_ids": accepted_ids,
        "homonym_risk": homonym_risk,
        "verdict": "OK",
        "sources": sorted(by_source),
        "counts": {
            "main": len(works),
            "review": len(review_rows) + review_routed,
            "excluded": len(excluded_rows),
            "supplement": supplement_total,
            "unlabeled_dropped": unlabeled,
            "review_routed_from_supplements": review_routed,
            "by_source": dict(by_source),
        },
        "year_range": year_range,
        "year_histogram": year_histogram,
        "theme_histogram": theme_histogram,
        "input_hashes": input_hashes,
        "second_opinion": second_opinion,  # cross-model identity opinion (method.md Pass 1.5)
        "works": works,
    }


def stale_inputs(verdict: dict) -> list[str]:
    """Return the list of input files whose current SHA256 no longer matches the
    hash recorded in the verdict — i.e. the evidence changed since it was built."""
    run_dir = Path(verdict.get("run_dir", "."))
    drifted = []
    for name, recorded in (verdict.get("input_hashes") or {}).items():
        p = Path(name) if Path(name).is_absolute() else run_dir / name
        if not p.exists() or sha256_file(p) != recorded:
            drifted.append(name)
    return drifted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True, help="Full-pass output directory")
    ap.add_argument("--author", required=True, help="Author display name")
    ap.add_argument("--profile", type=Path, default=None, help="Optional profile.yaml")
    ap.add_argument("--supplement", type=Path, action="append", default=[],
                    help="Extra per-source supplement CSV (repeatable). Any "
                         "*_supplement.csv in the run dir is folded in automatically.")
    ap.add_argument("--pubmed-supplement", type=Path, default=None,
                    help="Back-compat alias for --supplement")
    ap.add_argument("--second-opinion", type=Path, default=None,
                    help="identity_second_opinion.md (auto-discovered in run dir if omitted)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output JSON (default: <run-dir>/AUTHOR_MAP.json)")
    args = ap.parse_args(argv)

    extra = list(args.supplement)
    if args.pubmed_supplement:
        extra.append(args.pubmed_supplement)
    verdict = build_verdict(args.run_dir, args.author, args.profile, extra, args.second_opinion)
    out = args.out or (args.run_dir / "AUTHOR_MAP.json")
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    c = verdict["counts"]
    print(f"AUTHOR_MAP.json -> {out}")
    print(f"  main {c['main']} · review {c['review']} · excluded {c['excluded']} "
          f"· supplement {c['supplement']} · unlabeled-dropped {c['unlabeled_dropped']}")
    print(f"  sources: {verdict['sources']}  by_source={c['by_source']}")
    print(f"  year range {verdict['year_range']} · profile {verdict['profile_status']} "
          f"· {len(verdict['input_hashes'])} inputs hashed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
