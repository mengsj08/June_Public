#!/usr/bin/env python3
"""Scientific Review v1.1.1 red-team regression contracts."""
from contextlib import contextmanager
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock
import zipfile

import review_slice_b
import server


class ScientificReviewV111Tests(unittest.TestCase):
    @contextmanager
    def _host(self, tmp, *, invoke_ai=None):
        patches = [
            mock.patch.object(server, "DATA_ROOT", tmp),
            mock.patch.object(server, "REVIEW_ROOT", os.path.join(tmp, "review-sessions")),
            mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")),
        ]
        if invoke_ai is not None:
            patches.append(mock.patch.object(server, "_invoke_ai", side_effect=invoke_ai))
        for patch in patches:
            patch.start()
        server._ACTIVE_REVIEW_RUNS.clear()
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server._ACTIVE_REVIEW_RUNS.clear()
            for patch in reversed(patches):
                patch.stop()

    @staticmethod
    def _request(base, path, method="GET", payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    @classmethod
    def _request_error(cls, base, path, method, payload):
        try:
            cls._request(base, path, method, payload)
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.load(error)
            finally:
                error.close()
        raise AssertionError("request unexpectedly succeeded")

    @staticmethod
    def _write_doc(tmp, body):
        doc = os.path.join(tmp, "paper.md")
        with open(doc, "w", encoding="utf-8") as handle:
            handle.write(body)
        return doc

    @staticmethod
    def _read_text(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    @staticmethod
    def _completed_session(doc, *, suffix="aaaaaaaaaaaa"):
        body = server._read_doc(doc)
        comments = server._load_comments(doc)
        session = {
            "id": f"review-{suffix}",
            "doc_path": "paper.md",
            "base_rev": server._rev(body),
            "document_rev": server._rev(body),
            "comments_rev": server._comments_rev(comments),
            "comments_snapshot": review_slice_b.comment_snapshot(comments),
            "status": "completed",
            "completed_at": "2026-07-20T10:00:00",
            "findings": [], "messages": [], "writeback_receipts": [],
        }
        server._save_session(session)
        return session

    def test_01_reviewed_export_separates_truthful_comment_states(self):
        rendered = server._reviewed_markdown("# Synthetic\n", [
            {"id": "c-ok", "author": "June", "content": "Confirmed content.",
             "finding_state": "accepted", "lifecycle_state": "active"},
            {"id": "c-temp", "author": "AI", "content": "Provisional content.",
             "finding_state": "provisional", "lifecycle_state": "active"},
            {"id": "c-gone", "author": "AI", "content": "Withdrawn content.",
             "finding_state": "accepted", "lifecycle_state": "withdrawn",
             "withdraw_reason": "Superseded after verification."},
        ])
        self.assertIn("状态统计：已确认 1 · AI 暂定/待议 1 · 已撤回 1", rendered)
        self.assertIn("### 已确认批注", rendered)
        self.assertIn("### AI 暂定批注", rendered)
        self.assertIn("**AI 暂定 · 未经人工确认**", rendered)
        self.assertIn("### 已撤回记录（不作为当前评审意见）", rendered)
        self.assertIn("Withdrawn content.", rendered)
        self.assertIn("撤回原因：Superseded after verification.", rendered)
        self.assertLess(rendered.index("Confirmed content."), rendered.index("Provisional content."))
        self.assertLess(rendered.index("Provisional content."), rendered.index("Withdrawn content."))

    def test_02_acceptance_uses_real_finding_state_and_locked_events(self):
        body = "# Discussion\n\nSynthetic acceptance sentence.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, body)
                comments = [server._comment_record({
                    "id": "c-one", "kind": "overall", "content": "First",
                    "source": "ai-review", "finding_state": "provisional",
                }), server._comment_record({
                    "id": "c-two", "kind": "overall", "content": "Second",
                    "source": "ai-review", "finding_state": "provisional",
                })]
                server._save_comments(doc, comments)
                _, accepted = self._request(base, "/api/comments/c-one/accept", "POST", {
                    "path": "paper.md", "base_comment_version": 1, "actor": "June",
                })
                self.assertEqual(accepted["comment"]["finding_state"], "accepted")
                self.assertEqual(accepted["comment_version"], 2)
                self.assertEqual(accepted["event"]["action"], "finding-update")
                status, conflict = self._request_error(
                    base, "/api/comments/c-one/accept", "POST",
                    {"path": "paper.md", "base_comment_version": 1, "actor": "June"})
                self.assertEqual(status, 409)
                self.assertEqual(conflict["code"], "comment_version_conflict")
                _, store = self._request(base, "/api/comments?path=paper.md")
                _, bulk = self._request(base, "/api/comments/accept-provisional", "POST", {
                    "path": "paper.md", "comments_rev": store["comments_rev"], "actor": "June",
                })
                self.assertEqual(bulk["accepted_comment_ids"], ["c-two"])
                self.assertEqual(bulk["events"][0]["action"], "finding-update")
                self.assertTrue(all(item.get("finding_state") == "accepted" for item in bulk["comments"]))

        script = self._read_text(os.path.join(server.STATIC_ROOT, "app.js"))
        self.assertIn("function trueFindingState(finding)", script)
        self.assertIn("AI 暂定 · 未经人工确认", script)
        self.assertIn("接受全部暂定", script)
        self.assertIn("window.confirm(`确认接受全部", script)
        self.assertNotIn("finding.decision === 'accepted'", script)
        self.assertNotIn("data-decision=", script)

    def test_03_protected_section_red_team_counterexample_table(self):
        cases = [
            ("nested-methods", "## Methods\n\n### Statistical analysis\n\nAlpha model.\n",
             "## Methods\n\n### Statistical analysis\n\nBeta model.\n", "methods"),
            ("cn-statistics", "### 统计学分析\n\nAlpha model.\n",
             "### 统计学分析\n\nBeta model.\n", "methods"),
            ("participants", "### Participants\n\nAlpha cohort.\n",
             "### Participants\n\nBeta cohort.\n", "methods"),
            ("study-design", "### Study design\n\nAlpha design.\n",
             "### Study design\n\nBeta design.\n", "methods"),
            ("sample-size", "### Sample size\n\nAlpha estimate.\n",
             "### Sample size\n\nBeta estimate.\n", "methods"),
            ("outcomes", "### Outcome measures\n\nAlpha outcome.\n",
             "### Outcome measures\n\nBeta outcome.\n", "methods"),
            ("cn-eligibility", "### 纳入与排除标准\n\n甲标准。\n",
             "### 纳入与排除标准\n\n乙标准。\n", "methods"),
            ("findings", "## Findings\n\nAlpha finding.\n",
             "## Findings\n\nBeta finding.\n", "results"),
            ("headingless", "Alpha unheaded paragraph.\n",
             "Beta unheaded paragraph.\n", "unclassified"),
            ("pre-heading", "Alpha preface.\n\n## Discussion\n\nStable prose.\n",
             "Beta preface.\n\n## Discussion\n\nStable prose.\n", "unclassified"),
        ]
        for name, before, after, expected in cases:
            with self.subTest(name=name):
                baseline = review_slice_b.segment_markdown(before, body_rev="r1", task_path="paper.md")
                current = review_slice_b.segment_markdown(after, body_rev="r2", task_path="paper.md")
                changed = review_slice_b.compare_blocks(baseline, current)
                lookup = {block["id"]: block for block in current}
                protected = review_slice_b.protected_sections(changed, lookup)
                self.assertIn(expected, protected)
        nested = review_slice_b.segment_markdown(
            cases[0][2], body_rev="r2", task_path="paper.md")
        paragraph = next(item for item in nested if item["type"] == "paragraph")
        self.assertEqual(paragraph["section_path"], ["Methods", "Statistical analysis"])

    def test_04_legacy_routes_close_and_human_edit_blocks_downgrade(self):
        body = "# Discussion\n\nA unique legacy sentence.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp, invoke_ai=lambda *_args, **_kwargs: self.fail("CLI must not run")) as base:
                doc = self._write_doc(tmp, body)
                completed = self._completed_session(doc)
                status, response = self._request_error(base, "/api/review-sessions", "POST", {
                    "path": "paper.md", "base_rev": server._rev(body), "tool": "codex",
                })
                self.assertEqual(status, 409)
                self.assertEqual(response["code"], "review_preflight_required")
                self.assertIn("/api/review-preflight", response["preflight_url"])
                status, response = self._request_error(
                    base, f"/api/review-sessions/{completed['id']}/writeback", "POST", {})
                self.assertEqual(status, 409)
                self.assertEqual(response["code"], "legacy_writeback_closed")

                comment = server._comment_record({
                    "id": "c-human", "kind": "anchored", "content": "Human wording.",
                    "quote_text": "A unique legacy sentence.", "source": "ai-review",
                    "source_key": "review-bbbbbbbbbbbb:F001", "finding_state": "accepted",
                    "human_edited": True,
                })
                server._save_comments(doc, [comment])
                session = {
                    "id": "review-bbbbbbbbbbbb", "doc_path": "paper.md",
                    "base_rev": server._rev(body), "status": "preview",
                    "findings": [{
                        "id": "F001", "quote_text": "A unique legacy sentence.",
                        "issue": "Old issue", "action": "Old action", "priority": "P2",
                        "decision": "rejected", "context_before": "", "context_after": "",
                    }], "writeback_receipts": [],
                }
                result = server._writeback_session(session, doc)
                self.assertEqual(result["blocked"][0]["comment_id"], "c-human")
                self.assertIn("human-edited", result["blocked"][0]["reason"])
                self.assertEqual(server._load_comments(doc)[0]["finding_state"], "accepted")

    def test_05_startup_fails_stale_runs_and_registry_owns_inflight_truth(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp):
                doc = self._write_doc(tmp, "# Discussion\n\nSynthetic.\n")
                comments_rev = server._save_comments(doc, [])
                run = {
                    "id": "run-cccccccccccc", "status": "running", "mode": "initial",
                    "input": {"document_rev": server._rev(server._read_doc(doc)),
                              "comments_rev": comments_rev},
                }
                session = {
                    "id": "review-cccccccccccc", "doc_path": "paper.md", "status": "running",
                    "run": run, "findings": [], "writeback_receipts": [],
                }
                server._save_session(session)
                report = server._fail_stale_running_reviews()
                self.assertEqual(report, {"runs_failed": 1, "sessions_failed": 1})
                failed_session, failed_run = server._load_review_run(run["id"])
                self.assertEqual(failed_session["status"], "failed")
                self.assertEqual(failed_run["status"], "failed")
                self.assertEqual(server._inflight_review_run(
                    "paper.md", run["input"]["document_rev"], comments_rev, "initial"),
                    (None, None))
                failed_session["status"] = "running"
                failed_run["status"] = "running"
                server._save_session(failed_session)
                key = ("paper.md", run["input"]["document_rev"], comments_rev, "initial")
                server._ACTIVE_REVIEW_RUNS[key] = run["id"]
                active_session, active_run = server._inflight_review_run(*key)
                self.assertEqual(active_session["id"], failed_session["id"])
                self.assertEqual(active_run["id"], run["id"])

    def test_06_public_comment_create_ignores_privileged_fields(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                self._write_doc(tmp, "# Synthetic\n")
                _, response = self._request(base, "/api/comments", "POST", {
                    "path": "paper.md", "kind": "overall", "content": "Manual note.",
                    "actor": "June", "id": "attacker-id", "source_key": "attacker:key",
                    "applied_signature": "attacker-sig", "applied_operation_id": "attacker-op",
                    "finding_state": "accepted", "human_edited": True,
                })
                comment = response["comment"]
                self.assertNotEqual(comment["id"], "attacker-id")
                self.assertNotIn("source_key", comment)
                self.assertNotIn("applied_signature", comment)
                self.assertNotIn("applied_operation_id", comment)
                self.assertNotIn("finding_state", comment)
                self.assertFalse(comment["human_edited"])
                self.assertEqual(comment["source"], "manual")

    def test_07_journal_recovers_landed_comments_after_document_rev_change(self):
        body = "# Discussion\n\nRecovery quote is unique.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp):
                doc = self._write_doc(tmp, body)
                comments_rev = server._save_comments(doc, [])
                proposal = server._anchor_finding({
                    "id": "F-RECOVER", "quote_text": "Recovery quote is unique.",
                    "issue": "Boundary", "action": "Calibrate", "priority": "P1",
                    "decision": "accepted", "section": "Discussion",
                    "evidence_requirement": "", "rationale": "Synthetic",
                    "context_before": "", "context_after": "",
                }, body, server._rev(body), "paper.md")
                operation = {
                    "id": "op-recover", "action": "create", "finding_id": "F-RECOVER",
                    "supersedes_finding_id": "", "target_comment_id": "", "reason": "new",
                    "proposed_comment": proposal, "human_edited_target": False,
                }
                run = {
                    "id": "run-dddddddddddd", "status": "preview", "mode": "incremental",
                    "input": {"document_rev": server._rev(body), "comments_rev": comments_rev},
                    "operations": [operation], "writeback_receipt_id": "",
                }
                session = {
                    "id": "review-dddddddddddd", "doc_path": "paper.md", "status": "preview",
                    "tool": "codex", "run": run, "findings": [proposal],
                    "writeback_receipts": [],
                }
                server._save_session(session)
                payload = {
                    "base_rev": server._rev(body), "comments_rev": comments_rev,
                    "accepted_operation_ids": ["op-recover"],
                }
                with mock.patch.object(
                        server, "_finalize_operation_writeback",
                        side_effect=RuntimeError("crash before receipt")):
                    with self.assertRaisesRegex(RuntimeError, "crash before receipt"):
                        server._confirm_review_run_writeback(run["id"], payload)
                self.assertEqual(len(server._load_comments(doc)), 1)
                self._write_doc(tmp, body + "\nLater independent document edit.\n")
                report = server._reconcile_operation_journal()
                self.assertEqual(report["inconsistent"], 0)
                self.assertEqual(report["finalized"], 1)
                recovered_session, recovered_run = server._load_review_run(run["id"])
                self.assertEqual(recovered_run["status"], "completed")
                self.assertTrue(recovered_session["writeback_receipts"][0]["recovered"])
                self.assertTrue(recovered_session["writeback_receipts"][0]["recovered_from_journal"])

    def test_08_document_summary_is_revision_bound_stale_and_exported(self):
        outputs = []

        def invoke(tool, prompt, **kwargs):
            outputs.append((tool, prompt, kwargs.get("schema")))
            number = len(outputs)
            return {"tool": tool, "returncode": 0, "elapsed_ms": number, "output": json.dumps({
                "summary_3_6": ["要点一", "要点二", "要点三"],
                "thesis": f"核心论点 {number}",
                "evidence_scope": ["合成证据范围"],
                "major_conclusions": ["合成结论"],
                "limitations": ["合成限制"],
                "source_check_targets": ["合成来源核查"],
            }, ensure_ascii=False)}

        body = "# Discussion\n\nA synthetic summary body.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp, invoke_ai=invoke) as base:
                doc = self._write_doc(tmp, body)
                _, empty = self._request(base, "/api/document-summary?path=paper.md")
                self.assertIsNone(empty["summary"])
                payload = {"path": "paper.md", "base_rev": server._rev(body),
                           "tool": "codex", "regenerate": False}
                _, first = self._request(base, "/api/document-summary", "POST", payload)
                self.assertEqual(first["summary"]["schema_version"], "comma-document-summary/v1")
                self.assertEqual(first["summary"]["status"], "ready")
                self.assertEqual(len(first["summary"]["summary_3_6"]), 3)
                self.assertEqual(len(outputs), 1)
                _, reused = self._request(base, "/api/document-summary", "POST", payload)
                self.assertTrue(reused["reused"])
                self.assertEqual(reused["summary"]["id"], first["summary"]["id"])
                self.assertEqual(len(outputs), 1)
                payload["regenerate"] = True
                _, regenerated = self._request(base, "/api/document-summary", "POST", payload)
                self.assertNotEqual(regenerated["summary"]["id"], first["summary"]["id"])
                self.assertEqual(len(outputs), 2)
                ledger = server._load_summary_ledger(doc)
                self.assertEqual(len(ledger["summaries"]), 2)
                self.assertNotIn("output", ledger["summaries"][0].get("model_meta", {}))
                self._write_doc(tmp, body + "\nChanged revision.\n")
                _, stale = self._request(base, "/api/document-summary?path=paper.md")
                self.assertTrue(stale["stale"])
                self.assertEqual(stale["summary"]["status"], "stale")
                package = server._review_package(doc, server._read_doc(doc))
                with zipfile.ZipFile(io.BytesIO(package)) as archive:
                    exported = json.loads(archive.read("review/document-summaries.json"))
                    manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(len(exported["summaries"]), 2)
                self.assertEqual(manifest["contents"]["document_summaries"], 2)
                self.assertIn("A synthetic summary body.", outputs[0][1])
                self.assertIs(outputs[0][2], server._DOCUMENT_SUMMARY_SCHEMA)

        html = self._read_text(os.path.join(server.STATIC_ROOT, "editor.html"))
        script = self._read_text(os.path.join(server.STATIC_ROOT, "app.js"))
        self.assertIn('id="overview-summary-list"', html)
        self.assertIn("/api/document-summary", script)
        self.assertIn("STALE · 已过期", script)
        self.assertIn("未读取图片或图表像素", html)
        self.assertIn("未获取或全文核验所引用的文献", html)
        self.assertIn("未重新计算统计结果", html)

    def test_09_core_dual_normalization_aliases_are_completed(self):
        models = self._read_text(os.path.join(
            server.ROOT, "..", "..", "src", "core", "models.js"))
        self.assertIn("reviewRunId: String(first(input, 'reviewRunId', 'review_run_id')", models)
        self.assertIn("appliedSignature: String(first(input, 'appliedSignature', 'applied_signature')", models)
        self.assertIn("appliedOperationId: String(first(input, 'appliedOperationId', 'applied_operation_id')", models)

    def test_10_comment_event_append_fsyncs_complete_line(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            doc = self._write_doc(os.path.realpath(raw_tmp), "# Synthetic\n")
            with mock.patch.object(server.os, "fsync", wraps=server.os.fsync) as fsync:
                event = server._append_comment_event(
                    doc, comment_id="c-fsync", action="create", actor="June",
                    from_version=0, to_version=1,
                )
            self.assertEqual(fsync.call_count, 1)
            with open(server._comment_events_path(doc), "rb") as handle:
                raw = handle.read()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(json.loads(raw), event)

    def test_11_bad_comment_event_line_warns_and_preserves_later_good_line(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            doc = self._write_doc(os.path.realpath(raw_tmp), "# Synthetic\n")
            path = server._comment_events_path(doc)
            rows = [
                {"event_id": "ce-before", "comment_id": "c-one", "action": "create"},
                {"event_id": "ce-after", "comment_id": "c-two", "action": "edit"},
            ]
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(rows[0]) + "\n")
                handle.write('{"event_id":"ce-broken"\n')
                handle.write(json.dumps(rows[1]) + "\n")
            before = server.observability_warning_counts()["malformed_comment_event_lines"]
            stderr = io.StringIO()
            with mock.patch.object(server.sys, "stderr", stderr):
                loaded = server._load_comment_events(doc)
            after = server.observability_warning_counts()["malformed_comment_event_lines"]
            self.assertEqual([item["event_id"] for item in loaded], ["ce-before", "ce-after"])
            self.assertEqual(after, before + 1)
            self.assertIn("line 2 skipped", stderr.getvalue())
            self.assertNotIn("ce-broken", stderr.getvalue())

    def test_12_keep_preview_copy_disclaims_ai_reverification(self):
        script = self._read_text(os.path.join(server.STATIC_ROOT, "app.js"))
        self.assertIn("不变（表示本轮未改动，不代表 AI 重新逐条核验）", script)

    def test_13_public_comment_create_reassigns_duplicate_caller_id(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, "# Synthetic\n")
                existing = server._comment_record({
                    "id": "c-existing", "kind": "overall", "content": "Existing note.",
                    "actor": "June", "source": "manual",
                })
                server._save_comments(doc, [existing])
                _, response = self._request(base, "/api/comments", "POST", {
                    "path": "paper.md", "kind": "overall", "content": "New note.",
                    "actor": "June", "source": "manual", "id": "c-existing",
                })
                self.assertNotEqual(response["comment"]["id"], "c-existing")
                stored_ids = [item["id"] for item in server._load_comments(doc)]
                self.assertEqual(len(stored_ids), len(set(stored_ids)))
                self.assertIn("c-existing", stored_ids)


if __name__ == "__main__":
    unittest.main()
