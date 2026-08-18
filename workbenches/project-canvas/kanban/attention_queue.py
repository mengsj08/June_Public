#!/usr/bin/env python3
"""Read-only global/project attention queue projection for Canvas Studio."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


TERMINAL_STATUSES = {"done", "archived", "cancelled", "canceled"}
ACTIVE_STATUSES = {"in-progress", "in_progress", "doing", "running"}


def _text(value) -> str:
    return str(value or "").strip()


def _stamp(task: dict) -> str:
    return _text(task.get("updated") or task.get("status_changed_at") or task.get("created"))


def _public(task: dict) -> dict:
    return {
        "task_id": _text(task.get("task_id")),
        "title": _text(task.get("title") or task.get("display_title")),
        "next_action": _text(task.get("next_action")),
        "path": _text(task.get("path")),
        "status": _text(task.get("status") or "todo"),
        "assignee": _text(task.get("assignee")),
        "updated": _stamp(task),
        "project_ref": _text(task.get("project_ref")),
    }


def build_attention_queue(
    tasks, owner_action_needed, *, project="", record_classifier=None, now=None, handled_days=7
):
    """Return a compact queue; human-gate and record routing stay canonical."""
    rows = [task for task in tasks if isinstance(task, dict)]
    project = _text(project)
    if project:
        project_rows = [
            task for task in rows
            if _text(task.get("project_ref")) == project
            and not (record_classifier and record_classifier(task))
        ]
        needs_you = [_public(task) for task in project_rows if owner_action_needed(task)]
        processing = [
            _public(task) for task in project_rows
            if _text(task.get("status")).lower() in ACTIVE_STATUSES
            and not owner_action_needed(task)
        ]
        planned = [
            _public(task) for task in project_rows
            if _text(task.get("status") or "todo").lower() not in TERMINAL_STATUSES | ACTIVE_STATUSES
            and not owner_action_needed(task)
        ]
        other_projects_needs_you = sum(
            1 for task in rows
            if _text(task.get("project_ref"))
            and _text(task.get("project_ref")) != project
            and owner_action_needed(task)
        )
        sort_key = lambda row: (row.get("updated", ""), row.get("task_id", ""))
        needs_you.sort(key=sort_key, reverse=True)
        processing.sort(key=sort_key, reverse=True)
        planned.sort(key=sort_key, reverse=True)
        return {
            "ok": True,
            "scope": "project",
            "project": project,
            "counts": {
                "needs_you": len(needs_you),
                "processing": len(processing),
                "planned": len(planned),
                "other_projects_needs_you": other_projects_needs_you,
            },
            "needs_you": needs_you,
            "processing": processing,
            "planned": planned,
        }

    needs_you = [_public(task) for task in rows if owner_action_needed(task)]
    processing = [
        _public(task) for task in rows
        if _text(task.get("status")).lower() in ACTIVE_STATUSES
        and not owner_action_needed(task)
    ]
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=handled_days)

    def recently_handled(task):
        if _text(task.get("status")).lower() not in TERMINAL_STATUSES:
            return False
        try:
            stamp = datetime.fromisoformat(_stamp(task).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp >= cutoff
        except (TypeError, ValueError):
            return False

    handled = [_public(task) for task in rows if recently_handled(task)]
    sort_key = lambda row: (row.get("updated", ""), row.get("task_id", ""))
    needs_you.sort(key=sort_key, reverse=True)
    processing.sort(key=sort_key, reverse=True)
    handled.sort(key=sort_key, reverse=True)
    return {
        "ok": True,
        "scope": "global",
        "counts": {
            "needs_you": len(needs_you),
            "processing": len(processing),
            "handled": len(handled),
        },
        "needs_you": needs_you,
        "processing": processing,
        "handled": handled,
    }
