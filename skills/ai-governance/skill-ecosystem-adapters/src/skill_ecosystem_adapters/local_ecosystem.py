"""Read-only filesystem primitives for local skill ecosystems."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class LocalSkillRecord:
    name: str
    path: str
    scope: str
    actual_state: str
    actual_state_source: str
    native_parent_id: str | None = None
    ecosystem: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def skill_records(ecosystem: str, roots: Iterable[tuple[Path, str, str]], limit: int = 500) -> list[LocalSkillRecord]:
    records: list[LocalSkillRecord] = []
    seen: set[Path] = set()
    for root, scope, source in roots:
        if not root.is_dir():
            continue
        for manifest in sorted(root.glob("*/SKILL.md")) + sorted(root.glob("*/*/SKILL.md")):
            directory = manifest.parent.resolve()
            if directory in seen:
                continue
            seen.add(directory)
            records.append(LocalSkillRecord(directory.name, str(directory), scope, "installed", source, ecosystem=ecosystem))
            if len(records) >= limit:
                return records
    return records


def state_payload(ecosystem: str, records: list[LocalSkillRecord], capabilities: dict[str, Any]) -> dict[str, Any]:
    return {"ecosystem": ecosystem, "status": "current", "observedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "records": [row.as_dict() for row in records], "capabilities": capabilities}
