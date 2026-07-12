"""BigApple package discovery. Publishing is deliberately excluded."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from .capabilities import capability
from .local_ecosystem import LocalSkillRecord, skill_records, state_payload

STAMP="2026-07-12T00:00:00+08:00"; REF="evidence/bigapple-local-discovery.md"
class BigAppleAdapter:
    ecosystem="bigapple"
    CAPABILITIES={name:capability(level,REF,STAMP) for name,level in {"discover":"read_only","read_state":"read_only","set_enabled":"unsupported","install":"unknown","uninstall":"unknown","publish":"unsupported","refresh_events":"unsupported","resolve_plugin_parent":"unsupported"}.items()}
    def __init__(self, home: Path | str | None=None) -> None:
        self.home=Path(home or os.environ.get("BIGAPPLE_HOME","~/.bigapple")).expanduser()
    def discover(self, context_roots: list[str] | None=None) -> list[LocalSkillRecord]:
        roots=[(self.home/"codex-home"/"skills","user","filesystem-fallback")]
        roots += [(Path(root)/".bigapple"/"skills","repo","filesystem-fallback") for root in context_roots or []]
        return skill_records(self.ecosystem,roots)
    def read_state(self, native_id: str | None=None, context_roots: list[str] | None=None) -> dict[str,Any]:
        return state_payload(self.ecosystem,self.discover(context_roots),self.CAPABILITIES)
