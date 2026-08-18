#!/usr/bin/env python3
"""Compile project unknowns into auditable, task-bound action routing.

This module never creates cards or executes business work.  It answers the
smaller governance question first: can a project gap reuse an existing task,
and is that task safe for backstage execution or already waiting at a real
Owner gate?
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


STATE_SCHEMA = "kanban-real-project-state/v1"
ACTION_SCHEMA = "kanban-project-actions/v1"
STATE_REL = Path("project/个人调度/.real-projects/project-state.generated.json")
ACTION_REL = Path("project/个人调度/.real-projects/project-actions.generated.json")
TERMINAL_STATUSES = {"done", "archived", "cancelled", "canceled"}
OWNER_SCOPES = {"owner", "human", "pi", "user"}
AUTO_SAFETY = {"reversible", "read-only", "readonly"}
EXCLUDED_PARTS = {".git", ".archive", "archive", "node_modules", "__pycache__"}


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


def _atomic_write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def _frontmatter_value(raw: str) -> Any:
    value = raw.strip().strip("'\"")
    if value.lower() in {"true", "yes", "on", "1"}:
        return True
    if value.lower() in {"false", "no", "off", "0"}:
        return False
    return value


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}
    fields: dict[str, Any] = {}
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line.strip())
        if match:
            fields[match.group(1)] = _frontmatter_value(match.group(2))
    return fields


def _scan_tasks(repo_root: Path) -> list[dict[str, Any]]:
    task_root = repo_root / "project"
    if not task_root.is_dir():
        return []
    tasks = []
    for path in sorted(task_root.rglob("*.md")):
        relative = path.relative_to(repo_root)
        if any(part in EXCLUDED_PARTS or part.startswith(".") for part in relative.parts):
            continue
        try:
            raw = path.read_bytes()
            fields = _parse_frontmatter(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        project_ref = str(fields.get("project_ref") or "").strip()
        task_id = str(fields.get("task_id") or "").strip()
        if not project_ref or not task_id:
            continue
        tasks.append({
            **fields,
            "project_ref": project_ref,
            "task_id": task_id,
            "path": relative.as_posix(),
            "sha256": _sha256_bytes(raw),
        })
    return tasks


def _task_rank(task: dict[str, Any]) -> tuple[int, int, int, str, str]:
    status = str(task.get("status") or "todo").lower()
    scope = str(task.get("attention_scope") or "").lower()
    human_gate = task.get("human_gate") is True or scope in OWNER_SCOPES
    return (
        0 if human_gate else 1,
        {"review": 0, "blocked": 1, "in_progress": 2, "todo": 3}.get(status, 4),
        {"high": 0, "medium": 1, "low": 2}.get(str(task.get("priority") or "medium").lower(), 1),
        str(task.get("updated") or ""),
        str(task.get("task_id") or ""),
    )


def _active_task(tasks: list[dict[str, Any]], project_ref: str) -> dict[str, Any] | None:
    linked = [
        task for task in tasks
        if task.get("project_ref") == project_ref
        and str(task.get("status") or "todo").lower() not in TERMINAL_STATUSES
    ]
    return sorted(linked, key=_task_rank)[0] if linked else None


def _task_route(task: dict[str, Any] | None) -> tuple[str, bool, str, str]:
    if not task:
        return (
            "unbound",
            False,
            "no_existing_task",
            "没有可复用的进行中任务；保持未绑定，不自动建卡。",
        )
    scope = str(task.get("attention_scope") or "").strip().lower()
    responsibility = str(task.get("responsibility") or "").strip().lower()
    next_action = str(task.get("next_action") or "").strip()
    if (
        task.get("human_gate") is True
        or scope in OWNER_SCOPES
        or responsibility in {"pi-gated", "human-gated", "owner-gated"}
        or next_action.lower().startswith("owner ")
    ):
        return (
            "requires_owner",
            False,
            "existing_task_human_gate",
            "现有任务已处于显式 Owner 人闸；复用该闸门并停止自动执行。",
        )
    safety = str(task.get("safety") or "").strip().lower()
    if scope == "backstage" and task.get("human_gate") is False and safety in AUTO_SAFETY:
        return (
            "ready_backstage",
            True,
            "existing_task_backstage_safe",
            "现有任务明确允许后台处理，且声明为本地可逆或只读工作。",
        )
    return (
        "requires_owner",
        False,
        "existing_task_not_auto_eligible",
        "现有任务未同时满足 backstage、非人闸和可逆/只读条件；不自动执行。",
    )


def _action_row(
    project_ref: str,
    unknown: str,
    task: dict[str, Any] | None,
    state_sha256: str,
    transaction_id: str,
) -> dict[str, Any]:
    routing_status, auto_allowed, reason_code, reason = _task_route(task)
    bound_task = None
    if task:
        bound_task = {
            key: task.get(key)
            for key in (
                "task_id", "title", "path", "sha256", "status", "priority",
                "responsibility", "human_gate", "attention_scope", "safety", "next_action",
            )
        }
    action_material = [
        project_ref,
        unknown,
        state_sha256,
        (bound_task or {}).get("task_id", ""),
        (bound_task or {}).get("sha256", ""),
    ]
    return {
        "action_id": "rpa_" + _sha256_bytes(
            json.dumps(action_material, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )[:20],
        "project_ref": project_ref,
        "trigger": {
            "kind": "project_unknown",
            "summary": unknown,
            "source_transaction": transaction_id,
        },
        "bound_task": bound_task,
        "routing_status": routing_status,
        "automatic_execution_allowed": auto_allowed,
        "reason_code": reason_code,
        "reason": reason,
        "attention_reused": routing_status == "requires_owner" and task is not None,
        "duplicate_card_created": False,
        "execution_performed": False,
        "next_action": str((task or {}).get("next_action") or ""),
        "escalation_conditions": [
            "decision_required",
            "external_action",
            "irreversible_change",
            "insufficient_evidence",
            "outside_existing_task_scope",
        ],
    }


def compile_actions(
    repo_root: Path,
    project_state_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    project_state_path = Path(project_state_path) if project_state_path else repo_root / STATE_REL
    output_path = Path(output_path) if output_path else repo_root / ACTION_REL
    state = _read_json(project_state_path)
    if state.get("schema") != STATE_SCHEMA or not isinstance(state.get("projects"), list):
        raise ProjectionError(f"project state must use {STATE_SCHEMA}")
    state_sha256 = _sha256_file(project_state_path)
    source = state.get("source") if isinstance(state.get("source"), dict) else {}
    transaction_id = str(source.get("event_ledger_transaction_id") or "")
    tasks = _scan_tasks(repo_root)
    actions = []
    for project in sorted(state["projects"], key=lambda row: str(row.get("project_ref") or "")):
        if not isinstance(project, dict):
            raise ProjectionError("project state contains a non-object row")
        project_ref = str(project.get("project_ref") or "").strip()
        if not project_ref:
            raise ProjectionError("project state contains an empty project_ref")
        task = _active_task(tasks, project_ref)
        for unknown in project.get("unknowns") or []:
            text = str(unknown).strip()
            if text:
                actions.append(_action_row(project_ref, text, task, state_sha256, transaction_id))

    counts = {
        "ready_backstage": sum(row["routing_status"] == "ready_backstage" for row in actions),
        "requires_owner": sum(row["routing_status"] == "requires_owner" for row in actions),
        "unbound": sum(row["routing_status"] == "unbound" for row in actions),
        "executed": sum(row["execution_performed"] is True for row in actions),
        "duplicate_cards_created": sum(row["duplicate_card_created"] is True for row in actions),
    }
    payload = {
        "schema": ACTION_SCHEMA,
        "generated_at": state.get("generated_at", ""),
        "generator": "project_action_projection.py",
        "source": {
            "project_state_path": str(project_state_path),
            "project_state_sha256": state_sha256,
            "event_ledger_transaction_id": transaction_id,
        },
        "actions": actions,
        "counts": counts,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    changed = _atomic_write_if_changed(output_path, text)
    return {
        "ok": True,
        "schema": ACTION_SCHEMA,
        "output": str(output_path),
        "changed": changed,
        "action_count": len(actions),
        "counts": counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--project-state", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compile_actions(args.repo_root, args.project_state, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
