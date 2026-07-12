"""Intent and observation helpers for portable ecosystem reconciliation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .local_ecosystem import LocalSkillRecord

Intent = dict[str, str]
_DESIRED = frozenset({"default", "on-demand", "disabled"})


def load_intent(path: Path | str) -> Intent:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("intent must be a JSON object")
    intent = {str(key): str(desired) for key, desired in value.items()}
    invalid = {key: desired for key, desired in intent.items() if desired not in _DESIRED}
    if invalid:
        raise ValueError(f"invalid intent values: {invalid}")
    return intent


def save_intent(path: Path | str, intent: Mapping[str, str]) -> None:
    invalid = {key: value for key, value in intent.items() if value not in _DESIRED}
    if invalid:
        raise ValueError(f"invalid intent values: {invalid}")
    Path(path).write_text(
        json.dumps(dict(intent), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def export_observations(adapters_or_records: Any) -> list[dict[str, Any]]:
    """Return normalized JSON-safe observations from adapters or records."""
    sources = (
        adapters_or_records.values()
        if isinstance(adapters_or_records, Mapping)
        else adapters_or_records
    )
    rows: list[dict[str, Any]] = []
    for source in sources:
        if hasattr(source, "discover"):
            records = source.discover([])
        elif isinstance(source, (list, tuple)):
            records = list(source)
        else:
            records = [source]
        for record in records:
            row = record.as_dict() if isinstance(record, LocalSkillRecord) else dict(record)
            ecosystem = str(row.get("ecosystem") or getattr(source, "ecosystem", ""))
            native_id = str(row.get("native_id") or row.get("name") or row.get("id") or "")
            identifier = str(row.get("id") or f"{ecosystem}/{native_id}")
            rows.append({
                "id": identifier,
                "ecosystem": ecosystem,
                "native_id": native_id,
                "actual": str(row.get("actual") or row.get("actual_state") or "unknown"),
                "scope": row.get("scope"),
                "path": row.get("path"),
            })
    return sorted(rows, key=lambda row: row["id"])


def drift(intent: Mapping[str, str], observations: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    observed = {str(row["id"]): str(row.get("actual", row.get("actual_state", "unknown"))) for row in observations}
    result = []
    for identifier, desired in sorted(intent.items()):
        actual = observed.get(identifier, "missing")
        if actual != desired:
            result.append({"id": identifier, "desired": desired, "actual": actual, "ecosystem": identifier.split("/", 1)[0]})
    return result


def diff_observations(old: Iterable[Mapping[str, Any]], new: Iterable[Mapping[str, Any]]) -> dict[str, list[Any]]:
    before = {str(row["id"]): dict(row) for row in old}
    after = {str(row["id"]): dict(row) for row in new}
    return {
        "added": [after[key] for key in sorted(after.keys() - before.keys())],
        "removed": [before[key] for key in sorted(before.keys() - after.keys())],
        "changed": [
            {"id": key, "old": before[key], "new": after[key]}
            for key in sorted(before.keys() & after.keys())
            if str(before[key].get("actual", before[key].get("actual_state", "unknown")))
            != str(after[key].get("actual", after[key].get("actual_state", "unknown")))
        ],
    }
