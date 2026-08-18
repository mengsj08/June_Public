#!/usr/bin/env python3
"""Materialize one registered Mario Unit from its approved local sources."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import mario_levels


def _task_from_card(path, repo_root):
    text = path.read_text(encoding="utf-8")
    values = mario_levels._frontmatter(text)
    return {
        "task_id": values.get("task_id", ""),
        "status": values.get("status", ""),
        "source": values.get("source", ""),
        "human_gate": values.get("human_gate", "").lower() == "true",
        "attention_scope": values.get("attention_scope", ""),
        "path": str(path.relative_to(repo_root)),
    }


def find_task(repo_root, task_id):
    matches = []
    for path in (repo_root / "project").rglob("*.md"):
        if ".archive" in path.parts:
            continue
        try:
            task = _task_from_card(path, repo_root)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if task["task_id"] == task_id:
            matches.append((path, task))
    if not matches:
        raise RuntimeError(f"active task card not found: {task_id}")
    if len(matches) != 1:
        joined = ", ".join(str(path) for path, _ in matches)
        raise RuntimeError(f"multiple active task cards found for {task_id}: {joined}")
    return matches[0][1]


def render_unit(*, level_id, repo_root, documents_root):
    registration = mario_levels.get_registration(level_id=level_id)
    if not registration:
        raise RuntimeError(f"Mario level is not registered: {level_id}")
    if not registration.get("materialized_path"):
        raise RuntimeError(f"Mario level has no materialized_path: {level_id}")
    task = find_task(repo_root, registration["task_id"])
    result, status = mario_levels.build_level(
        task,
        {"repo_root": repo_root, "documents_root": documents_root},
        level_id=level_id,
    )
    if status != 200 or not result.get("available"):
        raise RuntimeError(f"Mario level did not build: {result}")
    unit = mario_levels.unit_from_level(result["level"])
    output = documents_root / Path(registration["materialized_path"])
    payload = json.dumps(unit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return output, payload, unit


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main(argv=None):
    script_path = Path(__file__).resolve()
    default_repo = script_path.parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=default_repo)
    parser.add_argument("--documents-root", type=Path, default=default_repo.parent.parent)
    parser.add_argument("--check", action="store_true", help="Fail if the materialized file is missing or stale")
    parser.add_argument("--replace", action="store_true", help="Replace an existing stale materialization")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    documents_root = args.documents_root.resolve()
    output, payload, unit = render_unit(
        level_id=args.level_id,
        repo_root=repo_root,
        documents_root=documents_root,
    )
    existing = output.read_text(encoding="utf-8") if output.exists() else None

    if args.check:
        if existing != payload:
            state = "missing" if existing is None else "stale"
            print(json.dumps({
                "ok": False,
                "status": state,
                "path": str(output),
                "projection_hash": unit["projection_hash"],
            }, ensure_ascii=False))
            return 1
        print(json.dumps({
            "ok": True,
            "status": "current",
            "path": str(output),
            "projection_hash": unit["projection_hash"],
        }, ensure_ascii=False))
        return 0

    if existing is not None and existing != payload and not args.replace:
        print(json.dumps({
            "ok": False,
            "status": "replace_required",
            "path": str(output),
            "projection_hash": unit["projection_hash"],
        }, ensure_ascii=False))
        return 2
    if existing == payload:
        status = "unchanged"
    else:
        _atomic_write(output, payload)
        status = "created" if existing is None else "replaced"
    print(json.dumps({
        "ok": True,
        "status": status,
        "path": str(output),
        "unit_status": unit["status"],
        "projection_hash": unit["projection_hash"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
