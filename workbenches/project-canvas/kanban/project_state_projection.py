#!/usr/bin/env python3
"""Compile Event-ledger facts into a rebuildable real-project state sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA = "kanban-real-projects/v1"
STATE_SCHEMA = "kanban-real-project-state/v1"
REGISTRY_REL = Path("project/个人调度/.real-projects/projects.json")
STATE_REL = Path("project/个人调度/.real-projects/project-state.generated.json")
REQUIRED_LEDGER_FILES = (
    "events.jsonl",
    "source-pointers.jsonl",
    "source-relations.jsonl",
)


class ProjectionError(RuntimeError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectionError(f"JSON root must be an object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectionError(f"cannot read JSONL: {path}: {exc}") from exc
    rows = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProjectionError(f"invalid JSONL row {path}:{index}") from exc
        if not isinstance(row, dict):
            raise ProjectionError(f"JSONL row must be an object: {path}:{index}")
        rows.append(row)
    return rows


def _atomic_write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def _verify_ledger(ledger_root: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest_path = ledger_root / "manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("manifest_version") != "event-ledger-manifest/v1":
        raise ProjectionError("unsupported Event ledger manifest")
    declared = manifest.get("files")
    if not isinstance(declared, dict):
        raise ProjectionError("Event ledger manifest files must be an object")
    rows_by_file: dict[str, list[dict[str, Any]]] = {}
    for filename in REQUIRED_LEDGER_FILES:
        expected = declared.get(filename)
        path = ledger_root / filename
        if not isinstance(expected, dict) or not path.is_file():
            raise ProjectionError(f"Event ledger file is missing from manifest: {filename}")
        if _sha256_file(path) != expected.get("sha256"):
            raise ProjectionError(f"Event ledger digest mismatch: {filename}")
        rows = _read_jsonl(path)
        if len(rows) != expected.get("row_count"):
            raise ProjectionError(f"Event ledger row count mismatch: {filename}")
        rows_by_file[filename] = rows
    return manifest, rows_by_file


def _verified_closure(
    project_ref: str,
    event_ids: set[str],
    source_rows: dict[str, dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    source_ids = {
        row.get("source_id")
        for row in relations
        if row.get("event_id") in event_ids
    }
    for source_id in sorted(source_ids):
        pointer = source_rows.get(str(source_id))
        if not pointer or pointer.get("source_kind") != "project_fact_closure":
            continue
        path = Path(str(pointer.get("source_path") or ""))
        if not path.is_file() or _sha256_file(path) != pointer.get("sha256"):
            raise ProjectionError(f"project closure source drifted: {path}")
        closure = _read_json(path)
        project = closure.get("project") if isinstance(closure.get("project"), dict) else {}
        coverage = closure.get("coverage") if isinstance(closure.get("coverage"), dict) else {}
        source_project_id = str(project.get("project_id") or "")
        if source_project_id not in {project_ref, f"prj-{project_ref}"}:
            continue
        if project.get("registration_status") != "registered":
            continue
        if coverage.get("event_count") != len(event_ids):
            continue
        if coverage.get("events_with_high_confidence_source") != len(event_ids):
            continue
        return closure
    return None


def _event_label(events: list[dict[str, Any]]) -> str:
    course_count = sum(row.get("event_type") == "course" for row in events)
    field_count = sum(
        "field-research" in str(row.get("event_id") or "")
        or "驻场" in str(row.get("title") or "")
        for row in events
    )
    parts = []
    if course_count:
        parts.append(f"{course_count} 次课程")
    if field_count:
        parts.append(f"{field_count} 次驻场调研")
    accounted = course_count + field_count
    if len(events) > accounted:
        parts.append(f"{len(events) - accounted} 个其他 Event")
    return "＋".join(parts) if parts else f"{len(events)} 个 Event"


def _material_gap_unknown(closure: dict[str, Any]) -> str | None:
    coverage = closure.get("coverage") if isinstance(closure.get("coverage"), dict) else {}
    counts = coverage.get("missing_stage_counts")
    if not isinstance(counts, dict):
        return None
    labels = {"before": "课前", "during": "现场", "after": "课后"}
    parts = [
        f"{labels[key]} {value} 项"
        for key, value in counts.items()
        if key in labels and isinstance(value, int) and value > 0
    ]
    if not parts:
        return None
    return "材料覆盖仍有显式缺口：" + "、".join(parts) + "；不影响已确认 Event 的发生与项目关联。"


def _superseded_unknown(text: str, closure_verified: bool) -> bool:
    if not closure_verified:
        return False
    if ("Event" in text or "子事件" in text) and any(
        marker in text for marker in ("尚未", "待校对", "未全部晋升", "建立正式项目关联")
    ):
        return True
    if "材料" in text and "覆盖" in text and "校对" in text:
        return True
    return False


def _project_state(
    registered: dict[str, Any],
    events: list[dict[str, Any]],
    closure: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    project_ref = registered["project_ref"]
    ordered = sorted(events, key=lambda row: (str(row.get("canonical_time") or ""), row["event_id"]))
    event_ids = [row["event_id"] for row in ordered]
    all_confirmed = bool(ordered) and all(row.get("status") == "confirmed" for row in ordered)
    label = _event_label(ordered)
    closure_verified = closure is not None
    completion_phrase = "，均为 confirmed" if all_confirmed else ""
    latest_update = (
        f"Event 正本已关联 {len(ordered)} 个 Event（{label}）{completion_phrase}；"
        f"来源事务 {manifest['transaction_id']}。"
    )
    derived_fields: dict[str, Any] = {
        "latest_update": latest_update,
        "impact": "项目视图已消费 Event 正本；旧的待校对数量与未关联摘要失效。",
        "recommendation": "后续判断必须基于当前 Event 正本与显式任务，不再回退到手写事件数量。",
        "checkpoint": {
            "expected_change": "Event 正本新增或修正后，项目投影以新 transaction 重建；无变化不改写 sidecar。",
            "reason": f"当前投影锁定 {manifest['transaction_id']}，可由输入哈希验证。",
        },
    }
    if registered.get("lifecycle") == "completed" and all_confirmed and closure_verified:
        derived_fields["primary_action"] = {
            "type": "no_action",
            "summary": f"{len(ordered)} 个 Event 正本关联已完成",
            "reason": "Event 发生、边界、日期和正式项目关系均已通过收口；事实层当前无需 Owner 再校对。",
        }

    original_unknowns = [str(item) for item in registered.get("unknowns") or []]
    superseded = [item for item in original_unknowns if _superseded_unknown(item, closure_verified)]
    unknowns = [item for item in original_unknowns if item not in superseded]
    if closure:
        gap = _material_gap_unknown(closure)
        if gap and gap not in unknowns:
            unknowns.append(gap)

    milestone_updates = []
    if closure_verified:
        for milestone in registered.get("milestones") or []:
            label_text = str(milestone.get("label") or "")
            if "Event" in label_text:
                milestone_updates.append(
                    {
                        "label": label_text,
                        "state": "verified",
                        "receipt": manifest["transaction_id"],
                    }
                )

    type_counts = Counter(str(row.get("event_type") or "other") for row in ordered)
    return {
        "project_ref": project_ref,
        "derived_fields": derived_fields,
        "event_summary": {
            "count": len(ordered),
            "confirmed_count": sum(row.get("status") == "confirmed" for row in ordered),
            "event_type_counts": dict(sorted(type_counts.items())),
            "first_canonical_time": ordered[0].get("canonical_time"),
            "last_canonical_time": ordered[-1].get("canonical_time"),
            "event_ids": event_ids,
            "closure_verified": closure_verified,
        },
        "facts": [
            {
                "canonical_key": f"event-ledger:{manifest['transaction_id']}:{project_ref}",
                "summary": latest_update,
                "impact": "项目事实投影从手写摘要切换为可重建 Event 证据。",
                "observed_at": manifest.get("written_at", ""),
                "certainty": "locally_verified",
                "sources": [
                    {
                        "kind": "event_ledger_manifest",
                        "ref": manifest["transaction_id"],
                        "path": str(manifest.get("write_receipt", {}).get("canonical_path") or ""),
                        "label": "Library 多人 Event 正本",
                    }
                ],
            }
        ],
        "milestone_updates": milestone_updates,
        "unknowns": unknowns,
        "superseded_registry_unknowns": superseded,
        "action_hint": (
            "event_fact_link_complete"
            if all_confirmed and closure_verified
            else "event_fact_review_required"
        ),
    }


def compile_state(
    repo_root: Path,
    event_ledger_root: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    event_ledger_root = Path(event_ledger_root).resolve() if event_ledger_root else (
        repo_root.parents[1] / "Library" / "SoT_Owner" / "案例" / "_事件账"
    )
    output_path = Path(output_path) if output_path else repo_root / STATE_REL
    registry_path = repo_root / REGISTRY_REL
    registry = _read_json(registry_path)
    if registry.get("schema") != REGISTRY_SCHEMA or not isinstance(registry.get("projects"), list):
        raise ProjectionError(f"registry must use {REGISTRY_SCHEMA}")
    registered = {
        str(row.get("project_ref") or ""): row
        for row in registry["projects"]
        if isinstance(row, dict) and row.get("project_ref")
    }
    manifest, rows = _verify_ledger(event_ledger_root)
    events = rows["events.jsonl"]
    event_ids = [str(row.get("event_id") or "") for row in events]
    if not all(event_ids) or len(set(event_ids)) != len(event_ids):
        raise ProjectionError("Event ledger contains missing or duplicate event_id")
    unknown_refs = sorted(
        {
            str(row.get("project_ref"))
            for row in events
            if row.get("project_ref") and row.get("project_ref") not in registered
        }
    )
    if unknown_refs:
        raise ProjectionError(f"Event ledger references unregistered projects: {unknown_refs}")
    sources = {row["source_id"]: row for row in rows["source-pointers.jsonl"]}
    relations = rows["source-relations.jsonl"]

    state_rows = []
    for project_ref, project in sorted(registered.items()):
        project_events = [row for row in events if row.get("project_ref") == project_ref]
        if not project_events:
            continue
        closure = _verified_closure(
            project_ref,
            {row["event_id"] for row in project_events},
            sources,
            relations,
        )
        state_rows.append(_project_state(project, project_events, closure, manifest))

    manifest_path = event_ledger_root / "manifest.json"
    payload = {
        "schema": STATE_SCHEMA,
        "generated_at": manifest.get("written_at", ""),
        "generator": "project_state_projection.py",
        "source": {
            "event_ledger_manifest_path": str(manifest_path),
            "event_ledger_transaction_id": manifest["transaction_id"],
            "event_ledger_manifest_sha256": _sha256_file(manifest_path),
            "registry_path": str(registry_path),
            "registry_sha256": _sha256_file(registry_path),
        },
        "projects": state_rows,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    changed = _atomic_write_if_changed(output_path, text)
    return {
        "ok": True,
        "schema": STATE_SCHEMA,
        "output": str(output_path),
        "changed": changed,
        "project_count": len(state_rows),
        "event_count": sum(row["event_summary"]["count"] for row in state_rows),
        "transaction_id": manifest["transaction_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--event-ledger-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compile_state(args.repo_root, args.event_ledger_root, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
