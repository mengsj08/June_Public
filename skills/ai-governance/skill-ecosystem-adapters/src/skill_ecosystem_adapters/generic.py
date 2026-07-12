"""Read-only filesystem adapter for ecosystems without a native adapter."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .capabilities import capability
from .local_ecosystem import LocalSkillRecord, skill_records


_NO_CONTROL = "generic filesystem adapter has no native control surface"


class GenericAdapter:
    """Inventory SKILL.md files for an arbitrary named ecosystem."""

    def __init__(
        self,
        ecosystem: str,
        roots: Iterable[tuple[Path | str, str, str]],
    ) -> None:
        if not ecosystem:
            raise ValueError("ecosystem is required")
        self.ecosystem = ecosystem
        self.roots = [(Path(path).expanduser(), scope, note) for path, scope, note in roots]
        evidence = "; ".join(
            f"{path} ({scope}: {note})" for path, scope, note in self.roots
        ) or "no scan roots configured"
        levels = {
            "discover": "read_only",
            "read_state": "read_only",
            "set_enabled": "unsupported",
            "install": "unknown",
            "uninstall": "unknown",
            "publish": "unsupported",
            "refresh_events": "unknown",
            "resolve_plugin_parent": "unsupported",
        }
        self.CAPABILITIES = {
            name: capability(level, evidence if level == "read_only" else _NO_CONTROL)
            for name, level in levels.items()
        }
        for name, value in self.CAPABILITIES.items():
            if levels[name] not in {"read_only"}:
                value["reason"] = _NO_CONTROL

    def discover(self, context_roots: list[str] | None = None) -> list[LocalSkillRecord]:
        del context_roots
        return skill_records(self.ecosystem, self.roots)

    def read_state(
        self, native_id: str | None = None, context_roots: list[str] | None = None
    ) -> dict[str, Any]:
        records = self.discover(context_roots)
        payload: dict[str, Any] = {
            "ecosystem": self.ecosystem,
            "records": [
                {"name": row.name, "path": row.path, "exists": True, "scope": row.scope}
                for row in records
            ],
            "capabilities": self.CAPABILITIES,
        }
        if native_id is not None:
            matches = [row for row in records if row.name == native_id or row.path == native_id]
            payload.update(
                native_id=native_id,
                exists=bool(matches),
                scopes=sorted({row.scope for row in matches}),
            )
        return payload
