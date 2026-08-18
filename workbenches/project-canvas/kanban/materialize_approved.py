#!/usr/bin/env python3
"""Promote approved Mario batch review rows after a separate human gate.

KMO-147 only authorizes this skeleton and its guardrails. The implementation
refuses to materialize unless a future task supplies an explicit approval list
and source verification remains mandatory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import plan_batch


def load_approved_rows(path):
    rows = plan_batch.read_jsonl(path)
    return [row for row in rows if row.get("approved_by") == "Owner" and row.get("approval_id")]


def planned_downstream_pin_rows(approved_rows):
    return [
        {
            "approval_id": row.get("approval_id"),
            "question_type": row.get("question_type"),
            "source_verification": "required",
            "downstream_spec_hash_repin": "required_after_promote",
            "review_manifest_entry": "required",
        }
        for row in approved_rows
    ]


def plan_materialization(*, approved_review_queue):
    approved = load_approved_rows(approved_review_queue)
    if not approved:
        raise ValueError("no Owner-approved review rows were supplied")
    return {
        "ok": True,
        "mode": "promote_plan_only",
        "approved_count": len(approved),
        "downstream_repin_manifest": planned_downstream_pin_rows(approved),
        "writes_authorized": False,
        "note": "Future Promote must verify every source hash, write approved deltas only, then re-pin downstream spec hashes into the review manifest.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-review-queue", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = plan_materialization(approved_review_queue=args.approved_review_queue)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
