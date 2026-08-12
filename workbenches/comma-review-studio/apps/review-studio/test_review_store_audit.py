#!/usr/bin/env python3
"""Read-only Store Audit CLI contracts for SKL-119."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import review_store_audit
import server


SECRET_TEXT = "PRIVATE_BODY_COMMENT_EVIDENCE_TRACE_SECRET"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _tree_hashes(root: Path) -> dict[str, str]:
    rows = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rows[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return rows


class ReviewHostLoopbackTests(unittest.TestCase):
    def test_main_rejects_non_loopback_before_bind(self):
        with mock.patch.object(server, "ThreadingHTTPServer") as httpd:
            with self.assertRaises(SystemExit) as ctx:
                server.main(["--host", "0.0.0.0", "--port", "8891"])
        self.assertEqual(ctx.exception.code, 2)
        httpd.assert_not_called()

    def test_main_rejects_ipv6_loopback_v0(self):
        with mock.patch.object(server, "ThreadingHTTPServer") as httpd:
            with self.assertRaises(SystemExit):
                server.main(["--host", "::1", "--port", "8891"])
        httpd.assert_not_called()

    def test_main_allows_localhost_and_127(self):
        for host in ("127.0.0.1", "localhost"):
            with self.subTest(host=host), \
                    mock.patch.object(server, "os") as os_module, \
                    mock.patch.object(server, "_fail_stale_running_reviews",
                                      return_value={"runs_failed": 0, "sessions_failed": 0}), \
                    mock.patch.object(server, "_reconcile_operation_journal",
                                      return_value={"pending": 0, "finalized": 0, "inconsistent": 0}), \
                    mock.patch.object(server, "runtime_capability_manifest",
                                      return_value={"tools": [
                                          {"id": "bigapple", "ready": False, "auth_state": "not_running"},
                                          {"id": "claude", "ready": False, "auth_state": "not_installed"},
                                          {"id": "codex", "ready": False, "auth_state": "not_installed"},
                                      ]}), \
                    mock.patch.object(server, "ThreadingHTTPServer") as httpd:
                os_module.makedirs.return_value = None
                instance = httpd.return_value
                instance.serve_forever.side_effect = KeyboardInterrupt()
                instance.shutdown.return_value = None
                self.assertEqual(server.main(["--host", host, "--port", "0"]), 0)
                self.assertEqual(httpd.call_args.args[0], (host, 0))


class ReviewStoreAuditTests(unittest.TestCase):
    def _clean_store(self, root: Path) -> None:
        _write(root / "paper.md", f"# Title\n\n{SECRET_TEXT}\n")
        _write_json(root / "paper.md.comments.json", {
            "schema_version": "comma-comments-view/v1.1",
            "comments_rev": "comments-fixture",
            "comments": [{"id": "c-1", "content": SECRET_TEXT}],
        })
        _write(root / "paper.md.comment-events.jsonl", json.dumps({
            "event_id": "ce-1",
            "comment_id": "c-1",
            "content_after_hash": "sha256:fixture",
        }) + "\n")
        _write_json(root / "review-sessions" / "review-000000000001.json", {
            "schema_version": "comma-review-session/v1",
            "id": "review-000000000001",
            "doc_path": "paper.md",
            "status": "completed",
            "run": {
                "schema_version": "comma-review-run/v1",
                "id": "run-000000000001",
                "status": "completed",
            },
        })
        _write_json(root / "conversations" / "conversation-000000000001.json", {
            "schema_version": "comma-review-conversation/v1",
            "id": "conversation-000000000001",
            "doc_path": "paper.md",
            "messages": [{"content": SECRET_TEXT}],
        })
        key = hashlib.sha256("paper.md".encode("utf-8")).hexdigest()[:16]
        rev = "sha256-fixture"
        _write_json(root / ".comma-review" / "versions" / key / "index.json", {
            "schema_version": "comma-review-versions/v1",
            "doc_path": "paper.md",
            "versions": [{"id": "version-1", "rev": rev}],
        })
        _write(root / ".comma-review" / "versions" / key / "blobs" / f"{rev}.md", SECRET_TEXT)
        _write_json(root / ".comma-review" / "evidence-sources" / key / "evidence-abcdef1234567890" / "record.json", {
            "schema_version": "comma-review-evidence-source/v1",
            "id": "evidence-abcdef1234567890",
            "source_filename": "source.pdf",
            "summary": SECRET_TEXT,
        })
        _write(root / ".comma-review" / "evidence-sources" / key / "evidence-abcdef1234567890" / "source.pdf", "%PDF")
        _write_json(root / ".comma-review" / "evidence-sources" / key / "evidence-abcdef1234567890" / "pages.json", [
            {"page": 1, "text": SECRET_TEXT}
        ])
        _write_json(root / ".comma-review" / "operation-journal.json", {
            "schema_version": "comma-operation-journal/v1",
            "entries": [],
        })

    def test_clean_store_is_read_only_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            self._clean_store(root)
            before = _tree_hashes(root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = review_store_audit.main(["--data-root", str(root)])
            after = _tree_hashes(root)
            self.assertEqual(code, review_store_audit.EXIT_CLEAN)
            self.assertEqual(before, after)
            self.assertNotIn(SECRET_TEXT, out.getvalue())

    def test_warning_exit_for_orphans_missing_doc_and_pending_journal(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            self._clean_store(root)
            os.remove(root / "paper.md")
            _write_json(root / ".comma-review" / "operation-journal.json", {
                "schema_version": "comma-operation-journal/v1",
                "entries": [{"schema_version": "comma-operation-journal-entry/v1", "status": "pending"}],
            })
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = review_store_audit.main(["--data-root", str(root), "--json"])
            summary = json.loads(out.getvalue())
            self.assertEqual(code, review_store_audit.EXIT_WARNING)
            self.assertEqual(summary["status"], "warning")
            self.assertTrue(any(item["code"] == "doc_path_missing_file" for item in summary["warnings"]))
            self.assertTrue(any(item["code"] == "operation_journal_pending" for item in summary["warnings"]))
            self.assertNotIn(SECRET_TEXT, out.getvalue())

    def test_error_exit_for_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            _write(root / "broken.md.comments.json", "{not-json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = review_store_audit.main(["--data-root", str(root)])
            self.assertEqual(code, review_store_audit.EXIT_ERROR)
            self.assertIn("json_parse_error", out.getvalue())


if __name__ == "__main__":
    unittest.main()
