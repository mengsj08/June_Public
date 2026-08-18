#!/usr/bin/env python3
"""Build Mario batch Shadow artifacts from a planned read-only scope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import plan_batch


SCHEMA_VERSION = "mario.batch-shadow/v0"
BASIS_KINDS = {"source_backed", "owner_confirmed", "derived", "unknown"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def monitored_snapshot(paths):
    rows = []
    for path in sorted({str(Path(item).expanduser().resolve()) for item in paths}):
        target = Path(path)
        if not target.exists() or not target.is_file():
            rows.append({"path": path, "exists": False, "sha256": None, "mtime_ns": None})
            continue
        stat = target.stat()
        rows.append({
            "path": path,
            "exists": True,
            "sha256": plan_batch.sha256_file(target),
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
        })
    return rows


def _rows_by_key(rows, key):
    result = {}
    for row in rows:
        result.setdefault(row.get(key), []).append(row)
    return result


def _event_rows(scope, ledger_dir):
    wanted = {row["event_id"] for row in scope["evidence_events"]}
    events, bindings, assertions = plan_batch.load_event_context(ledger_dir)
    return (
        [row for row in events if row.get("event_id") in wanted],
        [row for row in bindings if row.get("event_id") in wanted],
        [row for row in assertions if row.get("event_id") in wanted],
    )


def _basis_for_assertion(row):
    confidence = str(row.get("confidence") or "")
    if confidence == "human_confirmed":
        return "owner_confirmed"
    if confidence in {"high", "medium"}:
        return "source_backed"
    return "unknown"


def build_event_candidates(events, bindings_by_event, assertions_by_event):
    rows = []
    for event in sorted(events, key=lambda row: (plan_batch.event_date(row), row.get("event_id") or "")):
        event_id = event.get("event_id")
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "candidate_status": "shadow_from_readonly_scope",
            "title": event.get("title"),
            "canonical_time": event.get("canonical_time"),
            "event_type": event.get("event_type"),
            "project_ref": event.get("project_ref"),
            "project_candidate_refs": list(event.get("project_candidate_refs") or []),
            "participant_count": len(bindings_by_event.get(event_id) or []),
            "participant_binding_ids": [row.get("binding_id") for row in bindings_by_event.get(event_id, [])],
            "source_relation_ids": list(event.get("source_relation_ids") or []),
            "assertion_ids": [row.get("assertion_id") for row in assertions_by_event.get(event_id, [])],
            "decision": "proposal_only_no_write",
        })
    return rows


def participant_key(row):
    return row.get("entity_id") or row.get("participant_candidate_id") or row.get("role_label")


def build_same_event_candidates(events, bindings_by_event, assertions_by_event):
    rows = []
    events = sorted(events, key=lambda row: (plan_batch.event_date(row), row.get("event_id") or ""))
    for index, left in enumerate(events):
        for right in events[index + 1:]:
            if plan_batch.event_date(left) != plan_batch.event_date(right):
                continue
            left_people = {participant_key(row) for row in bindings_by_event.get(left.get("event_id"), []) if participant_key(row)}
            right_people = {participant_key(row) for row in bindings_by_event.get(right.get("event_id"), []) if participant_key(row)}
            overlap = sorted(left_people & right_people)
            if not overlap:
                continue
            evidence = []
            for event in (left, right):
                event_id = event.get("event_id")
                evidence.extend(row.get("assertion_id") for row in assertions_by_event.get(event_id, []) if row.get("assertion_id"))
            rows.append({
                "schema_version": SCHEMA_VERSION,
                "candidate_group_id": "same-event-proposal:" + left["event_id"] + "__" + right["event_id"],
                "event_ids": [left["event_id"], right["event_id"]],
                "basis": {
                    "strong_evidence_found": False,
                    "weak_similarity": ["same calendar date", "overlapping participants"],
                    "overlapping_participants": overlap,
                    "source_assertion_ids": evidence,
                    "rule": "weak similarity only creates a review proposal; it never merges Events",
                },
                "proposed_action": "keep_separate_pending_owner_review",
                "auto_merge_allowed": False,
            })
    return rows


def build_reconstruction(event, bindings, assertions):
    owner_rows = [
        row for row in bindings
        if "Owner" in str(row.get("role_label") or "") or row.get("participant_candidate_id") == "participant-candidate-owner-owner"
    ]
    other_rows = [row for row in bindings if row not in owner_rows]
    assertions_out = [
        {
            "assertion_id": row.get("assertion_id"),
            "field": row.get("field"),
            "basis": _basis_for_assertion(row),
            "source_id": row.get("source_id"),
            "locator": row.get("locator"),
        }
        for row in sorted(assertions, key=lambda item: item.get("assertion_id") or "")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event.get("event_id"),
        "title": event.get("title"),
        "canonical_time": event.get("canonical_time"),
        "status": "shadow_reconstruction_proposal_only",
        "no_raw_speech_fabrication": True,
        "moves": [
            {
                "actor": "对方",
                "basis": "source_backed" if other_rows else "unknown",
                "summary": "Participant roles are copied from bindings; no unsourced utterances are reconstructed.",
                "participant_binding_ids": [row.get("binding_id") for row in other_rows],
            },
            {
                "actor": "我们",
                "basis": "source_backed" if owner_rows else "unknown",
                "summary": "Owner-side role is copied from bindings; no official project or relationship state is changed.",
                "participant_binding_ids": [row.get("binding_id") for row in owner_rows],
            },
            {
                "actor": "世界变化",
                "basis": "derived",
                "summary": "Downstream Unit candidates are proposed from event/project/person bindings for review only.",
                "project_ref": event.get("project_ref"),
                "project_candidate_refs": list(event.get("project_candidate_refs") or []),
            },
        ],
        "assertions": assertions_out,
    }


def unit_candidates_for_event(event, bindings):
    rows = []
    event_id = event.get("event_id")
    for row in sorted(bindings, key=lambda item: item.get("binding_id") or ""):
        target = row.get("entity_id") or row.get("participant_candidate_id")
        if not target:
            continue
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "unit_type": "relationship",
            "unit_ref": target,
            "basis": "source_backed",
            "binding_id": row.get("binding_id"),
            "candidate_only": True,
        })
    if event.get("project_ref"):
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "unit_type": "project",
            "unit_ref": event.get("project_ref"),
            "basis": "source_backed",
            "candidate_only": True,
        })
    for ref in event.get("project_candidate_refs") or []:
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "unit_type": "opportunity",
            "unit_ref": ref,
            "basis": "derived",
            "candidate_only": True,
        })
    return rows


def _event_summary(event_lookup, event_id):
    event = event_lookup.get(event_id) or {}
    date = plan_batch.event_date(event) or str(event.get("canonical_time") or "unknown date")
    title = event.get("title") or event_id
    return date, title


def _evidence_label(refs):
    refs = [str(ref) for ref in refs if ref]
    if not refs:
        return "no evidence ref"
    if len(refs) == 1:
        return refs[0]
    return ", ".join(refs[:3]) + (" ..." if len(refs) > 3 else "")


def build_review_queue(unresolved_rows, same_event_rows, unit_rows, event_lookup):
    rows = []
    for row in unresolved_rows:
        if row.get("participant_candidate_id") == "participant-candidate-owner-owner":
            continue
        date, title = _event_summary(event_lookup, row.get("event_id"))
        role_label = row.get("role_label") or row.get("participant_candidate_id") or "unknown participant"
        evidence_refs = list(row.get("evidence_refs") or [])
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "impact": "high",
            "question_type": "identity_confirmation",
            "event_id": row.get("event_id"),
            "subject_ref": row.get("participant_candidate_id"),
            "evidence_refs": evidence_refs,
            "answer_options": ["是，同一人", "否，保持候选身份", "暂不裁决"],
            "question": (
                f"{date}「{title}」中出现的「{role_label}」是否应绑定为已有人脉身份？"
                f"（证据：{_evidence_label(evidence_refs)}）"
            ),
        })
    for row in same_event_rows:
        event_ids = list(row.get("event_ids") or [])
        descriptions = []
        for event_id in event_ids:
            date, title = _event_summary(event_lookup, event_id)
            descriptions.append(f"{date}「{title}」")
        evidence_refs = list((row.get("basis") or {}).get("source_assertion_ids") or [])
        overlap = ", ".join((row.get("basis") or {}).get("overlapping_participants") or [])
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "impact": "high",
            "question_type": "same_event_boundary",
            "event_ids": event_ids,
            "evidence_refs": evidence_refs,
            "answer_options": ["是，同一场 Event", "否，保持两场 Event", "暂不裁决"],
            "question": (
                f"{' 与 '.join(descriptions)} 是否其实是同一场 Event？"
                f"（重叠参与者：{overlap or 'unknown'}；证据：{_evidence_label(evidence_refs)}）"
            ),
        })
    return sorted(rows, key=lambda item: plan_batch.stable_json(item))


def build_guard_notes(unit_rows, event_lookup):
    rows = []
    for row in unit_rows:
        if row.get("unit_type") != "opportunity":
            continue
        date, title = _event_summary(event_lookup, row.get("event_id"))
        rows.append({
            "schema_version": SCHEMA_VERSION,
            "note_type": "opportunity_or_project_guard",
            "event_id": row.get("event_id"),
            "subject_ref": row.get("unit_ref"),
            "evidence_refs": [row.get("event_id")],
            "guard": (
                f"{date}「{title}」产生 opportunity candidate {row.get('unit_ref')}；"
                "Shadow/validate/materialize must not change project or opportunity state without Owner Promote approval."
            ),
        })
    return sorted(rows, key=lambda item: plan_batch.stable_json(item))


def build_shadow(batch_root, monitor_paths):
    batch_root = Path(batch_root).expanduser().resolve()
    scope = read_json(batch_root / "batch-scope.json")
    discovery_report_path = batch_root / "event-discovery-report.json"
    discovery_report = (
        read_json(discovery_report_path)
        if discovery_report_path.exists()
        else {}
    )
    before = monitored_snapshot(monitor_paths)
    events, bindings, assertions = _event_rows(scope, scope["event_ledger_dir"])
    bindings_by_event = _rows_by_key(bindings, "event_id")
    assertions_by_event = _rows_by_key(assertions, "event_id")

    event_candidates = build_event_candidates(events, bindings_by_event, assertions_by_event)
    same_event = build_same_event_candidates(events, bindings_by_event, assertions_by_event)
    recon_dir = batch_root / "event-reconstructions"
    unit_dir = batch_root / "unit-candidates"
    recon_dir.mkdir(parents=True, exist_ok=True)
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_rows = []
    for event in event_candidates:
        event_id = event["event_id"]
        event_row = next(row for row in events if row.get("event_id") == event_id)
        plan_batch.write_json(
            recon_dir / f"{event_id}.json",
            build_reconstruction(event_row, bindings_by_event.get(event_id, []), assertions_by_event.get(event_id, [])),
        )
        event_unit_rows = unit_candidates_for_event(event_row, bindings_by_event.get(event_id, []))
        unit_rows.extend(event_unit_rows)
        plan_batch.write_jsonl(unit_dir / f"{event_id}.jsonl", event_unit_rows)

    unresolved = plan_batch.read_jsonl(batch_root / "unresolved-identities.jsonl")
    event_lookup = {row.get("event_id"): row for row in events}
    review_queue = build_review_queue(unresolved, same_event, unit_rows, event_lookup)
    guard_notes = build_guard_notes(unit_rows, event_lookup)
    after = monitored_snapshot(monitor_paths)
    zero_write_ok = before == after
    reconstruction_ids = [row["event_id"] for row in event_candidates]
    fanout = {
        event_id: len({row["unit_ref"] for row in unit_rows if row["event_id"] == event_id})
        for event_id in reconstruction_ids
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "batch_scope_hash": scope.get("scope_hash"),
        "event_detection_candidate_count": discovery_report.get(
            "event_detection_candidate_count", 0
        ),
        "event_boundary_review_count": discovery_report.get(
            "boundary_review_count", 0
        ),
        "event_candidate_count": len(event_candidates),
        "same_event_candidate_count": len(same_event),
        "event_reconstruction_count": len(reconstruction_ids),
        "unique_event_reconstruction_count": len(set(reconstruction_ids)),
        "deduplication_ok": len(reconstruction_ids) == len(set(reconstruction_ids)),
        "fanout_by_event": fanout,
        "fanout_ok": any(count >= 2 for count in fanout.values()),
        "review_queue_count": len(review_queue),
        "zero_canonical_write_check": {
            "ok": zero_write_ok,
            "before": before,
            "after": after,
        },
        "outputs": {
            "event_detection_candidates": str(
                batch_root / "event-detection-candidates.jsonl"
            ),
            "event_detection_review_queue": str(
                batch_root / "event-detection-review-queue.jsonl"
            ),
            "event_candidates": str(batch_root / "event-candidates.jsonl"),
            "same_event_candidates": str(batch_root / "same-event-candidates.jsonl"),
            "event_reconstructions": str(recon_dir),
            "unit_candidates": str(unit_dir),
            "review_queue": str(batch_root / "review-queue.jsonl"),
            "guard_notes": str(batch_root / "guard-notes.jsonl"),
        },
    }
    report["report_hash"] = plan_batch.batch_hash(report)
    plan_batch.write_jsonl(batch_root / "event-candidates.jsonl", event_candidates)
    plan_batch.write_jsonl(batch_root / "same-event-candidates.jsonl", same_event)
    plan_batch.write_jsonl(batch_root / "review-queue.jsonl", review_queue)
    plan_batch.write_jsonl(batch_root / "guard-notes.jsonl", guard_notes)
    plan_batch.write_json(batch_root / "batch-report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=plan_batch.DEFAULT_BATCH_ROOT)
    parser.add_argument("--monitor-path", action="append", required=True)
    args = parser.parse_args(argv)
    report = build_shadow(args.batch_root, args.monitor_path)
    print(json.dumps({
        "ok": True,
        "batch_root": str(Path(args.batch_root).expanduser().resolve()),
        "report_hash": report["report_hash"],
        "zero_canonical_write_ok": report["zero_canonical_write_check"]["ok"],
        "event_reconstruction_count": report["event_reconstruction_count"],
        "review_queue_count": report["review_queue_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if report["zero_canonical_write_check"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
