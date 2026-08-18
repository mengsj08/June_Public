"""Deployment-configured identities for human and automation roles."""

from __future__ import annotations

import re


ROLE_NAMES = ("owner", "operator", "reviewer")


def _actor(value: object, fallback: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", candidate) else fallback


def normalize_roles(value: object) -> dict[str, dict[str, str]]:
    source = value if isinstance(value, dict) else {}
    roles: dict[str, dict[str, str]] = {}
    for name in ROLE_NAMES:
        item = source.get(name) if isinstance(source.get(name), dict) else {}
        roles[name] = {
            "actor": _actor(item.get("actor"), name),
            "member": str(item.get("member") or "").strip(),
        }
    return roles


def actor_for_role(roles: object, role: str) -> str:
    normalized = normalize_roles(roles)
    name = role if role in normalized else "operator"
    return normalized[name]["actor"]


def member_for_role(roles: object, role: str) -> str:
    normalized = normalize_roles(roles)
    name = role if role in normalized else "operator"
    return normalized[name]["member"]


def actor_for_member(roles: object, member: object) -> str:
    target = str(member or "").strip()
    if not target:
        return ""
    for item in normalize_roles(roles).values():
        if item["member"] == target:
            return item["actor"]
    return ""
