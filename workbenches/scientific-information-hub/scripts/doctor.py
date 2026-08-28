#!/usr/bin/env python3
"""Read-only preflight for the public SIH reference package."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "config" / "sources.demo.json",
    ROOT / "config" / "sources.example.json",
    ROOT / "config" / "profile.example.json",
    ROOT / "fixtures" / "synthetic" / "source_items.jsonl",
]
SUSPICIOUS = re.compile(r"(?i)(api[_-]?key|password|token|secret)\s*[=:]\s*['\"]?[A-Za-z0-9/+_-]{12,}")


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python", sys.version_info >= (3, 10), f"{sys.version_info.major}.{sys.version_info.minor}"))
    for path in REQUIRED:
        checks.append((f"exists:{path.relative_to(ROOT)}", path.is_file(), "required file"))
    for path in ROOT.glob("config/*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
            checks.append((f"json:{path.name}", True, "valid"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append((f"json:{path.name}", False, type(exc).__name__))
    scanned = 0
    suspicious: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in {".git", "demo", "__pycache__"} for part in path.parts):
            continue
        if path.suffix.lower() not in {".json", ".jsonl", ".md", ".py", ".toml", ".yml", ".yaml", ".csv", ".eml"}:
            continue
        scanned += 1
        content = path.read_text(encoding="utf-8", errors="replace")
        if SUSPICIOUS.search(content):
            suspicious.append(str(path.relative_to(ROOT)))
    checks.append(("credential-pattern-scan", not suspicious, f"{scanned} text files"))
    for name, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    if suspicious:
        print("Potential credential-like assignments:")
        for path in suspicious:
            print(f"- {path}")
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
