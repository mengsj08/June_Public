#!/usr/bin/env python3
"""Prepare one project-canvas-explorer run for the existing AI queue."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


KIND = "project_canvas_explorer"
SKILL_REL_PATH = "skills/project-canvas-explorer/SKILL.md"
PROFILE = "execute_codex"


def build_prompt(project_ref: str) -> str:
    return f"""Run the local project-canvas-explorer workflow for project_ref `{project_ref}`.

This is a Project Canvas reorganization run, not a code implementation task.

1. Read `skills/project-canvas-explorer/SKILL.md` completely, then follow its full workflow and required references.
2. Use exactly `{project_ref}` as the target project_ref and run from the kanban-personal repository root.
3. Take the snapshot, read every linked fact card in full, classify direction decisions from evidence, design the exploration tree, dry-run it, then apply it with actor `codex` and perform the documented acceptance snapshot/event checks.
4. The user explicitly authorized this button-triggered apply. Do not ask for another confirmation.
5. Do not edit the Skill, task cards, project registry, source code, or `.canvas` files directly. Canvas writes must go only through the Skill's `PUT /api/canvas` path with `actor: codex` and `base_rev`.
6. Preserve generated and human-owned nodes/edges. On HTTP 409, re-read and re-merge; never force. If evidence is insufficient, mark the direction `待决定`.
7. Keep any temporary plan outside tracked `.canvas` directories. Report the main branches, direction-state counts, unresolved sources, write result, and actor verification in the final output.
"""


def prepare_run(
    repo_root: str | Path,
    project_ref: str,
    validate_project_ref: Callable[[str], tuple[dict[str, Any], int]],
) -> tuple[dict[str, Any], int]:
    clean_ref = str(project_ref or "").strip()
    if not clean_ref:
        return {"ok": False, "error": "project_ref 不能为空"}, 400

    project_result, status = validate_project_ref(clean_ref)
    if status != 200 or not project_result.get("ok"):
        return project_result, status

    root = Path(repo_root).resolve()
    skill_path = root / SKILL_REL_PATH
    if not skill_path.is_file():
        return {"ok": False, "error": "project-canvas-explorer skill 不存在"}, 503

    project = project_result.get("project") if isinstance(project_result.get("project"), dict) else {}
    label = f"项目画布 AI 重整 · {clean_ref}"
    return {
        "ok": True,
        "project_ref": clean_ref,
        "project_title": str(project.get("title") or clean_ref),
        "path": SKILL_REL_PATH,
        "workdir": str(root),
        "tool": "codex",
        "profile": PROFILE,
        "prompt": build_prompt(clean_ref),
        "dedupe_key": f"project-canvas-explorer:{clean_ref}",
        "metadata": {
            "kind": KIND,
            "label": label,
            "project_ref": clean_ref,
            "project_title": str(project.get("title") or clean_ref),
            "skill": "project-canvas-explorer",
            "actor": "codex",
        },
    }, 200
