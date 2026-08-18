#!/usr/bin/env python3

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("scan_docs_project_reorganize_test", HERE / "scan-docs.py")
scan_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan_mod)


def _install_skill(repo_root: Path) -> None:
    path = repo_root / "skills" / "project-canvas-explorer" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Project Canvas Explorer\n", encoding="utf-8")


def test_enqueue_project_canvas_reorganize_uses_existing_queue_without_task_card(tmp_path):
    _install_skill(tmp_path)
    before_cards = list(tmp_path.rglob("project/**/*.md"))

    with patch.object(scan_mod, "REPO_ROOT", tmp_path), \
         patch.object(
             scan_mod,
             "validate_real_project_ref",
             return_value=({"ok": True, "project": {"project_ref": "demo-project", "title": "Demo"}}, 200),
         ), \
         patch.object(scan_mod, "_queue_consume_next") as consume:
        result, status = scan_mod.enqueue_project_canvas_reorganize("demo-project")

    assert status == 200
    assert result["ok"] is True
    assert result["queue"] == "ai-run"
    assert list(tmp_path.rglob("project/**/*.md")) == before_cards
    queue = json.loads((tmp_path / ".ai-queue.json").read_text(encoding="utf-8"))
    entry = queue["entries"][0]
    assert entry["path"] == "skills/project-canvas-explorer/SKILL.md"
    assert entry["workdir"] == str(tmp_path.resolve())
    assert entry["ai_profile"] == "execute_codex"
    assert entry["metadata"]["kind"] == "project_canvas_explorer"
    assert entry["metadata"]["project_ref"] == "demo-project"
    assert entry["metadata"]["label"] == "项目画布 AI 重整 · demo-project"
    assert "project_ref `demo-project`" in entry["prompt_override"]
    assert "actor `codex`" in entry["prompt_override"]
    consume.assert_called_once_with()


def test_enqueue_project_canvas_reorganize_deduplicates_active_project_run(tmp_path):
    _install_skill(tmp_path)
    validation = ({"ok": True, "project": {"project_ref": "demo-project"}}, 200)
    with patch.object(scan_mod, "REPO_ROOT", tmp_path), \
         patch.object(scan_mod, "validate_real_project_ref", return_value=validation), \
         patch.object(scan_mod, "_queue_consume_next"):
        first, _ = scan_mod.enqueue_project_canvas_reorganize("demo-project")
        second, status = scan_mod.enqueue_project_canvas_reorganize("demo-project")

    assert status == 200
    assert second["run_id"] == first["run_id"]
    assert second["deduplicated"] is True
    queue = json.loads((tmp_path / ".ai-queue.json").read_text(encoding="utf-8"))
    assert len(queue["entries"]) == 1


def test_canvas_reorganize_endpoint_forwards_project_ref():
    payload = json.dumps({"project_ref": "demo-project"}).encode("utf-8")
    captured = {}

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = "/api/canvas/reorganize"
            self.headers = {"Host": "localhost", "Content-Length": str(len(payload))}
            self.rfile = io.BytesIO(payload)

        def _get_session(self):
            return {"user": "Owner"}

        def _json(self, data, code=200):
            captured["data"] = data
            captured["code"] = code

    with patch.object(
        scan_mod,
        "enqueue_project_canvas_reorganize",
        return_value=({"ok": True, "run_id": "run-1", "project_ref": "demo-project"}, 200),
    ) as enqueue:
        TestHandler().do_POST()

    enqueue.assert_called_once_with("demo-project")
    assert captured == {
        "data": {"ok": True, "run_id": "run-1", "project_ref": "demo-project"},
        "code": 200,
    }
