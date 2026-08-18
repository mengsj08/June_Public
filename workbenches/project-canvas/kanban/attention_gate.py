"""Neutral, role-based attention routing used by the public core."""

from __future__ import annotations


TERMINAL_STATUSES = {"done", "completed", "archived", "cancelled", "canceled"}
BACKSTAGE_DOC_TYPES = {"record", "receipt", "log", "ledger", "pointer"}


def _text(value: object) -> str:
    return str(value or "").strip().lower()


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value) in {"1", "true", "yes", "on"}


def is_backstage_record(task: object) -> bool:
    if not isinstance(task, dict):
        return False
    return (
        _text(task.get("doc_type")) in BACKSTAGE_DOC_TYPES
        or _text(task.get("attention_scope")) == "backstage"
        or _text(task.get("audience")) == "backstage"
    )


def requires_role_action(task: object, role: str = "owner") -> bool:
    """Return whether an active card explicitly enters a configured human role gate."""
    if not isinstance(task, dict) or is_backstage_record(task):
        return False
    if _text(task.get("status")) in TERMINAL_STATUSES:
        return False
    role = _text(role) or "owner"
    scope = _text(task.get("attention_scope"))
    responsibility = _text(task.get("responsibility"))
    assignee = _text(task.get("assignee"))
    return (
        scope in {role, "human", "pi"}
        or responsibility in {f"{role}-gated", "human-gated", "pi-gated"}
        or (_truthy(task.get("human_gate")) and assignee in {"", role})
    )
