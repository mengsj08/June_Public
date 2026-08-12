#!/usr/bin/env python3
"""HTTP-level contract test with a controlled AI response."""
import json
import io
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import zipfile
from unittest import mock

import server


class ReviewApiTests(unittest.TestCase):
    def test_documents_api_lists_manuscripts_and_excludes_internal_markdown(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            os.makedirs(os.path.join(tmp, "registered"))
            os.makedirs(os.path.join(tmp, "scratch"))
            os.makedirs(os.path.join(tmp, ".comma-review", "imports", "import-aaaaaaaaaaaaaaaa"))
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# Paper\n\nTop-level manuscript.\n")
            with open(os.path.join(tmp, "second.md"), "w", encoding="utf-8") as fh:
                fh.write("# Second\n")
            with open(os.path.join(tmp, "registered", "nested.md"), "w", encoding="utf-8") as fh:
                fh.write("# Nested\n")
            with open(os.path.join(tmp, "scratch", "note.md"), "w", encoding="utf-8") as fh:
                fh.write("# Scratch note\n")
            with open(os.path.join(tmp, ".comma-review", "imports", "import-aaaaaaaaaaaaaaaa", "candidate.md"), "w", encoding="utf-8") as fh:
                fh.write("# Internal candidate\n")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                server._snapshot_version(
                    os.path.join(tmp, "registered", "nested.md"),
                    "# Nested\n", kind="baseline", label="registered fixture")
                comments = [server._comment_record({
                    "kind": "anchored", "quote_text": "Top-level manuscript.",
                    "content": "Check source.", "author": "June",
                })]
                server._save_comments(os.path.join(tmp, "paper.md"), comments)
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    self._request(base + "/api/doc?path=registered/nested.md")
                    listing = self._request(base + "/api/documents?path=paper.md")
                    self.assertEqual(listing["schema_version"], "comma-review-documents/v1")
                    paths = [item["path"] for item in listing["documents"]]
                    self.assertEqual(set(paths), {"paper.md", "second.md", "registered/nested.md"})
                    self.assertNotIn("scratch/note.md", paths)
                    self.assertFalse(any(path.startswith(".comma-review/") for path in paths))
                    by_path = {item["path"]: item for item in listing["documents"]}
                    self.assertTrue(by_path["paper.md"]["current"])
                    self.assertEqual(by_path["registered/nested.md"]["display_name"], "nested.md")
                    self.assertEqual(by_path["paper.md"]["comment_count"], 1)
                    self.assertEqual(by_path["registered/nested.md"]["version_count"], 1)
                    self.assertTrue(by_path["registered/nested.md"]["last_opened_at"])
                    self.assertEqual(paths[0], "registered/nested.md")
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    def test_versions_conflict_recovery_and_portable_exports(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            first_body = "# Synthetic paper\n\nA controlled baseline sentence.\n\n![Control](figures/control.png)\n"
            second_body = first_body + "\n## Results\n\nA second revision.\n"
            draft_body = second_body + "\nLocally typed during a conflict.\n"
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write(first_body)
            os.makedirs(os.path.join(tmp, "figures"))
            with open(os.path.join(tmp, "figures", "control.png"), "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\ncontrolled")
            events = os.path.join(tmp, "events.jsonl")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", events):
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    document = self._request(base + "/api/doc?path=paper.md")
                    initial_rev = document["rev"]
                    history = self._request(base + "/api/versions?path=paper.md")
                    self.assertEqual(history["versions"][0]["kind"], "baseline")

                    saved = self._request(base + "/api/doc", "PUT", {
                        "path": "paper.md", "body": second_body,
                        "base_rev": initial_rev, "actor": "June",
                    })
                    second_rev = saved["rev"]
                    self.assertEqual(saved["version"]["kind"], "auto")

                    status, conflict = self._request_error(base + "/api/doc", "PUT", {
                        "path": "paper.md", "body": draft_body,
                        "base_rev": initial_rev, "actor": "June",
                    })
                    self.assertEqual(status, 409)
                    self.assertEqual(conflict["expected"], initial_rev)
                    draft_id = conflict["draft"]["id"]
                    draft = self._request(base + f"/api/drafts/{draft_id}?path=paper.md")["draft"]
                    self.assertEqual(draft["body"], draft_body)
                    self.assertEqual(draft["status"], "active")
                    draft_diff = self._request(base + f"/api/drafts/{draft_id}/diff?path=paper.md")
                    self.assertIn("Locally typed during a conflict.", draft_diff["diff"])

                    checkpoint = self._request(base + "/api/versions/checkpoints", "POST", {
                        "path": "paper.md", "base_rev": second_rev,
                        "label": "Evidence checked", "actor": "June",
                    })
                    self.assertEqual(checkpoint["version"]["label"], "Evidence checked")
                    history = self._request(base + "/api/versions?path=paper.md")
                    baseline = next(item for item in history["versions"] if item["kind"] == "baseline")
                    diff = self._request(base + f"/api/versions/diff?path=paper.md&from={baseline['id']}&to=current")
                    self.assertIn("A second revision.", diff["diff"])

                    restored = self._request(base + f"/api/versions/{baseline['id']}/restore", "POST", {
                        "path": "paper.md", "base_rev": second_rev, "actor": "June",
                    })
                    self.assertEqual(restored["body"], first_body)
                    self.assertEqual(restored["version"]["kind"], "restore")
                    recovered = self._request(base + f"/api/drafts/{draft_id}/restore", "POST", {
                        "path": "paper.md", "base_rev": restored["rev"], "actor": "June",
                    })
                    self.assertEqual(recovered["body"], draft_body)
                    self.assertEqual(recovered["version"]["kind"], "recovery")
                    self.assertEqual(recovered["draft"]["status"], "recovered")

                    self._request(base + "/api/comments?path=paper.md", "POST", {
                        "kind": "anchored", "quote_text": "A controlled baseline sentence.",
                        "content": "Keep this statement evidence-bound.", "priority": "P1", "actor": "Reviewer",
                    })
                    _, markdown_headers, markdown = self._request_raw(base + "/api/export?path=paper.md&format=markdown")
                    self.assertEqual(markdown.decode("utf-8"), draft_body)
                    self.assertIn("attachment", markdown_headers.get("Content-Disposition", ""))
                    _, _, reviewed = self._request_raw(base + "/api/export?path=paper.md&format=reviewed-markdown")
                    self.assertIn("## Review comments", reviewed.decode("utf-8"))
                    self.assertIn("Keep this statement evidence-bound.", reviewed.decode("utf-8"))
                    _, _, package = self._request_raw(base + "/api/export?path=paper.md&format=package")
                    with zipfile.ZipFile(io.BytesIO(package)) as archive:
                        names = set(archive.namelist())
                        self.assertIn("manifest.json", names)
                        self.assertIn("manuscript/paper.md", names)
                        self.assertIn("manuscript/figures/control.png", names)
                        self.assertIn("review/comments.json", names)
                        self.assertIn("history/versions.json", names)
                        manifest = json.loads(archive.read("manifest.json"))
                        self.assertEqual(manifest["privacy"], "Raw AI traces and the global event ledger are intentionally excluded.")
                    with open(os.path.join(tmp, "paper.md"), encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), draft_body)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    def test_frontend_exposes_cli_status_and_preflight_contract(self):
        with open(os.path.join(server.STATIC_ROOT, "editor.html"), encoding="utf-8") as fh:
            html = fh.read()
        with open(os.path.join(server.STATIC_ROOT, "app.js"), encoding="utf-8") as fh:
            script = fh.read()
        self.assertIn('id="cli-status"', html)
        self.assertIn('id="cli-redetect"', html)
        self.assertIn("/api/runtime/capabilities", script)
        self.assertIn("requireRuntimeTool(tool, 'quick_explain')", script)
        self.assertIn("文章总览", script)
        self.assertIn("源码编辑", script)
        self.assertIn("全文批注", script)
        self.assertIn('id="doc-file-menu"', html)
        self.assertIn('id="doc-file-list"', html)
        self.assertIn("/api/documents", script)
        self.assertIn("已切换到新主稿；原文稿", script)
        self.assertIn("switchDocument", script)
        self.assertIn('id="overview-drawer"', html)
        self.assertIn("未读取图片或图表像素", html)
        self.assertIn("未获取或全文核验所引用的文献", html)
        self.assertIn("未重新计算统计结果", html)
        self.assertNotIn("json.stub", script)

    def test_review_workflow_mutation_routes_append_comment_events(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            body = "# Paper\n\nA controlled sentence for workflow routes.\n"
            doc = os.path.join(tmp, "paper.md")
            with open(doc, "w", encoding="utf-8") as fh:
                fh.write(body)
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                comment = server._comment_record({
                    "id": "c-workflow",
                    "kind": "anchored",
                    "author": "AI Reviewer",
                    "content": "A controlled finding.",
                    "quote_text": "A controlled sentence for workflow routes.",
                    "source": "ai-review",
                    "finding_id": "F-WORKFLOW",
                    "finding_state": "accepted",
                    "workflow": {"state": "active"},
                    "finding_lineage_id": "lineage-workflow",
                    "evidence_occurrences": [{
                        "id": "occ-workflow",
                        "progress_state": "open",
                        "section_title": "Paper",
                        "source_locator": {"body_rev": server._rev(body), "text_index": 9},
                    }],
                }, strict=False)
                server._save_comments(doc, [comment])
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    muted = self._request(base + "/api/comments/c-workflow/lineage-mute", "POST", {
                        "path": "paper.md", "actor": "June",
                    })
                    self.assertEqual(muted["comment"]["workflow"]["state"], "muted_by_user")
                    restored = self._request(base + "/api/comments/c-workflow/lineage-restore", "POST", {
                        "path": "paper.md", "actor": "June",
                    })
                    self.assertEqual(restored["comment"]["workflow"]["state"], "active")
                    progress = self._request(
                        base + "/api/comments/c-workflow/evidence-occurrences/occ-workflow/progress",
                        "POST", {"path": "paper.md", "state": "handled", "actor": "June"},
                    )
                    self.assertEqual(progress["occurrence"]["progress_state"], "handled")
                    confirmed = self._request(base + "/api/comments/candidate-resolved/confirm", "POST", {
                        "path": "paper.md", "comment_ids": ["c-workflow"], "actor": "June",
                    })
                    self.assertEqual(confirmed["results"][0]["comment"]["workflow"]["state"], "resolved")
                    candidate_restored = self._request(base + "/api/comments/candidate-resolved/restore", "POST", {
                        "path": "paper.md", "comment_ids": ["c-workflow"], "actor": "June",
                    })
                    self.assertEqual(candidate_restored["results"][0]["comment"]["workflow"]["state"], "active")
                    actions = [event["action"] for event in server._load_comment_events(doc)]
                    self.assertIn("lineage-muted", actions)
                    self.assertIn("lineage-unmuted", actions)
                    self.assertIn("evidence-occurrence-progress", actions)
                    self.assertIn("candidate-resolved-confirmed", actions)
                    self.assertIn("candidate-resolved-restored", actions)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    def test_runtime_capabilities_report_provider_readiness(self):
        statuses = {
            "bigapple": {
                "id": "bigapple", "label": "BigApple Gateway", "available": False,
                "ready": False, "auth_state": "not_running", "version": "",
                "detail": "gateway fixture", "gateway_url": "",
            },
            "codex": {
                "id": "codex", "label": "Codex CLI", "available": True,
                "ready": True, "auth_state": "ready", "version": "codex-cli fixture",
                "detail": "codex-cli fixture",
            },
            "claude": {
                "id": "claude", "label": "Claude CLI", "available": True,
                "ready": False, "auth_state": "not_authenticated", "version": "claude fixture",
                "detail": "claude fixture",
            },
        }
        with mock.patch.object(server, "_cli_status", side_effect=lambda tool: statuses[tool]):
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                result = self._request(
                    f"http://127.0.0.1:{httpd.server_address[1]}/api/runtime/capabilities"
                )
                self.assertEqual(result["schema_version"], "comma-review-runtime-capabilities/v1")
                tools = {item["id"]: item for item in result["tools"]}
                self.assertFalse(tools["bigapple"]["capabilities"]["conversation"])
                self.assertEqual(tools["bigapple"]["auth_state"], "not_running")
                self.assertTrue(tools["codex"]["capabilities"]["conversation"])
                self.assertFalse(tools["claude"]["capabilities"]["quick_explain"])
                self.assertEqual(tools["claude"]["auth_state"], "not_authenticated")
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_cli_resolution_and_child_path_survive_minimal_launchd_environment(self):
        executable = os.path.realpath(server.sys.executable)
        with mock.patch.dict(server.os.environ, {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "COMMA_REVIEW_CODEX_BIN": executable,
        }, clear=False):
            self.assertEqual(server._resolve_cli_path("codex"), executable)
            child_path = server._cli_env(executable)["PATH"].split(os.pathsep)
            self.assertIn(os.path.dirname(executable), child_path)
            self.assertIn("/opt/homebrew/bin", child_path)

    def test_node_runtime_uses_portable_windows_candidate_after_path_lookup(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            app_root = os.path.join(tmp, "payload", "app")
            portable_node = os.path.join(tmp, "payload", "runtime", "node", "node.exe")
            os.makedirs(os.path.dirname(portable_node))
            with open(portable_node, "wb") as fh:
                fh.write(b"portable node fixture")
            with mock.patch.dict(server.os.environ, {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            }, clear=False), \
                    mock.patch.object(server, "_project_root", return_value=app_root), \
                    mock.patch.object(server.shutil, "which", return_value=""), \
                    mock.patch.object(server, "_is_windows", return_value=True):
                self.assertEqual(server._resolve_node_runtime(), portable_node)

    def test_static_provider_controls_include_bigapple_without_changing_codex_defaults(self):
        editor_path = os.path.join(server.ROOT, "static", "editor.html")
        app_path = os.path.join(server.ROOT, "static", "app.js")
        with open(editor_path, encoding="utf-8") as fh:
            html = fh.read()
        with open(app_path, encoding="utf-8") as fh:
            js = fh.read()

        self.assertIn('<option value="bigapple">BigApple</option>', html)
        self.assertIn('<select id="evidence-summary-tool"><option value="codex">Codex</option>', html)
        self.assertIn('<select id="overview-tool" aria-label="文章总览生成工具">\n              <option value="codex">Codex</option>', html)
        self.assertIn('name="review-tool" value="bigapple"', html)
        self.assertIn('name="conversation-tool" value="bigapple"', html)
        self.assertIn('name="review-tool" value="codex" checked', html)
        self.assertIn('name="conversation-tool" value="codex" checked', html)
        self.assertIn("const DEFAULT_AI_TOOL = 'codex';", js)
        self.assertIn("querySelector('input[name=\"review-tool\"]:checked')?.value || DEFAULT_AI_TOOL", js)
        self.assertIn("querySelector('input[name=\"conversation-tool\"]:checked')?.value || DEFAULT_AI_TOOL", js)
        self.assertIn("$('overview-tool').value || DEFAULT_AI_TOOL", js)

    def test_unavailable_cli_is_a_service_error_not_a_successful_stub(self):
        unavailable = {
            "id": "codex", "label": "Codex CLI", "available": False,
            "ready": False, "auth_state": "not_installed", "version": "",
            "detail": "未找到 codex 命令",
        }
        with mock.patch.object(server, "_cli_status", return_value=unavailable):
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                status, result = self._request_error(base + "/api/ai-run", "POST", {
                    "tool": "codex", "prompt": "Explain this synthetic sentence.",
                })
                self.assertEqual(status, 503)
                self.assertEqual(result["code"], "cli_unavailable")
                self.assertNotIn("stub", result)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_document_relative_assets_are_served_and_confined(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            nested = os.path.join(tmp, "nested")
            figures = os.path.join(nested, "figures")
            os.makedirs(figures)
            with open(os.path.join(nested, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("![Control](figures/control.png)\n")
            payload = b"\x89PNG\r\n\x1a\ncontrolled-test-image"
            with open(os.path.join(figures, "control.png"), "wb") as fh:
                fh.write(payload)
            with mock.patch.object(server, "DATA_ROOT", tmp):
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    with urllib.request.urlopen(
                        base + "/api/asset?doc=nested%2Fpaper.md&source=figures%2Fcontrol.png"
                    ) as response:
                        self.assertEqual(response.headers.get_content_type(), "image/png")
                        self.assertEqual(response.read(), payload)
                    escaped = self._request_error(
                        base + "/api/asset?doc=nested%2Fpaper.md&source=..%2F..%2Foutside.png"
                    )
                    self.assertEqual(escaped[0], 400)
                    self.assertIn("escapes data root", escaped[1]["error"])
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    def test_public_comment_contract_and_atomic_batch_revision(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            body = "# Results\n\nA precise sentence for an anchored comment.\n"
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write(body)
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    document = self._request(base + "/api/doc?path=paper.md")
                    overall = self._request(base + "/api/comments?path=paper.md", "POST", {
                        "kind": "overall", "actor": "June", "content": "整体意见",
                    })
                    self.assertEqual(overall["comment"]["kind"], "overall")
                    self.assertEqual(overall["comment"]["author"], "June")
                    batch = self._request(base + "/api/comments/batch?path=paper.md", "POST", {
                        "baseRev": document["rev"],
                        "actor": "AI Reviewer",
                        "source": "contract-test",
                        "comments": [{
                            "kind": "anchored",
                            "quoteText": "A precise sentence for an anchored comment.",
                            "content": "请补来源",
                            "priority": "P1",
                            "sourceLocator": {"bodyRev": document["rev"]},
                        }],
                    })
                    self.assertEqual(len(batch["comments"]), 1)
                    self.assertEqual(batch["comments"][0]["source"], "contract-test")
                    self.assertEqual(batch["comments"][0]["quote_text"], "A precise sentence for an anchored comment.")

                    conflict = self._request_error(base + "/api/comments/batch?path=paper.md", "POST", {
                        "base_rev": "sha256-stale",
                        "comments": [{"kind": "overall", "content": "不应写入"}],
                    })
                    self.assertEqual(conflict[0], 409)
                    self.assertTrue(conflict[1]["conflict"])
                    comments = self._request(base + "/api/comments?path=paper.md")
                    self.assertEqual(len(comments["comments"]), 2)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    def test_comment_item_lifecycle_versions_replies_and_append_only_ledger(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            body = "# Controlled manuscript\n\nA synthetic sentence.\n"
            doc_path = os.path.join(tmp, "paper.md")
            with open(doc_path, "w", encoding="utf-8") as fh:
                fh.write(body)
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    created = self._request(base + "/api/comments?path=paper.md", "POST", {
                        "kind": "anchored", "actor": "AI Reviewer", "source": "ai-review",
                        "quote_text": "A synthetic sentence.", "content": "Initial synthetic finding.",
                    })
                    comment_id = created["comment"]["id"]
                    self.assertEqual(created["comment_version"], 1)
                    self.assertEqual(created["comment"]["finding_state"], "provisional")
                    first_comments_rev = created["comments_rev"]

                    edited = self._request(base + f"/api/comments/{comment_id}?path=paper.md", "PATCH", {
                        "base_comment_version": 1, "actor": "June", "content": "Human-edited synthetic finding.",
                    })
                    self.assertEqual(edited["comment_version"], 2)
                    self.assertTrue(edited["comment"]["human_edited"])
                    self.assertNotEqual(edited["comments_rev"], first_comments_rev)

                    status, stale = self._request_error(
                        base + f"/api/comments/{comment_id}?path=paper.md", "PATCH",
                        {"base_comment_version": 1, "actor": "Stale", "content": "Must not win."},
                    )
                    self.assertEqual(status, 409)
                    self.assertEqual(stale["code"], "comment_version_conflict")
                    self.assertEqual(stale["current_comment"]["comment_version"], 2)

                    replied = self._request(base + f"/api/comments/{comment_id}/replies?path=paper.md", "POST", {
                        "base_comment_version": 2, "actor": "June", "content": "Synthetic reply.",
                    })
                    reply_id = replied["reply"]["id"]
                    self.assertEqual(replied["comment_version"], 3)
                    self.assertEqual(len(replied["comment"]["replies"]), 1)

                    reply_edited = self._request(
                        base + f"/api/comments/{comment_id}/replies/{reply_id}?path=paper.md", "PATCH",
                        {"base_comment_version": 3, "actor": "June", "content": "Edited synthetic reply."},
                    )
                    self.assertEqual(reply_edited["comment_version"], 4)
                    reply_withdrawn = self._request(
                        base + f"/api/comments/{comment_id}/replies/{reply_id}?path=paper.md", "DELETE",
                        {"base_comment_version": 4, "actor": "June"},
                    )
                    self.assertEqual(reply_withdrawn["reply"]["state"], "withdrawn")

                    withdrawn = self._request(base + f"/api/comments/{comment_id}?path=paper.md", "DELETE", {
                        "base_comment_version": 5, "actor": "June", "reason": "Superseded locally",
                    })
                    self.assertEqual(withdrawn["comment"]["lifecycle_state"], "withdrawn")
                    restored = self._request(base + f"/api/comments/{comment_id}/restore?path=paper.md", "POST", {
                        "base_comment_version": 6, "actor": "June",
                    })
                    self.assertEqual(restored["comment"]["id"], comment_id)
                    self.assertEqual(restored["comment"]["lifecycle_state"], "active")
                    self.assertEqual(restored["comment_version"], 7)

                    listed = self._request(base + "/api/comments?path=paper.md")
                    self.assertEqual(len(listed["comments"]), 1)
                    self.assertEqual(listed["comments_rev"], restored["comments_rev"])
                    history = self._request(base + f"/api/comments/{comment_id}/events?path=paper.md")
                    self.assertEqual(
                        [item["action"] for item in history["events"]],
                        ["create", "edit", "reply", "reply-edit", "reply-withdraw", "withdraw", "restore"],
                    )
                    self.assertTrue(all("content" not in item for item in history["events"]))
                    with open(server._comment_events_path(doc_path), encoding="utf-8") as fh:
                        ledger_text = fh.read()
                    self.assertNotIn("A synthetic sentence.", ledger_text)
                    self.assertNotIn("Human-edited synthetic finding.", ledger_text)
                    self.assertEqual(len(ledger_text.splitlines()), 7)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    def test_slice_a_migration_is_lossless_idempotent_and_legacy_readable(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            sidecar = os.path.join(tmp, "paper.md.comments.json")
            legacy = {
                "comments": [
                    {
                        "id": "c-ai", "kind": None, "author": "AI Reviewer",
                        "content": "Synthetic anchored finding.", "quote_text": "Exact synthetic quote.",
                        "source_locator": {"text_index": 12}, "source": "ai-review",
                        "review_state": "active", "finding_id": "F001",
                        "source_key": "review-fixture:F001",
                    },
                    {
                        "id": "c-overall", "kind": None, "author": "Assistant",
                        "content": "Synthetic overall note.", "quote_text": "",
                        "source": "selection-conversation", "source_key": "conversation:fixture:m1",
                    },
                ],
            }
            with open(sidecar, "w", encoding="utf-8") as fh:
                json.dump(legacy, fh, ensure_ascii=False)
            session_root = os.path.join(tmp, "review-sessions")
            os.makedirs(session_root)
            for index, status in enumerate(("ready", "failed"), 1):
                with open(os.path.join(session_root, f"review-{index:012x}.json"), "w", encoding="utf-8") as fh:
                    json.dump({
                        "id": f"review-{index:012x}", "doc_path": "paper.md",
                        "status": status, "findings": [],
                    }, fh)
            with open(sidecar, "rb") as fh:
                original = fh.read()

            dry_run = server.migrate_slice_a_data(tmp, apply=False)
            self.assertEqual((dry_run["comments_before"], dry_run["comments_after"]), (2, 2))
            self.assertEqual((dry_run["sessions_before"], dry_run["sessions_after"]), (2, 2))
            self.assertEqual(dry_run["kind_null_before"], 2)
            self.assertEqual((dry_run["kind_anchored_after"], dry_run["kind_overall_after"]), (1, 1))
            self.assertTrue(dry_run["finding_ids_preserved"])
            self.assertTrue(dry_run["source_keys_preserved"])
            with open(sidecar, "rb") as fh:
                self.assertEqual(fh.read(), original)

            applied = server.migrate_slice_a_data(tmp, apply=True)
            self.assertTrue(applied["backup_created"])
            migrated = server._read_json_file(sidecar, {})
            self.assertEqual(migrated["schema_version"], "comma-comments-view/v1.1")
            self.assertEqual(migrated["comments"][0]["finding_state"], "accepted")
            self.assertEqual(migrated["comments"][0]["lifecycle_state"], "active")
            self.assertEqual(migrated["comments"][1]["kind"], "overall")
            ledger = server._load_comment_events(os.path.join(tmp, "paper.md"))
            self.assertEqual([item["action"] for item in ledger], ["migrate", "migrate"])
            self.assertTrue(all("content" not in item for item in ledger))
            repeated = server.migrate_slice_a_data(tmp, apply=True)
            self.assertEqual(repeated["sidecars_requiring_rewrite"], 0)
            self.assertFalse(repeated["backup_created"])

            with tempfile.TemporaryDirectory() as failure_tmp:
                failed_sidecar = os.path.join(failure_tmp, "paper.md.comments.json")
                with open(failed_sidecar, "wb") as fh:
                    fh.write(original)
                with mock.patch.object(server, "_atomic_write_json", side_effect=OSError("controlled failure")):
                    with self.assertRaises(OSError):
                        server.migrate_slice_a_data(failure_tmp, apply=True)
                with open(failed_sidecar, "rb") as fh:
                    self.assertEqual(fh.read(), original)
                fallback = server._load_comments(os.path.join(failure_tmp, "paper.md"))
                self.assertEqual(len(fallback), 2)
                self.assertEqual(fallback[0]["finding_state"], "accepted")

    def test_review_discussion_and_incremental_writeback(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            body = "# Results\n\nThis tiny cohort proves broad clinical utility.\n"
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write(body)
            initial = {
                "tool": "claude", "returncode": 0, "elapsed_ms": 12,
                "output": json.dumps({
                    "summary": "证据边界需要收紧。",
                    "assistant_text": "已生成一条主要问题。",
                    "findings": [{
                        "id": "F001", "section": "Results",
                        "quote_text": "This tiny cohort proves broad clinical utility.",
                        "issue": "样本量不足以支持广泛临床外推。",
                        "action": "改为探索性结果并说明样本限制。", "priority": "P1",
                    }],
                }, ensure_ascii=False),
            }
            continued = {
                "tool": "claude", "returncode": 0, "elapsed_ms": 9,
                "output": json.dumps({
                    "assistant_text": "已把建议改为同时要求补充验证队列。",
                    "finding_ops": [{
                        "op": "update", "finding_id": "F001",
                        "patch": {"action": "改为探索性结果，并补充独立验证队列。"},
                    }],
                }, ensure_ascii=False),
            }
            review_root = os.path.join(tmp, "review-sessions")
            events = os.path.join(tmp, "events.jsonl")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "REVIEW_ROOT", review_root), \
                    mock.patch.object(server, "EVENTS_PATH", events), \
                    mock.patch.object(server, "_invoke_ai", side_effect=[initial, continued]):
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    started = self._request(base + "/api/review-sessions", "POST", {
                        "path": "paper.md", "tool": "claude", "writeback_policy": "auto-ready",
                    })
                    self.assertTrue(started["ok"])
                    self.assertEqual(len(started["writeback"]["created"]), 1)
                    session_id = started["session"]["id"]

                    updated = self._request(
                        base + f"/api/review-sessions/{session_id}/messages", "POST",
                        {"message": "把建议补充为还需要独立验证队列。"},
                    )
                    self.assertTrue(updated["ok"])
                    self.assertIsNone(updated["writeback"])
                    self.assertEqual(updated["session"]["status"], "preview")
                    self.assertEqual(len(updated["session"]["messages"]), 3)

                    comments = self._request(base + "/api/comments?path=paper.md")
                    self.assertEqual(len(comments["comments"]), 1)
                    self.assertNotIn("独立验证队列", comments["comments"][0]["content"])
                    sessions = self._request(base + "/api/review-sessions?path=paper.md")
                    self.assertEqual(sessions["sessions"][0]["applied_count"], 1)
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    def test_quote_conversation_branch_note_and_explicit_writeback(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            body = "# Results\n\nThis tiny cohort suggests a preliminary response.\n"
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write(body)
            responses = [
                {"tool": "codex", "returncode": 0, "elapsed_ms": 6,
                 "output": "这句话只支持探索性信号，不能外推疗效。"},
                {"tool": "codex", "returncode": 0, "elapsed_ms": 7,
                 "output": "在该分支假设下，还需要独立队列和预设终点。"},
            ]
            conversation_root = os.path.join(tmp, "conversations")
            events = os.path.join(tmp, "events.jsonl")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "CONVERSATION_ROOT", conversation_root), \
                    mock.patch.object(server, "EVENTS_PATH", events), \
                    mock.patch.object(server, "_invoke_ai", side_effect=responses):
                httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                try:
                    document = self._request(base + "/api/doc?path=paper.md")
                    started = self._request(base + "/api/conversations", "POST", {
                        "path": "paper.md", "base_rev": document["rev"], "tool": "codex",
                        "source_quote": {
                            "quote_text": "This tiny cohort suggests a preliminary response.",
                            "source_locator": {"text_index": body.index("This tiny cohort")},
                        },
                        "message": "这句话能支持什么结论？",
                    })
                    session_id = started["session"]["id"]
                    assistant_id = started["session"]["messages"][-1]["id"]
                    noted = self._request(base + f"/api/conversations/{session_id}/notes", "POST", {
                        "parent_message_id": assistant_id, "content": "这个边界判断保留。",
                    })
                    self.assertEqual(noted["note"]["role"], "note")

                    forked = self._request(base + f"/api/conversations/{session_id}/messages", "POST", {
                        "parent_message_id": assistant_id, "mode": "fork",
                        "message": "如果把它作为探索性终点呢？",
                    })
                    self.assertTrue(forked["branch_created"])
                    branch_messages = [m for m in forked["session"]["messages"] if m.get("branch_id") != "main"]
                    self.assertEqual(len(branch_messages), 2)
                    self.assertEqual(branch_messages[0]["branch_from_message_id"], assistant_id)

                    written = self._request(base + f"/api/conversations/{session_id}/writeback", "POST", {
                        "message_id": assistant_id,
                        "content": "证据边界：仅支持探索性信号，不能直接外推疗效。",
                    })
                    self.assertEqual(written["action"], "created")
                    repeated = self._request(base + f"/api/conversations/{session_id}/writeback", "POST", {
                        "message_id": assistant_id,
                        "content": "证据边界：仅支持探索性信号，不能直接外推疗效。",
                    })
                    self.assertEqual(repeated["action"], "skipped")
                    comments = self._request(base + "/api/comments?path=paper.md")["comments"]
                    self.assertEqual(len(comments), 1)
                    self.assertEqual(comments[0]["conversation_session_id"], session_id)

                    sessions = self._request(base + "/api/conversations?path=paper.md")["sessions"]
                    self.assertEqual(sessions[0]["branch_count"], 1)
                    self.assertEqual(sessions[0]["message_count"], 5)

                    with open(os.path.join(tmp, "paper.md"), "a", encoding="utf-8") as fh:
                        fh.write("\nChanged.\n")
                    conflict = self._request_error(
                        base + f"/api/conversations/{session_id}/writeback", "POST",
                        {"message_id": branch_messages[-1]["id"]},
                    )
                    self.assertEqual(conflict[0], 409)
                    self.assertTrue(conflict[1]["conflict"])
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=2)

    @staticmethod
    def _request(url, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise AssertionError(f"HTTP {exc.code}: {detail}") from exc

    @staticmethod
    def _request_error(url, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()
        raise AssertionError("request unexpectedly succeeded")

    @staticmethod
    def _request_raw(url, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.headers, response.read()


if __name__ == "__main__":
    unittest.main()
