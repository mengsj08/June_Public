"""Robust JSONL persistence helpers for canvas audit events."""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any


def events_path_for(canvas_path: str | Path) -> Path:
    return Path(canvas_path).parent / 'events.jsonl'


def append_events(canvas_path: str | Path, events: list[dict[str, Any]], *, lock=None) -> bool:
    """Append a batch atomically at the process-lock level and report failure."""
    if not events:
        return True
    try:
        payload = ''.join(json.dumps(event, ensure_ascii=False) + '\n' for event in events)
        with lock if lock is not None else nullcontext():
            with open(events_path_for(canvas_path), 'a', encoding='utf-8') as fh:
                fh.write(payload)
        return True
    except Exception:
        return False


def read_events(canvas_path: str | Path) -> dict[str, Any]:
    """Read valid event objects while making malformed non-empty lines visible."""
    events_path = events_path_for(canvas_path)
    if not events_path.exists():
        return {'events': [], 'malformed_lines': 0}
    events: list[dict[str, Any]] = []
    malformed_lines = 0
    try:
        with open(events_path, 'r', encoding='utf-8') as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    malformed_lines += 1
                    continue
                if not isinstance(event, dict):
                    malformed_lines += 1
                    continue
                events.append(event)
    except OSError:
        return {'events': events, 'malformed_lines': malformed_lines}
    return {'events': events, 'malformed_lines': malformed_lines}


def partial_save_error(canvas_ref: str, canvas_rev: str, canvas: dict[str, Any]) -> dict[str, Any]:
    """Canonical response when the canvas persisted but its audit batch did not."""
    return {
        'ok': False,
        'error': 'canvas_event_append_failed',
        'message': '画布已保存但事件未入账，请重新 GET 对账',
        'partial_save': True,
        'canvas_saved': True,
        'events_recorded': False,
        'canvas_ref': canvas_ref,
        'canvas_rev': canvas_rev,
        'rev': canvas_rev,
        'canvas': canvas,
    }
