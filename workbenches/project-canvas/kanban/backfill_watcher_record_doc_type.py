#!/usr/bin/env python3
"""Safely normalize task-card ``doc_type`` metadata.

KAN-1264 deliberately keeps this maintenance path outside scan-docs.py.  The
selector is conservative, dry-run is the default, and apply writes exactly one
frontmatter line with an atomic same-directory ``os.replace``.  In particular,
it never calls ``update_frontmatter_field`` and never refreshes ``updated`` or
``status_changed_at``.

KAN-1275 extends the same mechanism with two explicit batches: a reviewed,
fail-closed title-candidate allowlist for ``doc_type: record`` and removal of
redundant ``doc_type: task`` declarations.  New or drifted title candidates are
reported as uncertain instead of being modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
DEFAULT_SCAN_DIRS = (
    "project/个人调度",
    "project/场景库运营",
    "project/研究方法咨询",
)
TERMINAL_STATUSES = {"done", "archived", "cancelled", "canceled"}
DAILY_ACTIVE_STATUSES = {"todo", "in-progress", "review"}
HUMAN_SCOPES = {"owner", "human", "decision", "acceptance"}
TRUTHY = {"1", "true", "yes", "y", "on"}
NORTH_STAR_RELATIONS = {"direct", "support"}
TITLE_RE = re.compile(r"^Conversation Map 自动生成记录 — .+$")
TITLE_CANDIDATE_RE = re.compile(r"记录|补记")
STRONG_RECORD_TITLE_RE = re.compile(r"(?:记录卡?|补记)[）)]?(?:\s*$|\s*[—–-]\s*)")
RETROSPECTIVE_BODY_RE = re.compile(
    r"账外执行|补(?:账|记|记录|卡)|Conversation Map 拆账时发现|"
    r"本卡(?:只|仅|是|补)[^\n]*(?:记录|保存|承载|补|发生)|"
    r"不是新的?执行任务|历史(?:事实|记录)|本记录卡|当时没有[^\n]*(?:卡|承接)|"
    r"记录已发生|只记录历史事实",
    re.IGNORECASE,
)
PHASE_A_ALLOWLIST = frozenset({
    "CHN-11",
    "GOV-108", "GOV-109", "GOV-110", "GOV-391", "GOV-392", "GOV-393", "GOV-394", "GOV-87",
    "KAN-1051", "KAN-1052", "KAN-1067", "KAN-1129", "KAN-192", "KAN-195", "KAN-198",
    "KAN-205", "KAN-206", "KAN-796", "KAN-798", "KAN-800", "KAN-833",
    "KMO-103", "KMO-104", "KMO-105", "KMO-122", "KMO-35", "KMO-54", "KMO-55", "KMO-58",
    "KMO-66", "KMO-67", "KMO-68", "KMO-69", "KMO-70", "KMO-71", "KMO-72", "KMO-73",
    "KMO-74", "KMO-75", "KMO-76", "KMO-77", "KMO-78", "KMO-79", "KMO-80", "KMO-81",
    "KMO-82", "KMO-83", "KMO-89", "KMO-90", "KMO-91", "KMO-93", "KMO-94", "KMO-95",
    "RSH-12",
    "SKL-14", "SKL-15", "SKL-16", "SKL-17", "SKL-18", "SKL-22", "SKL-23", "SKL-28",
    "SKL-30", "SKL-31", "SKL-32", "SKL-33", "SKL-37", "SKL-79",
})
PHASE_A_EXPLICIT_EXCLUSIONS = {
    "KAN-9": "explicit_false_positive:feature_task_about_record_routing",
    "KAN-174": "explicit_false_positive:execution_task_with_backfill_subtask",
}
PHASE_A_UNCERTAIN = {
    "CHN-10": "body_has_unchecked_acceptance_and_follow_up",
    "KAN-166": "body_retains_three_month_observation_todo",
    "KMO-39": "body_has_unchecked_follow_up",
    "KMO-92": "body_declares_open_follow_up",
}
EXCLUDED_SOURCE_PREFIXES = (
    "skill-board/",
    "infoops/",
    "codex-thread/",
    "derived/",
    "conversation-map/",
    "team-kanban/",
    "meeting-chain/",
)
PRE_EXEC_GATE_RE = re.compile(
    r"通过后\s*派|通过后[^，。；;]*执行|待\s*PI\s*审核方案|重点拍板|PI\s*决策点|"
    r"拍板[^，。；;]*执行|方案[^，。；;]*通过后",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Card:
    path: Path
    relative_path: str
    raw: bytes
    fields: dict[str, str]
    raw_fields: dict[str, bytes]
    close_index: int
    newline: bytes


def _line_value(value: str) -> str:
    return value.strip().strip("'\"")


def parse_card(path: Path, repo_root: Path) -> Card | None:
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        return None
    close_line = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip(b"\r\n") == b"---"),
        None,
    )
    if close_line is None:
        return None
    fields: dict[str, str] = {}
    raw_fields: dict[str, bytes] = {}
    for line in lines[1:close_line]:
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", text)
        if not match:
            continue
        fields[match.group(1)] = _line_value(match.group(2))
        raw_fields[match.group(1)] = line
    close_index = sum(len(line) for line in lines[:close_line])
    newline = b"\r\n" if lines[0].endswith(b"\r\n") else b"\n"
    return Card(
        path=path,
        relative_path=path.relative_to(repo_root).as_posix(),
        raw=raw,
        fields=fields,
        raw_fields=raw_fields,
        close_index=close_index,
        newline=newline,
    )


def _read_config(repo_root: Path) -> dict:
    for name in (".kanban.config.json", ".kanban.config.example.json"):
        path = repo_root / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def configured_scan_dirs(repo_root: Path, config: dict | None = None) -> list[Path]:
    config = config if isinstance(config, dict) else _read_config(repo_root)
    raw = config.get("scan_dirs") if isinstance(config.get("scan_dirs"), list) else DEFAULT_SCAN_DIRS
    result = []
    for value in raw:
        path = Path(os.path.expanduser(str(value)))
        result.append(path.resolve() if path.is_absolute() else (repo_root / path).resolve())
    return result


def iter_cards(repo_root: Path, config: dict | None = None) -> Iterable[Card]:
    for directory in configured_scan_dirs(repo_root, config):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            card = parse_card(path, repo_root)
            if card is not None:
                yield card


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def _excluded_source_prefix(source: str) -> str | None:
    lowered = source.strip().lower()
    return next((prefix for prefix in EXCLUDED_SOURCE_PREFIXES if lowered.startswith(prefix)), None)


def exclusion_reasons(card: Card) -> list[str]:
    fields = card.fields
    reasons = []
    if not fields.get("task_id", "").strip():
        reasons.append("missing_task_id")
    status_value = fields.get("status", "").strip().lower()
    if status_value not in TERMINAL_STATUSES:
        reasons.append(f"non_terminal_status:{status_value or '<missing>'}")
    scope = (fields.get("attention_scope") or fields.get("audience") or "").strip().lower()
    responsibility = fields.get("responsibility", "").strip().lower()
    assignee = fields.get("assignee", "").strip().lower()
    if _truthy(fields.get("human_gate")):
        reasons.append("human_gate:true")
    if responsibility == "pi-gated":
        reasons.append("pi_gate:responsibility")
    if assignee in {"owner", "pi"}:
        reasons.append(f"human_assignee:{assignee}")
    if scope in HUMAN_SCOPES:
        reasons.append(f"human_attention_scope:{scope}")
    source = fields.get("source", "").strip()
    excluded_prefix = _excluded_source_prefix(source)
    if excluded_prefix:
        reasons.append(f"excluded_source_prefix:{excluded_prefix}")
    if not source.lower().startswith("archive-map-watcher/"):
        reasons.append("source_not_archive_map_watcher")
    title = fields.get("title", "").strip()
    if not TITLE_RE.fullmatch(title):
        reasons.append("title_not_watcher_standard_template")
    if "doc_type" in fields:
        value = fields.get("doc_type", "")
        reasons.append(f"doc_type_already_present:{value or '<empty>'}")
    return reasons


def select_cards(repo_root: Path, config: dict | None = None) -> tuple[list[Card], list[dict]]:
    selected = []
    exclusions = []
    for card in iter_cards(repo_root, config):
        reasons = exclusion_reasons(card)
        if not reasons:
            selected.append(card)
        else:
            exclusions.append({
                "path": card.relative_path,
                "task_id": card.fields.get("task_id") or None,
                "source": card.fields.get("source") or None,
                "reasons": reasons,
            })
    return selected, exclusions


def _body_text(card: Card) -> str:
    lines = card.raw.splitlines(keepends=True)
    close_line = next(
        index for index, line in enumerate(lines[1:], start=1) if line.rstrip(b"\r\n") == b"---"
    )
    return b"".join(lines[close_line + 1 :]).decode("utf-8", errors="strict")


def title_candidate_cards(repo_root: Path, config: dict | None = None) -> list[Card]:
    return [
        card for card in iter_cards(repo_root, config)
        if "doc_type" not in card.fields
        and TITLE_CANDIDATE_RE.search(card.fields.get("title", ""))
    ]


def _phase_a_invariant_reasons(card: Card) -> list[str]:
    fields = card.fields
    reasons = []
    task_id = fields.get("task_id", "").strip()
    if not task_id:
        reasons.append("missing_task_id")
    status_value = fields.get("status", "").strip().lower()
    if status_value not in TERMINAL_STATUSES:
        reasons.append(f"non_terminal_status:{status_value or '<missing>'}")
    scope = (fields.get("attention_scope") or fields.get("audience") or "").strip().lower()
    responsibility = fields.get("responsibility", "").strip().lower()
    assignee = fields.get("assignee", "").strip().lower()
    if _truthy(fields.get("human_gate")):
        reasons.append("human_gate:true")
    if scope in HUMAN_SCOPES:
        reasons.append(f"human_attention_scope:{scope}")
    if responsibility in {"pi-gated", "human-gated", "owner-gated"}:
        reasons.append(f"human_gate:responsibility:{responsibility}")
    if assignee in {"owner", "pi"}:
        reasons.append(f"human_assignee:{assignee}")
    title = fields.get("title", "").strip()
    if not STRONG_RECORD_TITLE_RE.search(title):
        reasons.append("title_not_strong_record_phrase")
    body = _body_text(card)
    if not RETROSPECTIVE_BODY_RE.search(body):
        reasons.append("body_missing_explicit_retrospective_declaration")
    return reasons


def classify_phase_a(repo_root: Path, config: dict | None = None) -> dict:
    backfill = []
    excluded = []
    uncertain = []
    for card in title_candidate_cards(repo_root, config):
        task_id = card.fields.get("task_id", "").strip()
        row = {
            "path": card.relative_path,
            "task_id": task_id or None,
            "title": card.fields.get("title") or None,
            "status": card.fields.get("status") or None,
        }
        invariant_reasons = _phase_a_invariant_reasons(card)
        body_reason = "body_missing_explicit_retrospective_declaration"
        hard_reasons = [reason for reason in invariant_reasons if reason != body_reason]
        explicit_reason = PHASE_A_EXPLICIT_EXCLUSIONS.get(task_id)
        if explicit_reason:
            excluded.append({**row, "reasons": [explicit_reason, *invariant_reasons]})
        elif hard_reasons:
            excluded.append({**row, "reasons": invariant_reasons})
        elif task_id in PHASE_A_UNCERTAIN:
            uncertain.append({
                **row,
                "reasons": [PHASE_A_UNCERTAIN[task_id], *([body_reason] if body_reason in invariant_reasons else [])],
            })
        elif body_reason in invariant_reasons:
            uncertain.append({**row, "reasons": [body_reason]})
        elif task_id not in PHASE_A_ALLOWLIST:
            uncertain.append({**row, "reasons": ["not_in_reviewed_allowlist"]})
        else:
            backfill.append({**row, "old_value": None, "new_value": "record"})
    return {
        "candidate_count": len(backfill) + len(excluded) + len(uncertain),
        "backfill": backfill,
        "excluded": excluded,
        "uncertain": uncertain,
    }


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _field_proof(card: Card, after: Card, field: str) -> dict:
    before_raw = card.raw_fields.get(field)
    after_raw = after.raw_fields.get(field)
    return {
        "before": before_raw.decode("utf-8").rstrip("\r\n") if before_raw is not None else None,
        "after": after_raw.decode("utf-8").rstrip("\r\n") if after_raw is not None else None,
        "byte_equal": before_raw == after_raw,
        "sha256": _sha256(before_raw) if before_raw is not None else None,
    }


def _atomic_add_doc_type(card: Card, repo_root: Path) -> dict:
    inserted = b"doc_type: record" + card.newline
    expected = card.raw[: card.close_index] + inserted + card.raw[card.close_index :]
    original_mode = stat.S_IMODE(card.path.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{card.path.name}.tmp-", dir=card.path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, card.path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    after = parse_card(card.path, repo_root)
    if after is None:
        raise RuntimeError(f"frontmatter disappeared after write: {card.relative_path}")
    proof = {
        "path": card.relative_path,
        "task_id": card.fields.get("task_id"),
        "old_value": None,
        "new_value": "record",
        "before_sha256": _sha256(card.raw),
        "after_sha256": _sha256(after.raw),
        "only_expected_line_added": after.raw == expected,
        "byte_length_delta": len(after.raw) - len(card.raw),
        "updated": _field_proof(card, after, "updated"),
        "status_changed_at": _field_proof(card, after, "status_changed_at"),
    }
    if not proof["only_expected_line_added"]:
        raise RuntimeError(f"unexpected byte diff after write: {card.relative_path}")
    if not proof["updated"]["byte_equal"] or not proof["status_changed_at"]["byte_equal"]:
        raise RuntimeError(f"protected timestamp changed: {card.relative_path}")
    return proof


def _atomic_remove_doc_type_task(card: Card, repo_root: Path) -> dict:
    raw_line = card.raw_fields.get("doc_type")
    if raw_line is None or card.fields.get("doc_type", "").strip().lower() != "task":
        raise RuntimeError(f"expected doc_type: task: {card.relative_path}")
    frontmatter = card.raw[: card.close_index]
    if frontmatter.count(raw_line) != 1:
        raise RuntimeError(f"ambiguous doc_type line: {card.relative_path}")
    line_start = frontmatter.index(raw_line)
    expected = card.raw[:line_start] + card.raw[line_start + len(raw_line) :]
    original_mode = stat.S_IMODE(card.path.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{card.path.name}.tmp-", dir=card.path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, card.path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    after = parse_card(card.path, repo_root)
    if after is None:
        raise RuntimeError(f"frontmatter disappeared after write: {card.relative_path}")
    proof = {
        "path": card.relative_path,
        "task_id": card.fields.get("task_id"),
        "old_value": "task",
        "new_value": None,
        "before_sha256": _sha256(card.raw),
        "after_sha256": _sha256(after.raw),
        "only_expected_line_removed": after.raw == expected,
        "byte_length_delta": len(after.raw) - len(card.raw),
        "removed_line": raw_line.decode("utf-8").rstrip("\r\n"),
        "updated": _field_proof(card, after, "updated"),
        "status_changed_at": _field_proof(card, after, "status_changed_at"),
    }
    if not proof["only_expected_line_removed"]:
        raise RuntimeError(f"unexpected byte diff after write: {card.relative_path}")
    if not proof["updated"]["byte_equal"] or not proof["status_changed_at"]["byte_equal"]:
        raise RuntimeError(f"protected timestamp changed: {card.relative_path}")
    return proof


def build_backfill_report(repo_root: Path, *, apply: bool, config: dict | None = None) -> dict:
    selected, exclusions = select_cards(repo_root, config)
    changes = [{
        "path": card.relative_path,
        "task_id": card.fields.get("task_id"),
        "old_value": None,
        "new_value": "record",
    } for card in selected]
    proofs = [_atomic_add_doc_type(card, repo_root) for card in selected] if apply else []
    reason_counts = Counter(reason for row in exclusions for reason in row["reasons"])
    prefix_counts = {
        prefix: reason_counts.get(f"excluded_source_prefix:{prefix}", 0)
        for prefix in EXCLUDED_SOURCE_PREFIXES
    }
    return {
        "mode": "apply" if apply else "dry-run",
        "repo_root": str(repo_root),
        "matched_count": len(selected),
        "changes": changes,
        "exclusion_count": len(exclusions),
        "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "excluded_source_prefix_counts": prefix_counts,
        "exclusions": exclusions,
        "write_proofs": proofs,
    }


def build_phase_a_report(repo_root: Path, *, apply: bool, config: dict | None = None) -> dict:
    decisions = classify_phase_a(repo_root, config)
    by_path = {card.relative_path: card for card in iter_cards(repo_root, config)}
    selected = [by_path[row["path"]] for row in decisions["backfill"]]
    proofs = [_atomic_add_doc_type(card, repo_root) for card in selected] if apply else []
    return {
        "batch": "phase-a-title-candidates",
        "mode": "apply" if apply else "dry-run",
        "repo_root": str(repo_root),
        "candidate_count": decisions["candidate_count"],
        "matched_count": len(selected),
        "decision_counts": {
            "backfill": len(decisions["backfill"]),
            "excluded": len(decisions["excluded"]),
            "uncertain": len(decisions["uncertain"]),
        },
        "decisions": decisions,
        "changes": decisions["backfill"],
        "write_proofs": proofs,
    }


def select_doc_type_task_cards(repo_root: Path, config: dict | None = None) -> list[Card]:
    return [
        card for card in iter_cards(repo_root, config)
        if card.fields.get("doc_type", "").strip().lower() == "task"
    ]


def build_phase_b_report(repo_root: Path, *, apply: bool, config: dict | None = None) -> dict:
    selected = select_doc_type_task_cards(repo_root, config)
    changes = [{
        "path": card.relative_path,
        "task_id": card.fields.get("task_id"),
        "old_value": "task",
        "new_value": None,
    } for card in selected]
    proofs = [_atomic_remove_doc_type_task(card, repo_root) for card in selected] if apply else []
    return {
        "batch": "phase-b-normalize-task",
        "mode": "apply" if apply else "dry-run",
        "repo_root": str(repo_root),
        "matched_count": len(selected),
        "changes": changes,
        "write_proofs": proofs,
    }


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _task_ref(task: dict) -> str:
    return str(task.get("path") or task.get("task_id") or task.get("legacy_id") or "").strip()


def _routing_text(task: dict) -> str:
    tags = task.get("tags") or ""
    if isinstance(tags, list):
        tags = " ".join(str(item) for item in tags)
    return " ".join(str(task.get(key) or "") for key in (
        "next_action", "title", "display_title", "task_id", "source"
    )) + " " + str(tags)


def _auto_accept_eligible(task: dict) -> bool:
    return (
        str(task.get("responsibility") or "").strip().lower() == "ai-owned"
        and str(task.get("safety") or "").strip().lower() in {"read-only", "reversible"}
        and not _truthy(task.get("human_gate"))
        and not PRE_EXEC_GATE_RE.search(_routing_text(task))
    )


def _parse_date(value) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _refs(tasks: Iterable[dict]) -> list[str]:
    return sorted(ref for ref in (_task_ref(task) for task in tasks) if ref)


def build_six_collection_snapshot(repo_root: Path, config: dict | None = None) -> dict:
    """Capture the six KAN-1264 membership sets with current-worktree rules."""
    config = config if isinstance(config, dict) else _read_config(repo_root)
    cards = list(iter_cards(repo_root, config))
    tasks = []
    for card in cards:
        task = dict(card.fields)
        task["path"] = card.relative_path
        task["project"] = card.path.parent.name
        tasks.append(task)

    kanban_dir = repo_root / "shared" / "toolkit" / "kanban"
    if str(kanban_dir) not in sys.path:
        sys.path.insert(0, str(kanban_dir))
    attention = _load_module("kan1264_attention_gate_attention", kanban_dir / "attention_gate_attention.py")
    sys.modules["attention_gate_attention"] = attention
    summary = _load_module("kan1264_attention_gate_summary", kanban_dir / "attention_gate_summary.py")
    is_record = attention.is_backstage_record

    activity_lanes = [task for task in tasks if str(task.get("status") or "todo") != "done" and not is_record(task)]
    summary_active = summary._console_active_for_owner(tasks, "Owner")
    summary_needs = [task for task in summary_active if summary._is_review_task(task, "Owner")]
    summary_pending = [task for task in summary_active if summary._is_inbox_task(task) and summary._is_owner_decision_task(task, "Owner")]
    ai_members = set(str(item).strip() for item in (config.get("ai_members") or []) if str(item).strip())
    summary_running = [
        task for task in summary_active
        if summary._status(task) == "in-progress" and summary._assignee(task) in ai_members
    ]
    summary_recent = summary._recent_done_tasks(tasks, today=date.today())

    daily_active = [
        task for task in tasks
        if str(task.get("status") or "todo") in DAILY_ACTIVE_STATUSES and not is_record(task)
    ]
    daily_reviews = [
        task for task in tasks
        if str(task.get("status") or "") == "review"
        and not is_record(task)
        and not PRE_EXEC_GATE_RE.search(_routing_text(task))
    ]
    today_text = date.today().isoformat()
    daily_due = [task for task in daily_active if str(task.get("due_date") or "") == today_text]
    daily_overdue = [
        task for task in daily_active
        if str(task.get("due_date") or "") and str(task.get("due_date")) < today_text
    ]
    daily_board = [
        task for task in tasks
        if str(task.get("responsibility") or "").lower() == "pi-gated"
        and str(task.get("status") or "") in {"todo", "in-progress"}
        and (not task.get("assignee") or task.get("assignee") == "Owner")
        and not is_record(task)
    ]

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    north_star = [
        task for task in tasks
        if (created := _parse_date(task.get("created"))) is not None
        and week_start <= created <= week_end
        and str(task.get("north_star_relation") or "").strip().lower() in NORTH_STAR_RELATIONS
    ]
    auto_accept = [
        task for task in tasks
        if str(task.get("status") or "").strip().lower() == "review" and _auto_accept_eligible(task)
    ]
    active_records = [task for task in tasks if str(task.get("status") or "todo") != "done" and is_record(task)]

    collections = {
        "activity_lanes": _refs(activity_lanes),
        "attention_gate_summary": {
            "active": _refs(summary_active),
            "needs_me": _refs(summary_needs),
            "pending_decisions": _refs(summary_pending),
            "ai_running": _refs(summary_running),
            "recent_done": sorted(str(item.get("task_id") or "") for item in summary_recent),
        },
        "daily_reminder": {
            "active": _refs(daily_active),
            "reviews": _refs(daily_reviews),
            "due_today": _refs(daily_due),
            "overdue": _refs(daily_overdue),
            "board": _refs(daily_board),
        },
        "north_star": _refs(north_star),
        "auto_accept_candidates": _refs(auto_accept),
        "active_records": _refs(active_records),
    }
    return {
        "snapshot_date": today.isoformat(),
        "rules": {
            "record_classifier": "current-worktree attention_gate_attention.is_backstage_record",
            "activity_lanes": "render-board.js: status !== done && !isConsoleRecordTask",
            "attention_gate_summary": "current-worktree attention_gate_summary helpers",
            "daily_reminder": "current-worktree daily reminder predicates",
            "north_star": f"created in {week_start.isoformat()}..{week_end.isoformat()} and north_star_relation direct|support",
            "auto_accept_candidates": "scan-docs.py _is_auto_acceptance_eligible contract",
            "active_records": "render-board.js: status !== done && isConsoleRecordTask",
        },
        "collections": collections,
        "counts": _collection_counts(collections),
    }


def _collection_counts(value):
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return {key: _collection_counts(item) for key, item in value.items()}
    raise TypeError(f"unsupported collection value: {type(value)!r}")


def _compare_collection(before, after):
    if isinstance(before, list) and isinstance(after, list):
        return {
            "equal": before == after,
            "before_count": len(before),
            "after_count": len(after),
            "added": sorted(set(after) - set(before)),
            "removed": sorted(set(before) - set(after)),
        }
    if isinstance(before, dict) and isinstance(after, dict):
        rows = {key: _compare_collection(before.get(key, []), after.get(key, [])) for key in sorted(set(before) | set(after))}
        return {"equal": all(row["equal"] for row in rows.values()), "members": rows}
    return {"equal": False, "before": before, "after": after}


def compare_snapshot(before_path: Path, current: dict) -> dict:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    comparison = _compare_collection(before.get("collections", {}), current.get("collections", {}))
    return {
        "equal": comparison["equal"],
        "before_snapshot": str(before_path),
        "comparison": comparison,
        "current_counts": current["counts"],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--batch",
        choices=("watcher", "phase-a", "phase-b"),
        default="watcher",
        help="metadata batch to report/apply (default keeps the KAN-1264 watcher behavior)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report exact changes and exclusions without writing (default)")
    mode.add_argument("--apply", action="store_true", help="atomically apply the selected metadata batch")
    mode.add_argument("--snapshot", type=Path, help="write the six-collection membership snapshot")
    mode.add_argument("--compare-snapshot", type=Path, help="compare current six collections with a saved snapshot")
    parser.add_argument("--report-out", type=Path, help="also write the emitted JSON report")
    args = parser.parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    config = _read_config(repo_root)
    if args.snapshot:
        payload = build_six_collection_snapshot(repo_root, config)
        _write_json(args.snapshot.expanduser().resolve(), payload)
        payload = {**payload, "snapshot_path": str(args.snapshot.expanduser().resolve())}
    elif args.compare_snapshot:
        current = build_six_collection_snapshot(repo_root, config)
        payload = compare_snapshot(args.compare_snapshot.expanduser().resolve(), current)
    else:
        if args.batch == "phase-a":
            payload = build_phase_a_report(repo_root, apply=args.apply, config=config)
        elif args.batch == "phase-b":
            payload = build_phase_b_report(repo_root, apply=args.apply, config=config)
        else:
            payload = build_backfill_report(repo_root, apply=args.apply, config=config)
    if args.report_out:
        _write_json(args.report_out.expanduser().resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.compare_snapshot and not payload["equal"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
