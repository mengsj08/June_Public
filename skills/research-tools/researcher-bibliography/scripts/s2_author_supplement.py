#!/usr/bin/env python3
"""Semantic Scholar author supplement for the author literature map.

Why this exists
---------------
OpenAlex is the backbone and PubMed catches its year-drift, but Semantic Scholar
(S2) indexes some venue-only journal papers and carries citation counts that
OpenAlex misses. This adds S2 as a third source leg, following the same contract
as pubmed_author_supplement.py: query by author, drop anything already covered by
the OpenAlex bucket (by DOI/PMID), and emit a supplement CSV the verdict builder
folds in.

Identity discipline (this is an AUTHOR map, so homonyms are the whole risk):
- With `--s2-author-id` (a confirmed S2 author id, recorded at the PI gate) the
  author's papers are enumerated and treated as mainline candidates.
- Without it, we fall back to S2 author *name search*. Name-search hits cannot be
  trusted onto the mainline — a homonym would poison the map — so every such row
  is written with `route=review`, and the verdict builder routes it to human
  review, never the first screen. This honours the PI-correction gate.

Graceful degradation (mirrors research-lit): S2's keyless endpoint rate-limits
(HTTP 429). On any network / rate-limit failure the script warns, writes an empty
supplement, and exits 0 — it never aborts the map.

Read-only over the network; only writes the supplement files under --out.
No API key required; pass --api-key for higher rate limits.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

S2_BASE = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "title,year,venue,externalIds,publicationTypes"


def norm_doi(value: str) -> str:
    return (value or "").strip().lower().replace("https://doi.org/", "").replace(
        "http://doi.org/", "")


def s2_get(path: str, params: dict, api_key: str | None, delay: float) -> dict | None:
    url = f"{S2_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("x-api-key", api_key)
    time.sleep(delay)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # 429, network, JSON — all degrade the same way
        print(f"warning: S2 request failed ({exc}) for {path}", file=sys.stderr)
        return None


def load_seen_keys(openalex_csv: Path | None) -> tuple[set[str], set[str]]:
    dois: set[str] = set()
    pmids: set[str] = set()
    if not openalex_csv or not openalex_csv.exists():
        if openalex_csv:
            print(f"warning: --openalex-csv {openalex_csv} not found, no dedup applied")
        return dois, pmids
    with openalex_csv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        dc, pc = cols.get("doi"), cols.get("pmid")
        for row in reader:
            if dc and norm_doi(row.get(dc, "")):
                dois.add(norm_doi(row.get(dc, "")))
            if pc and str(row.get(pc, "")).strip():
                pmids.add(str(row.get(pc, "")).strip())
    return dois, pmids


def resolve_author_ids(name: str, api_key: str, delay: float) -> list[str]:
    data = s2_get("/author/search", {"query": name, "fields": "name,paperCount"},
                  api_key, delay)
    if not data or not data.get("data"):
        return []
    return [a["authorId"] for a in data["data"] if a.get("authorId")]


def fetch_author_papers(author_id: str, api_key: str, delay: float,
                        max_papers: int) -> list[dict]:
    papers: list[dict] = []
    offset = 0
    while len(papers) < max_papers:
        data = s2_get(f"/author/{author_id}/papers",
                      {"fields": PAPER_FIELDS, "offset": offset, "limit": 100},
                      api_key, delay)
        if not data or not data.get("data"):
            break
        papers.extend(data["data"])
        if data.get("next") is None:
            break
        offset = data["next"]
    return papers[:max_papers]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--author", required=True, help="Author display name")
    ap.add_argument("--s2-author-id", default=None,
                    help="Confirmed Semantic Scholar author id; when given, its papers "
                         "are mainline candidates. Omit to fall back to name search "
                         "(those rows are routed to human review).")
    ap.add_argument("--openalex-csv", type=Path, default=None,
                    help="OpenAlex bucket CSV; records already here (DOI/PMID) are dropped")
    ap.add_argument("--out", type=Path, required=True, help="Output directory")
    ap.add_argument("--max-papers", type=int, default=1000)
    ap.add_argument("--api-key", default=None, help="S2 API key (optional; lifts rate limits)")
    ap.add_argument("--request-delay", type=float, default=1.1,
                    help="Seconds between requests; keyless S2 needs ~1s to avoid 429")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    seen_dois, seen_pmids = load_seen_keys(args.openalex_csv)

    if args.s2_author_id:
        author_ids = [args.s2_author_id]
        route = "main"      # anchored → trustable onto the mainline
    else:
        author_ids = resolve_author_ids(args.author, args.api_key, args.request_delay)
        route = "review"    # name-search → cannot trust identity; send to review
        print(f"note: no --s2-author-id; name search found {len(author_ids)} candidate "
              f"author id(s); their papers are routed to human review, not the mainline.",
              file=sys.stderr)

    rows: list[dict] = []
    for aid in author_ids:
        for art in fetch_author_papers(aid, args.api_key, args.request_delay, args.max_papers):
            ext = art.get("externalIds") or {}
            doi = norm_doi(ext.get("DOI", ""))
            pmid = str(ext.get("PubMed", "")).strip()
            if (doi and doi in seen_dois) or (pmid and pmid in seen_pmids):
                continue
            if doi:
                seen_dois.add(doi)
            if pmid:
                seen_pmids.add(pmid)
            rows.append({
                "source": "s2_supplement",
                "route": route,
                "s2_author_id": aid,
                "year": art.get("year") or "",
                "pmid": pmid,
                "doi": doi,
                "title": art.get("title") or "",
                "venue": art.get("venue") or "",
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                "url": f"https://www.semanticscholar.org/paper/{art.get('paperId')}"
                       if art.get("paperId") else "",
                "cited_by_count": art.get("citationCount", ""),
            })

    fieldnames = ["source", "route", "s2_author_id", "year", "pmid", "doi", "title",
                  "venue", "pubmed_url", "url", "cited_by_count"]
    csv_path = args.out / "s2_supplement.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    summary = {
        "author": args.author,
        "s2_author_id": args.s2_author_id,
        "route": route,
        "author_ids_used": author_ids,
        "supplement_records": len(rows),
        "dedup_against": str(args.openalex_csv) if args.openalex_csv else None,
    }
    (args.out / "s2_supplement_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"S2 supplement: {len(rows)} records (route={route}) -> {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
