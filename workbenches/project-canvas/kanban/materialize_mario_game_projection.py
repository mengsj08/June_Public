#!/usr/bin/env python3
"""Materialize one registered Mario game projection from approved sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mario_game_projection
import mario_levels
from materialize_mario_unit import _atomic_write, find_task


def render_projection(*, level_id, repo_root, documents_root):
    registration = mario_levels.get_registration(level_id=level_id)
    if not registration:
        raise RuntimeError(f"Mario level is not registered: {level_id}")
    if not registration.get("game_projection_path"):
        raise RuntimeError(f"Mario level has no game_projection_path: {level_id}")
    task = find_task(repo_root, registration["task_id"])
    result, status = mario_levels.build_level(
        task,
        {"repo_root": repo_root, "documents_root": documents_root},
        level_id=level_id,
    )
    if status != 200 or not result.get("available"):
        raise RuntimeError(f"Mario level did not build: {result}")
    projection = mario_game_projection.build_game_projection(result["level"])
    output = documents_root / Path(registration["game_projection_path"])
    payload = json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return output, payload, projection


def main(argv=None):
    script_path = Path(__file__).resolve()
    default_repo = script_path.parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=default_repo)
    parser.add_argument("--documents-root", type=Path, default=default_repo.parent.parent)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    documents_root = args.documents_root.resolve()
    output, payload, projection = render_projection(
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
                "projection_hash": projection["projection_hash"],
            }, ensure_ascii=False))
            return 1
        print(json.dumps({
            "ok": True,
            "status": "current",
            "path": str(output),
            "projection_hash": projection["projection_hash"],
        }, ensure_ascii=False))
        return 0

    if existing is not None and existing != payload and not args.replace:
        print(json.dumps({
            "ok": False,
            "status": "replace_required",
            "path": str(output),
            "projection_hash": projection["projection_hash"],
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
        "projection_hash": projection["projection_hash"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
