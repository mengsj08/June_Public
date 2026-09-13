#!/usr/bin/env python3
"""PubMed author year-supplement for the author literature map.

Why this exists
---------------
The main pass resolves an author through OpenAlex author IDs. OpenAlex sometimes
splits one person across several author IDs and lags on the newest year, so a
single OpenAlex author.id can show 0 papers for the current year while PubMed
already indexes several. This script closes that gap: it queries PubMed by
full-author-name (FAU) per year, drops records already covered by an OpenAlex
bucket CSV (by DOI/PMID), and writes a supplement the ledger folds in.

Self-contained: talks to the public NCBI E-utilities API with the standard
library only (no third-party client). Read-only over the network; only writes
the supplement files under --out.

Politeness / rate limits: NCBI asks for <=3 req/s without an API key (10/s with
one). Pass --api-key and --email to lift limits and identify your tool. On any
network failure the script degrades gracefully (writes what it has, exits 0).
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

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def norm_doi(value: str) -> str:
    return (value or "").strip().lower().replace("https://doi.org/", "").replace(
        "http://doi.org/", "")


def eutils_get(endpoint: str, params: dict, delay: float) -> dict | None:
    url = f"{EUTILS}/{endpoint}?{urllib.parse.urlencode(params)}"
    time.sleep(delay)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # network / rate-limit / JSON — all degrade the same
        print(f"warning: PubMed request failed ({exc}) for {endpoint}", file=sys.stderr)
        return None


def esearch_pmids(query: str, retmax: int, common: dict, delay: float) -> tuple[list[str], bool]:
    """Return (pmids, truncated). truncated=True if the result count exceeded retmax."""
    data = eutils_get("esearch.fcgi", {**common, "db": "pubmed", "term": query,
                                       "retmax": retmax, "retmode": "json"}, delay)
    if not data:
        return [], False
    res = data.get("esearchresult", {})
    pmids = res.get("idlist", []) or []
    try:
        total = int(res.get("count", "0"))
    except ValueError:
        total = len(pmids)
    return pmids, total > retmax


def esummary(pmids: list[str], common: dict, delay: float) -> dict:
    if not pmids:
        return {}
    data = eutils_get("esummary.fcgi", {**common, "db": "pubmed",
                                        "id": ",".join(pmids), "retmode": "json"}, delay)
    return (data or {}).get("result", {}) if data else {}


def doi_from_articleids(rec: dict) -> str:
    for aid in rec.get("articleids", []) or []:
        if aid.get("idtype") == "doi":
            return norm_doi(aid.get("value", ""))
    return ""


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fau", required=True,
                    help='PubMed full-author-name term, e.g. "Doe Jane" (Lastname Firstname)')
    ap.add_argument("--years", required=True,
                    help="Comma list or range, e.g. 2024,2025,2026 or 2024-2026")
    ap.add_argument("--openalex-csv", type=Path, default=None,
                    help="OpenAlex bucket CSV; records already here (DOI/PMID) are dropped")
    ap.add_argument("--out", type=Path, required=True, help="Output directory")
    ap.add_argument("--route", default="main", choices=["main", "review"],
                    help="Routing for these rows (default main; FAU is name-anchored). "
                         "Use review if homonym risk is unresolved.")
    ap.add_argument("--max-per-year", type=int, default=200)
    ap.add_argument("--email", default=None, help="Contact email (NCBI politeness)")
    ap.add_argument("--api-key", default=None, help="NCBI API key (optional; lifts rate limits)")
    ap.add_argument("--request-delay", type=float, default=0.34,
                    help="Seconds between requests; 0.34 keyless, ~0.1 with a key")
    args = ap.parse_args(argv)

    if "-" in args.years and "," not in args.years:
        lo, hi = args.years.split("-", 1)
        years = [str(y) for y in range(int(lo), int(hi) + 1)]
    else:
        years = [y.strip() for y in args.years.split(",") if y.strip()]

    common: dict = {"tool": "author-literature-map"}
    if args.email:
        common["email"] = args.email
    if args.api_key:
        common["api_key"] = args.api_key

    seen_dois, seen_pmids = load_seen_keys(args.openalex_csv)
    args.out.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    per_year_counts: dict[str, int] = {}
    truncated_years: list[str] = []
    for year in years:
        query = f'"{args.fau}"[FAU] AND {year}[dp]'
        pmids, truncated = esearch_pmids(query, args.max_per_year, common, args.request_delay)
        if truncated:
            # A capped year may be incomplete; surface it rather than let it read as complete.
            truncated_years.append(year)
        summ = esummary(pmids, common, args.request_delay)
        kept = 0
        for pmid in pmids:
            rec = summ.get(pmid)
            if not isinstance(rec, dict):
                continue
            doi = doi_from_articleids(rec)
            if (doi and doi in seen_dois) or (pmid in seen_pmids):
                continue
            rows.append({
                "source": "pubmed_supplement", "route": args.route, "year": year,
                "pmid": pmid, "doi": doi,
                "title": rec.get("title", ""),
                "venue": rec.get("fulljournalname", "") or rec.get("source", ""),
                "authors": "; ".join(a.get("name", "") for a in rec.get("authors", []) or []),
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "query": query,
            })
            if doi:
                seen_dois.add(doi)
            seen_pmids.add(pmid)
            kept += 1
        per_year_counts[year] = kept
        print(f"{year}: PubMed returned {len(pmids)}, kept {kept} after dedup"
              + ("  [TRUNCATED]" if truncated else ""))

    fieldnames = ["source", "route", "year", "pmid", "doi", "title", "venue",
                  "authors", "pubmed_url", "query"]
    csv_path = args.out / "pubmed_supplement.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    summary = {"fau": args.fau, "years": years, "route": args.route,
               "total_supplement_records": len(rows), "per_year_kept": per_year_counts,
               "truncated_years": truncated_years,
               "dedup_against": str(args.openalex_csv) if args.openalex_csv else None}
    (args.out / "pubmed_supplement_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSupplement: {len(rows)} records not in OpenAlex pass -> {csv_path}")
    if truncated_years:
        print(f"⚠ TRUNCATED years (may be incomplete): {', '.join(truncated_years)} "
              f"— raise --max-per-year or narrow the query.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
