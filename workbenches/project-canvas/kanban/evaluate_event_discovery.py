#!/usr/bin/env python3
"""Score proposal-only Event Discovery output against a held-out gold spec.

The evaluator is intentionally separate from discovery. The generator receives
only source inputs; this scorer reads the gold answers after candidate output
already exists. Unmatched candidates are reported for human classification
rather than automatically labelled false positives, because adjacent meetings
can be real Events outside a narrower project mainline.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import plan_batch


SCHEMA_VERSION = "mario.event-discovery-gold-evaluation/v0"


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _matches(candidate, expected):
    pattern = expected.get("title_regex")
    if pattern and not re.search(pattern, candidate.get("proposed_title") or ""):
        return False
    event_type = expected.get("event_type_hint")
    if event_type and candidate.get("event_type_hint") != event_type:
        return False
    boundary_basis = expected.get("boundary_basis")
    if boundary_basis and (candidate.get("boundary") or {}).get("basis") != boundary_basis:
        return False
    return True


def evaluate(batch_root, gold_spec_path):
    batch_root = Path(batch_root).expanduser().resolve()
    gold_spec_path = Path(gold_spec_path).expanduser().resolve()
    candidates = plan_batch.read_jsonl(
        batch_root / "event-detection-candidates.jsonl"
    )
    report = _load_json(batch_root / "event-discovery-report.json")
    gold = _load_json(gold_spec_path)

    used_candidate_ids = set()
    event_results = []
    for expected in gold.get("expected_events") or []:
        matches = [
            row for row in candidates
            if row["candidate_id"] not in used_candidate_ids
            and _matches(row, expected)
        ]
        selected = matches[0] if len(matches) == 1 else None
        if selected:
            used_candidate_ids.add(selected["candidate_id"])
        expected_date = expected.get("date")
        actual_date = (selected or {}).get("time_hint", {}).get("date")
        event_results.append({
            "gold_event_id": expected["gold_event_id"],
            "matched": selected is not None,
            "candidate_id": selected.get("candidate_id") if selected else None,
            "candidate_title": selected.get("proposed_title") if selected else None,
            "match_count": len(matches),
            "expected_date": expected_date,
            "actual_date": actual_date,
            "date_status": (
                "not_scored"
                if not expected_date
                else "exact"
                if actual_date == expected_date
                else "unknown"
                if actual_date is None
                else "mismatch"
            ),
            "boundary_status": (
                (selected.get("boundary") or {}).get("status")
                if selected
                else None
            ),
        })

    review_results = []
    for expected in gold.get("expected_review_cases") or []:
        matches = [
            row for row in candidates
            if _matches(row, expected)
            and (row.get("boundary") or {}).get("status")
            == expected.get("boundary_status")
        ]
        review_results.append({
            "review_case_id": expected["review_case_id"],
            "matched": len(matches) == 1,
            "match_count": len(matches),
            "candidate_ids": [row["candidate_id"] for row in matches],
        })

    expected_dates = [
        row for row in event_results
        if row["expected_date"]
    ]
    unmatched = [
        {
            "candidate_id": row["candidate_id"],
            "proposed_title": row["proposed_title"],
            "date": (row.get("time_hint") or {}).get("date"),
            "boundary_status": (row.get("boundary") or {}).get("status"),
        }
        for row in candidates
        if row["candidate_id"] not in used_candidate_ids
    ]
    expected_count = len(event_results)
    matched_count = sum(row["matched"] for row in event_results)
    exact_date_count = sum(
        row["date_status"] == "exact" for row in expected_dates
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "gold_standard_id": gold.get("gold_standard_id"),
        "batch_root": str(batch_root),
        "gold_spec_path": str(gold_spec_path),
        "metrics": {
            "expected_event_count": expected_count,
            "matched_event_count": matched_count,
            "anchor_recall": (
                matched_count / expected_count if expected_count else 1.0
            ),
            "expected_date_count": len(expected_dates),
            "exact_date_count": exact_date_count,
            "exact_date_recall": (
                exact_date_count / len(expected_dates)
                if expected_dates
                else 1.0
            ),
            "expected_review_case_count": len(review_results),
            "matched_review_case_count": sum(
                row["matched"] for row in review_results
            ),
            "unmatched_candidate_count": len(unmatched),
            "canonical_write_count": len(report.get("canonical_writes") or []),
        },
        "event_results": event_results,
        "review_results": review_results,
        "unmatched_candidates": unmatched,
        "unmatched_candidate_policy": (
            "Human classification required: an unmatched candidate can be a "
            "real adjacent Event outside the narrower gold mainline."
        ),
    }
    payload["evaluation_hash"] = plan_batch.batch_hash(payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--gold-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = evaluate(args.batch_root, args.gold_spec)
    output = args.output or (
        Path(args.batch_root).expanduser().resolve() / "gold-validation.json"
    )
    plan_batch.write_json(output, payload)
    print(json.dumps({
        "ok": True,
        "output": str(Path(output).expanduser().resolve()),
        **payload["metrics"],
        "evaluation_hash": payload["evaluation_hash"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
