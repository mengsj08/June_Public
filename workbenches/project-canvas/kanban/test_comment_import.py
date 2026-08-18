"""External comment import stays durable without becoming an AI run."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comment_import = _load("comment_import_test", HERE / "comment_import.py")
scan_mod = _load("scan_docs_comment_import_test", HERE / "scan-docs.py")


@pytest.fixture
def repo(tmp_path):
    task_rel = "project/Paper/RSH-13_paper.md"
    task_path = tmp_path / task_rel
    task_path.parent.mkdir(parents=True)
    raw = """---
title: Paper
task_id: RSH-13
status: todo
---

# Background

Unique anchor sentence for this review.
"""
    task_path.write_text(raw, encoding="utf-8")

    def resolve(path):
        if path != task_rel:
            return None, str(path or ""), "非法路径", 400
        return task_path, task_rel, "", 200

    def read(path):
        if path != task_rel:
            return None, "文件不存在"
        current = task_path.read_text(encoding="utf-8")
        fm_end = current.index("---", 4) + 3
        body = current[fm_end:].lstrip("\r\n")
        return {
            "raw": current,
            "body": body,
            "rev": hashlib.sha256(current.encode("utf-8")).hexdigest(),
            "frontmatter": {"task_id": "RSH-13", "title": "Paper"},
        }, ""

    return {
        "root": tmp_path,
        "task_rel": task_rel,
        "task_path": task_path,
        "deps": {
            "repo_root": tmp_path,
            "resolve_active_task_card_path": resolve,
            "read_task_file": read,
            "ledger_lock": threading.Lock(),
        },
    }


def request_for(repo, *, dry_run=True, content="Please strengthen this claim."):
    return {
        "path": repo["task_rel"],
        "dry_run": dry_run,
        "source": {
            "provider": "feishu",
            "url": "https://example.feishu.cn/docx/doc-token",
            "doc_token": "doc-token",
            "revision": "51",
        },
        "comments": [{
            "comment_id": "comment-1",
            "author": "Owner",
            "ts": "2026-07-09T10:00:00+08:00",
            "updated_at": "2026-07-09T10:01:00+08:00",
            "content": content,
            "resolved": False,
            "source_quote": {
                "quote_text": "Unique anchor sentence for this review.",
                "section": "Background",
            },
            "replies": [{
                "reply_id": "reply-1",
                "author": "Editor",
                "ts": "2026-07-09T11:00:00+08:00",
                "content": "Agreed.",
            }],
        }],
    }


def test_dry_run_previews_without_writing_or_mutating_body(repo):
    before = repo["task_path"].read_bytes()
    result, status = comment_import.import_comments(repo["deps"], request_for(repo))

    assert status == 200
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["would_import"] == 2
    assert result["imported"] == 0
    assert result["anchor_counts"]["exact"] == 1
    assert len(result["comments"]) == 1
    assert len(result["comments"][0]["replies"]) == 1
    assert not (repo["root"] / result["ledger_ref"]).exists()
    assert repo["task_path"].read_bytes() == before


def test_commit_is_idempotent_preserves_reply_parent_and_body_sha(repo):
    before_sha = hashlib.sha256(repo["task_path"].read_bytes()).hexdigest()
    payload = request_for(repo, dry_run=False)

    first, first_status = comment_import.import_comments(repo["deps"], payload)
    second, second_status = comment_import.import_comments(repo["deps"], payload)
    projected, get_status = comment_import.get_task_comments(repo["deps"], repo["task_rel"])

    assert first_status == second_status == get_status == 200
    assert first["imported"] == 2
    assert second["imported"] == 0
    assert second["skipped"] == 2
    ledger = repo["root"] / first["ledger_ref"]
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert all(row["event"] == "external_comment_imported" for row in rows)
    assert all(row["role"] == "human" for row in rows)
    root, reply = rows
    assert root["parent"] is None
    assert reply["parent"] == root["entry_id"]
    assert projected["comments"][0]["author"] == "Owner"
    assert projected["comments"][0]["origin"] == {
        "provider": "feishu",
        "url": "https://example.feishu.cn/docx/doc-token",
        "doc_token": "doc-token",
        "revision": "51",
        "comment_id": "comment-1",
    }
    assert projected["comments"][0]["replies"][0]["parent"] == root["entry_id"]
    assert hashlib.sha256(repo["task_path"].read_bytes()).hexdigest() == before_sha


def test_path_revision_and_size_limits(repo):
    bad_path = request_for(repo)
    bad_path["path"] = "../RSH-13.md"
    result, status = comment_import.import_comments(repo["deps"], bad_path)
    assert status == 400
    assert result["ok"] is False

    stale = request_for(repo)
    stale["expected_task_rev"] = "stale"
    result, status = comment_import.import_comments(repo["deps"], stale)
    assert status == 409
    assert result["error"] == "任务正文版本已变化"

    oversized = request_for(repo, content="x" * (comment_import.MAX_COMMENT_BYTES + 1))
    result, status = comment_import.import_comments(repo["deps"], oversized)
    assert status == 400
    assert "超过" in result["error"]

    too_many = request_for(repo)
    too_many["comments"] = [
        {"comment_id": f"c-{index}", "content": "x"}
        for index in range(comment_import.MAX_BATCH_COMMENTS + 1)
    ]
    result, status = comment_import.import_comments(repo["deps"], too_many)
    assert status == 400
    assert "批注总数超过上限" in result["error"]


def test_markdown_normalized_anchor_and_duplicate_occurrence_are_stable():
    body = "**Table 1.** Current results\n\n| Cytokines/catagfactors | mammary |\n| Cytokines/catagfactors | glioma |"

    normalized_index, normalized_status = comment_import._choose_anchor_index(
        body, "Table 1. Current results", "", "", occurrence_index=0,
    )
    duplicate_index, duplicate_status = comment_import._choose_anchor_index(
        body, "Cytokines/catagfactors", "", "", occurrence_index=0,
    )

    assert normalized_index == body.index("Table 1.")
    assert normalized_status == "normalized"
    assert duplicate_index == body.index("Cytokines/catagfactors")
    assert duplicate_status == "exact"


def test_edit_root_and_reply_are_append_only_and_keep_source_metadata(repo):
    before_sha = hashlib.sha256(repo["task_path"].read_bytes()).hexdigest()
    imported, status = comment_import.import_comments(
        repo["deps"], request_for(repo, dry_run=False),
    )
    assert status == 200
    root = imported["comments"][0]
    reply = root["replies"][0]
    original_author = root["author"]
    original_ts = root["ts"]
    original_origin = root["origin"]
    original_quote = root["source_quote"]

    edited_root, root_status = comment_import.edit_comment(repo["deps"], {
        "path": repo["task_rel"],
        "entry_id": root["entry_id"],
        "content": "Locally revised root comment.",
        "expected_updated_at": root["updated_at"],
    }, actor="Owner")
    edited_reply, reply_status = comment_import.edit_comment(repo["deps"], {
        "path": repo["task_rel"],
        "entry_id": reply["entry_id"],
        "content": "Locally revised reply.",
        "expected_updated_at": reply["updated_at"],
    }, actor="Owner")

    assert root_status == reply_status == 200
    assert edited_root["changed"] is True
    assert edited_reply["changed"] is True
    projected, _ = comment_import.get_task_comments(repo["deps"], repo["task_rel"])
    current = projected["comments"][0]
    assert current["content"] == "Locally revised root comment."
    assert current["replies"][0]["content"] == "Locally revised reply."
    assert current["author"] == original_author
    assert current["ts"] == original_ts
    assert current["origin"] == original_origin
    assert current["source_quote"] == original_quote
    assert current["edited_by"] == "Owner"
    assert current["replies"][0]["edited_by"] == "Owner"
    ledger = repo["root"] / projected["ledger_ref"]
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == [
        "external_comment_imported", "external_comment_imported",
        "external_comment_edited", "external_comment_edited",
    ]
    assert hashlib.sha256(repo["task_path"].read_bytes()).hexdigest() == before_sha


def test_edit_conflict_noop_and_missing_entry(repo):
    imported, _ = comment_import.import_comments(repo["deps"], request_for(repo, dry_run=False))
    root = imported["comments"][0]

    noop, noop_status = comment_import.edit_comment(repo["deps"], {
        "path": repo["task_rel"], "entry_id": root["entry_id"],
        "content": root["content"], "expected_updated_at": root["updated_at"],
    }, actor="Owner")
    assert noop_status == 200
    assert noop["changed"] is False

    conflict, conflict_status = comment_import.edit_comment(repo["deps"], {
        "path": repo["task_rel"], "entry_id": root["entry_id"],
        "content": "Changed", "expected_updated_at": "stale",
    }, actor="Owner")
    assert conflict_status == 409
    assert conflict["current_updated_at"] == root["updated_at"]
    assert conflict["current_content"] == root["content"]

    edited, edited_status = comment_import.edit_comment(repo["deps"], {
        "path": repo["task_rel"], "entry_id": root["entry_id"],
        "content": "Changed once", "expected_updated_at": root["updated_at"],
    }, actor="Owner")
    assert edited_status == 200
    assert edited["changed"] is True
    edited_noop, edited_noop_status = comment_import.edit_comment(repo["deps"], {
        "path": repo["task_rel"], "entry_id": root["entry_id"],
        "content": "Changed once", "expected_updated_at": edited["comment"]["updated_at"],
    }, actor="Owner")
    assert edited_noop_status == 200
    assert edited_noop["changed"] is False

    missing, missing_status = comment_import.edit_comment(repo["deps"], {
        "path": repo["task_rel"], "entry_id": "ext-missing", "content": "Changed",
    }, actor="Owner")
    assert missing_status == 404
    assert missing["ok"] is False


class _Response:
    status = None
    data = None


def _handler(path, body=None):
    response = _Response()

    class TestHandler(scan_mod.Handler):
        def __init__(self):
            self.path = path
            self.headers = {"Host": "127.0.0.1"}
            raw = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
            if body is not None:
                self.headers["Content-Length"] = str(len(raw))
            self.rfile = io.BytesIO(raw)

        def _state_change_guard(self, _path):
            return True

        def _get_session(self):
            return {"user": "Owner"}

        def _json(self, value, code=200):
            response.status = code
            response.data = value

        def send_error(self, code, message=None):
            response.status = code
            response.data = {"ok": False, "error": message or "Not Found"}

    return TestHandler(), response


def test_http_routes_commit_and_project(repo):
    payload = request_for(repo, dry_run=False)
    post_handler, post_response = _handler("/api/comments/import", payload)
    with patch.object(scan_mod, "REPO_ROOT", repo["root"]), \
         patch.object(scan_mod, "SCAN_DIRS", ["project/Paper"]):
        post_handler.do_POST()
    assert post_response.status == 200
    assert post_response.data["imported"] == 2

    get_handler, get_response = _handler(
        "/api/task-comments?path=project%2FPaper%2FRSH-13_paper.md"
    )
    with patch.object(scan_mod, "REPO_ROOT", repo["root"]), \
         patch.object(scan_mod, "SCAN_DIRS", ["project/Paper"]):
        get_handler.do_GET()
    assert get_response.status == 200
    assert get_response.data["ok"] is True
    assert len(get_response.data["comments"]) == 1
    thread = get_response.data["comments"][0]
    assert set((
        "thread_id", "entry_id", "author", "ts", "updated_at", "content",
        "resolved", "origin", "source_quote", "replies",
    )).issubset(thread)

    edit_handler, edit_response = _handler("/api/comments/edit", {
        "path": repo["task_rel"],
        "entry_id": thread["entry_id"],
        "content": "Edited through the HTTP route.",
        "expected_updated_at": thread["updated_at"],
    })
    with patch.object(scan_mod, "REPO_ROOT", repo["root"]), \
         patch.object(scan_mod, "SCAN_DIRS", ["project/Paper"]):
        edit_handler.do_POST()
    assert edit_response.status == 200
    assert edit_response.data["changed"] is True
    assert edit_response.data["comment"]["content"] == "Edited through the HTTP route."
