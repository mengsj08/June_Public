#!/usr/bin/env python3
"""Validate Mario batch Scan + Discovery + Shadow artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import plan_batch


REQUIRED_SHADOW_FILES = (
    "event-candidates.jsonl",
    "same-event-candidates.jsonl",
    "review-queue.jsonl",
    "batch-report.json",
)
REQUIRED_DISCOVERY_FILES = (
    "source-observations.jsonl",
    "event-detection-candidates.jsonl",
    "event-detection-review-queue.jsonl",
    "non-event-sources.jsonl",
    "event-discovery-report.json",
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _hash_outputs(batch_root):
    rows = []
    for path in sorted(Path(batch_root).rglob("*")):
        if path.is_file():
            rows.append({"path": str(path), "sha256": plan_batch.sha256_file(path)})
    return rows


def validate_batch(batch_root):
    batch_root = Path(batch_root).expanduser().resolve()
    errors = []
    scope_path = batch_root / "batch-scope.json"
    inventory_path = batch_root / "source-inventory.jsonl"
    unresolved_path = batch_root / "unresolved-identities.jsonl"
    for path in (scope_path, inventory_path, unresolved_path):
        if not path.exists():
            errors.append(f"missing required scan output: {path}")
    if errors:
        return errors

    scope = read_json(scope_path)
    if scope.get("schema_version") != plan_batch.SCHEMA_VERSION:
        errors.append("batch-scope schema_version is invalid")
    source_inputs = scope.get("source_inputs")
    if not isinstance(source_inputs, list) or not source_inputs:
        errors.append("batch-scope source_inputs must be non-empty")
    evidence_events = scope.get("evidence_events") or []
    minimum_events = scope.get("minimum_multiplayer_events_required")
    if minimum_events is None:
        minimum_events = 3
    if len(evidence_events) < int(minimum_events):
        errors.append("batch-scope must include at least 3 multiplayer Event evidence pointers")
    for event in evidence_events:
        if int(event.get("participant_count") or 0) < 2:
            errors.append(f"Event is not multiplayer: {event.get('event_id')}")
        if not event.get("source_relation_ids") and not event.get("assertion_ids"):
            errors.append(f"Event lacks evidence pointers: {event.get('event_id')}")

    inventory = plan_batch.read_jsonl(inventory_path)
    if not inventory:
        errors.append("source-inventory must not be empty")
    for row in inventory:
        digest = str(row.get("sha256") or "")
        blob_oid = str(row.get("git_blob_oid") or "")
        if len(digest) != 64 and len(blob_oid) not in {40, 64}:
            errors.append(f"inventory content identity is invalid: {row.get('path')}")

    for name in REQUIRED_DISCOVERY_FILES:
        if not (batch_root / name).exists():
            errors.append(f"missing required discovery output: {batch_root / name}")
    if errors:
        return errors

    observations = plan_batch.read_jsonl(batch_root / "source-observations.jsonl")
    if len(observations) != len(inventory):
        errors.append("source-observations must preserve one row per inventory source")
    if any(row.get("raw_body_exported") is not False for row in observations):
        errors.append("source-observations must not export raw source bodies")

    discovery_candidates = plan_batch.read_jsonl(
        batch_root / "event-detection-candidates.jsonl"
    )
    candidate_ids = [row.get("candidate_id") for row in discovery_candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("event-detection candidate ids are not unique")
    for row in discovery_candidates:
        if row.get("promotion_allowed") is not False:
            errors.append(
                f"event-detection candidate permits promotion: {row.get('candidate_id')}"
            )
        if row.get("semantic_analysis_status") != "not_run":
            errors.append(
                f"event-detection candidate overclaims semantic analysis: {row.get('candidate_id')}"
            )
        source_refs = row.get("source_refs") or []
        if not source_refs:
            errors.append(
                f"event-detection candidate lacks evidence refs: {row.get('candidate_id')}"
            )
        if any(source.get("raw_body_exported") is not False for source in source_refs):
            errors.append(
                f"event-detection candidate exports raw body: {row.get('candidate_id')}"
            )
        if not (row.get("boundary") or {}).get("rule"):
            errors.append(
                f"event-detection candidate lacks boundary rule: {row.get('candidate_id')}"
            )

    discovery_reviews = plan_batch.read_jsonl(
        batch_root / "event-detection-review-queue.jsonl"
    )
    discovery_questions = []
    for row in discovery_reviews:
        if row.get("impact") != "high":
            errors.append("event-detection review queue contains a non-high-impact question")
        if not row.get("evidence_refs"):
            errors.append("event-detection review row lacks evidence_refs")
        question = str(row.get("question") or "").strip()
        if not question:
            errors.append("event-detection review row lacks question text")
        if row.get("candidate_id") not in set(candidate_ids):
            errors.append("event-detection review row references an unknown candidate")
        discovery_questions.append(question)
    if len(discovery_questions) != len(set(discovery_questions)):
        errors.append("event-detection review queue contains duplicate question text")

    discovery_report = read_json(batch_root / "event-discovery-report.json")
    if discovery_report.get("raw_body_exported") is not False:
        errors.append("event-discovery report raw_body_exported is not false")
    if discovery_report.get("canonical_writes") != []:
        errors.append("event-discovery report contains canonical writes")
    if discovery_report.get("event_detection_candidate_count") != len(
        discovery_candidates
    ):
        errors.append("event-discovery report candidate count does not match output")
    if discovery_report.get("boundary_review_count") != len(discovery_reviews):
        errors.append("event-discovery report review count does not match output")
    if scope.get("mode") == "scan_discovery_only":
        return errors

    for name in REQUIRED_SHADOW_FILES:
        if not (batch_root / name).exists():
            errors.append(f"missing required shadow output: {batch_root / name}")
    recon_dir = batch_root / "event-reconstructions"
    unit_dir = batch_root / "unit-candidates"
    if not recon_dir.is_dir():
        errors.append("event-reconstructions directory is missing")
    if not unit_dir.is_dir():
        errors.append("unit-candidates directory is missing")
    if errors:
        return errors

    same_event_rows = plan_batch.read_jsonl(batch_root / "same-event-candidates.jsonl")
    for row in same_event_rows:
        basis = row.get("basis") or {}
        if not basis or "rule" not in basis:
            errors.append(f"same-event candidate lacks explicit basis: {row.get('candidate_group_id')}")
        if row.get("auto_merge_allowed") is not False:
            errors.append(f"same-event candidate must be proposal-only: {row.get('candidate_group_id')}")

    recon_ids = []
    for path in sorted(recon_dir.glob("*.json")):
        row = read_json(path)
        event_id = row.get("event_id")
        recon_ids.append(event_id)
        moves = row.get("moves") or []
        if [move.get("actor") for move in moves] != ["对方", "我们", "世界变化"]:
            errors.append(f"reconstruction moves are invalid: {path}")
        for move in moves:
            if move.get("basis") not in {"source_backed", "owner_confirmed", "derived", "unknown"}:
                errors.append(f"invalid basis in reconstruction: {path}")
    if len(recon_ids) != len(set(recon_ids)):
        errors.append("same Event is reconstructed more than once")

    unit_rows = []
    for path in sorted(unit_dir.glob("*.jsonl")):
        unit_rows.extend(plan_batch.read_jsonl(path))
    fanout = {}
    for row in unit_rows:
        fanout.setdefault(row.get("event_id"), set()).add(row.get("unit_ref"))
        if row.get("candidate_only") is not True:
            errors.append(f"unit candidate is not candidate-only: {row.get('event_id')}")
    if not any(len(values) >= 2 for values in fanout.values()):
        errors.append("no Event fans out to at least 2 Unit candidates")

    review_rows = plan_batch.read_jsonl(batch_root / "review-queue.jsonl")
    questions = {}
    for row in review_rows:
        if row.get("impact") != "high":
            errors.append("review-queue contains a non-high-impact question")
        if not row.get("evidence_refs"):
            errors.append("review-queue row lacks evidence_refs")
        question = str(row.get("question") or "").strip()
        if not question:
            errors.append("review-queue row lacks question text")
        questions[question] = questions.get(question, 0) + 1
    repeated = sorted(question for question, count in questions.items() if count > 1)
    if repeated:
        errors.append("review-queue contains duplicate question text: " + "; ".join(repeated))

    report = read_json(batch_root / "batch-report.json")
    if not report.get("deduplication_ok"):
        errors.append("batch-report deduplication_ok is false")
    if not report.get("fanout_ok"):
        errors.append("batch-report fanout_ok is false")
    if not (report.get("zero_canonical_write_check") or {}).get("ok"):
        errors.append("zero canonical write check failed")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=plan_batch.DEFAULT_BATCH_ROOT)
    parser.add_argument("--hash-outputs", action="store_true")
    args = parser.parse_args(argv)
    errors = validate_batch(args.batch_root)
    result = {
        "ok": not errors,
        "batch_root": str(Path(args.batch_root).expanduser().resolve()),
        "errors": errors,
    }
    if args.hash_outputs:
        result["output_hashes"] = _hash_outputs(args.batch_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
