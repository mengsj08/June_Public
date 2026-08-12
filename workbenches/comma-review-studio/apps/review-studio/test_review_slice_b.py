#!/usr/bin/env python3
"""Scientific Review v1.1 Slice B API and orchestration contracts."""
from contextlib import contextmanager
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from review_executor import ReviewExecutor
import review_slice_b
import server


class SliceBTests(unittest.TestCase):
    @contextmanager
    def _host(self, tmp, *, invoke_ai=None):
        review_root = os.path.join(tmp, "review-sessions")
        events = os.path.join(tmp, "events.jsonl")
        executor = ReviewExecutor(os.path.join(tmp, "executor-traces"))
        patches = [
            mock.patch.object(server, "DATA_ROOT", tmp),
            mock.patch.object(server, "REVIEW_ROOT", review_root),
            mock.patch.object(server, "EVENTS_PATH", events),
            mock.patch.object(server, "_REVIEW_EXECUTOR", executor),
            mock.patch.object(server, "_ACTIVE_REVIEW_RUNS", {}),
        ]
        if invoke_ai is not None:
            patches.append(mock.patch.object(server, "_invoke_ai", side_effect=invoke_ai))
        entered = []
        for patch in patches:
            entered.append(patch.start())
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
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
            return json.load(response)

    @staticmethod
    def _write_doc(tmp, body):
        path = os.path.join(tmp, "paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    @staticmethod
    def _baseline(doc, comments, *, findings=None):
        body = server._read_doc(doc)
        server._snapshot_version(doc, body, kind="baseline", force_entry=True)
        comments_rev = server._save_comments(doc, comments)
        session = {
            "id": "review-aaaaaaaaaaaa",
            "doc_path": "paper.md",
            "base_rev": server._rev(body),
            "document_rev": server._rev(body),
            "comments_rev": comments_rev,
            "comments_snapshot": review_slice_b.comment_snapshot(comments),
            "status": "completed",
            "completed_at": "2026-07-19T10:00:00",
            "updated_at": "2026-07-19T10:00:00",
            "findings": findings or [],
        }
        server._save_session(session)
        return session

    def test_preflight_routes_local_and_protected_edits_without_body_duplication(self):
        baseline_body = """# Introduction

Local framing sentence.

Another local paragraph.

# Methods

METHODS-PROTECTED-CONTENT.
"""
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, baseline_body)
                self._baseline(doc, [])
                low_risk_body = baseline_body.replace(
                    "Local framing sentence.", "Locally clarified framing sentence.")
                self._write_doc(tmp, low_risk_body)
                low = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                self.assertEqual(low["recommended_mode"], "incremental")
                self.assertFalse(low["document"]["protected_sections_touched"])
                self.assertIn("Introduction", low["document"]["affected_sections"])
                self.assertNotIn("Locally clarified framing sentence", json.dumps(low))
                self.assertTrue(all("source_locator" in row and "hash" in row
                                    for row in low["document"]["changed_blocks"]))

                protected_body = baseline_body.replace(
                    "METHODS-PROTECTED-CONTENT.", "METHODS-PROTECTED-CONTENT-CHANGED.")
                self._write_doc(tmp, protected_body)
                protected = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                self.assertEqual(protected["recommended_mode"], "full")
                self.assertTrue(protected["document"]["protected_sections_touched"])
                self.assertIn("methods", protected["document"]["protected_sections"])
                self.assertEqual(protected["allowed_modes"], ["incremental", "forced-full"])

    def test_frontend_preflight_modal_uses_run_api_and_exposes_all_routes(self):
        with open(os.path.join(server.STATIC_ROOT, "editor.html"), encoding="utf-8") as handle:
            html = handle.read()
        with open(os.path.join(server.STATIC_ROOT, "app.js"), encoding="utf-8") as handle:
            script = handle.read()
        self.assertIn('id="review-preflight-modal"', html)
        self.assertIn('id="review-preflight-primary"', html)
        self.assertIn('id="review-preflight-force"', html)
        self.assertIn('id="review-preflight-incremental"', html)
        self.assertIn('/api/review-preflight?path=', script)
        self.assertIn("apiJson('/api/review-runs'", script)
        self.assertIn("primary.dataset.mode = 'view-latest'", script)
        self.assertIn("primary.dataset.mode = 'incremental'", script)
        self.assertIn("primary.dataset.mode = 'forced-full'", script)
        self.assertNotIn('review-auto-writeback', html + script)

    def test_every_protected_category_forces_full_routing(self):
        baseline_body = """# Abstract

ABSTRACT-CONTROL.

# Methods

METHODS-CONTROL.

# Results

RESULTS-CONTROL.

# Conclusion

CONCLUSION-CONTROL.

# References

REFERENCES-CONTROL.

# Discussion

As summarized in Figure 2, the controlled signal remains local.
"""
        cases = [
            ("ABSTRACT-CONTROL", "ABSTRACT-CHANGED", "abstract"),
            ("METHODS-CONTROL", "METHODS-CHANGED", "methods"),
            ("RESULTS-CONTROL", "RESULTS-CHANGED", "results"),
            ("CONCLUSION-CONTROL", "CONCLUSION-CHANGED", "conclusion"),
            ("REFERENCES-CONTROL", "REFERENCES-CHANGED", "references"),
            ("controlled signal remains local", "controlled signal changed locally", "figures-tables"),
        ]
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, baseline_body)
                self._baseline(doc, [])
                for old, new, category in cases:
                    self._write_doc(tmp, baseline_body.replace(old, new))
                    preflight = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                    self.assertEqual(preflight["recommended_mode"], "full", category)
                    self.assertIn(category, preflight["document"]["protected_sections"], category)

    def test_legacy_baseline_without_comments_snapshot_routes_conservatively(self):
        body = "# Discussion\n\nA controlled legacy baseline.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, body)
                baseline = self._baseline(doc, [])
                baseline.pop("comments_rev")
                baseline.pop("comments_snapshot")
                server._save_session(baseline)
                preflight = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                self.assertEqual(preflight["comments"]["comparison_state"], "unknown")
                self.assertEqual(preflight["recommended_mode"], "full")

    def test_preflight_lists_comment_deltas_and_anchor_health(self):
        body = "# Discussion\n\nUnique anchor.\n\nRepeated anchor.\n\nRepeated anchor.\n"
        baseline_comments = [
            {"id": "c-edit", "kind": "overall", "content": "Before", "comment_version": 1},
            {"id": "c-withdraw", "kind": "overall", "content": "Active", "comment_version": 1},
            {"id": "c-restore", "kind": "overall", "content": "Hidden", "comment_version": 1,
             "lifecycle_state": "withdrawn"},
            {"id": "c-reply", "kind": "overall", "content": "Discuss", "comment_version": 1},
        ]
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, body)
                self._baseline(doc, baseline_comments)
                current = [
                    {"id": "c-edit", "kind": "overall", "content": "Human revision",
                     "comment_version": 2, "human_edited": True},
                    {"id": "c-withdraw", "kind": "overall", "content": "Active",
                     "comment_version": 2, "lifecycle_state": "withdrawn"},
                    {"id": "c-restore", "kind": "overall", "content": "Hidden",
                     "comment_version": 2, "lifecycle_state": "active"},
                    {"id": "c-reply", "kind": "overall", "content": "Discuss", "comment_version": 2,
                     "replies": [{"id": "reply-1", "content": "Reply", "state": "active"}]},
                    {"id": "c-add", "kind": "overall", "content": "Added", "comment_version": 1},
                    {"id": "c-ready", "kind": "anchored", "content": "Ready",
                     "quote_text": "Unique anchor.", "comment_version": 1},
                    {"id": "c-missing", "kind": "anchored", "content": "Missing",
                     "quote_text": "Absent anchor.", "comment_version": 1},
                    {"id": "c-ambiguous", "kind": "anchored", "content": "Ambiguous",
                     "quote_text": "Repeated anchor.", "comment_version": 1},
                ]
                server._save_comments(doc, current)
                preflight = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                self.assertEqual(preflight["recommended_mode"], "incremental")
                self.assertEqual({row["comment_id"] for row in preflight["comments"]["added"]},
                                 {"c-add", "c-ready", "c-missing", "c-ambiguous"})
                self.assertEqual([row["comment_id"] for row in preflight["comments"]["edited"]], ["c-edit"])
                self.assertEqual([row["comment_id"] for row in preflight["comments"]["withdrawn"]], ["c-withdraw"])
                self.assertEqual([row["comment_id"] for row in preflight["comments"]["restored"]], ["c-restore"])
                self.assertEqual([row["comment_id"] for row in preflight["comments"]["replied"]], ["c-reply"])
                self.assertEqual(preflight["anchors"]["ready"], 5)
                self.assertEqual([row["comment_id"] for row in preflight["anchors"]["missing"]], ["c-missing"])
                self.assertEqual([row["comment_id"] for row in preflight["anchors"]["ambiguous"]], ["c-ambiguous"])

    def test_incremental_run_has_immutable_snapshot_scoped_prompt_and_no_writeback(self):
        baseline_body = """# Introduction

Stable context before.

The local framing is cautious.

Stable context after.

Another unchanged introduction paragraph.

# Methods

METHODS-SHOULD-NOT-BE-SENT-IN-INCREMENTAL-PROMPT.
"""
        changed_body = baseline_body.replace(
            "The local framing is cautious.",
            "The local framing is cautious and explicitly exploratory.",
        )
        prompts = []

        def invoke(tool, prompt, **_kwargs):
            prompts.append(prompt)
            return {
                "tool": tool, "returncode": 0, "elapsed_ms": 7,
                "output": json.dumps({
                    "summary": "局部表述需保持探索性边界。",
                    "assistant_text": "已生成增量操作预览。",
                    "operations": [{
                        "id": "op-local", "action": "create", "finding_id": "F002",
                        "supersedes_finding_id": "", "target_comment_id": "",
                        "reason": "局部措辞变化",
                        "proposed_comment": {
                            "id": "F002", "section": "Introduction",
                            "quote_text": "The local framing is cautious and explicitly exploratory.",
                            "issue": "仍需限定适用范围。", "action": "补充适用范围。",
                            "priority": "P2", "decision": "accepted",
                            "evidence_requirement": "", "rationale": "避免外推。",
                            "context_before": "", "context_after": "",
                        },
                    }],
                }, ensure_ascii=False),
            }

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp, invoke_ai=invoke) as base:
                doc = self._write_doc(tmp, baseline_body)
                accepted_comment = server._comment_record({
                    "id": "c-accepted", "kind": "anchored", "content": "Accepted boundary",
                    "quote_text": "The local framing is cautious.", "finding_state": "accepted",
                    "finding_id": "F001", "source": "ai-review",
                }, strict=False)
                baseline_finding = server._normalize_finding({
                    "id": "F001", "section": "Introduction",
                    "quote_text": "The local framing is cautious.",
                    "issue": "Keep cautious", "action": "Retain boundary", "priority": "P2",
                }, "F001")
                baseline_finding["applied_comment_id"] = "c-accepted"
                baseline = self._baseline(doc, [accepted_comment], findings=[baseline_finding])
                human_edited_comment = dict(accepted_comment)
                human_edited_comment.update({
                    "content": "Human-edited accepted boundary",
                    "comment_version": 2,
                    "human_edited": True,
                })
                server._save_comments(doc, [human_edited_comment])
                self._write_doc(tmp, changed_body)
                preflight = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                before_comments = server._read_json_file(doc + ".comments.json", {})
                response = self._request(base, "/api/review-runs", "POST", {
                    "path": "paper.md",
                    "base_rev": preflight["document"]["current_rev"],
                    "baseline_session_id": baseline["id"],
                    "comments_rev": preflight["comments"]["comments_rev"],
                    "mode": "incremental", "tool": "codex",
                    "rubric": "Evidence-bound review", "instruction": "Only local consequences",
                })
                run = response["run"]
                immutable_input = json.loads(json.dumps(run["input"]))
                self.assertEqual(run["schema_version"], "comma-review-run/v1")
                self.assertEqual(run["status"], "preview")
                self.assertEqual(run["parent_session_id"], baseline["id"])
                self.assertEqual(run["input"]["changed_block_ids"],
                                 [row["id"] for row in preflight["document"]["changed_blocks"]])
                self.assertEqual(run["input"]["affected_comment_ids"], ["c-accepted"])
                self.assertEqual(run["operations"][0]["action"], "create")
                self.assertEqual(before_comments, server._read_json_file(doc + ".comments.json", {}))
                self.assertIn("The local framing is cautious and explicitly exploratory.", prompts[0])
                self.assertIn("Keep cautious", prompts[0])
                self.assertIn("Human-edited accepted boundary", prompts[0])
                self.assertNotIn("METHODS-SHOULD-NOT-BE-SENT-IN-INCREMENTAL-PROMPT", prompts[0])

                self._write_doc(tmp, changed_body + "\nLater disk change.\n")
                fetched = self._request(base, f"/api/review-runs/{run['id']}")["run"]
                self.assertEqual(fetched["input"], immutable_input)
                legacy = self._request(base, f"/api/review-sessions/{run['session_id']}")["session"]
                self.assertEqual(legacy["run"]["id"], run["id"])

    def test_initial_run_writes_only_provisional_findings(self):
        body = "# Discussion\n\nA unique controlled claim needs qualification.\n"
        result = {
            "tool": "codex", "returncode": 0, "elapsed_ms": 4,
            "output": json.dumps({
                "summary": "首评完成。", "assistant_text": "一条 provisional finding。",
                "findings": [{
                    "id": "F001", "section": "Discussion",
                    "quote_text": "A unique controlled claim needs qualification.",
                    "issue": "边界过宽。", "action": "限定结论。", "priority": "P1",
                    "decision": "accepted", "evidence_requirement": "",
                    "rationale": "受控测试。", "context_before": "", "context_after": "",
                }],
            }, ensure_ascii=False),
        }
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp, invoke_ai=lambda *_args, **_kwargs: result) as base:
                self._write_doc(tmp, body)
                preflight = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                self.assertEqual(preflight["recommended_mode"], "initial")
                response = self._request(base, "/api/review-runs", "POST", {
                    "path": "paper.md", "base_rev": preflight["document"]["current_rev"],
                    "baseline_session_id": "", "comments_rev": preflight["comments"]["comments_rev"],
                    "mode": "initial", "tool": "codex", "rubric": "", "instruction": "",
                })
                self.assertEqual(response["run"]["status"], "completed",
                                 response["run"].get("error"))
                comments = self._request(base, "/api/comments?path=paper.md")["comments"]
                self.assertEqual(len(comments), 1)
                self.assertEqual(comments[0]["finding_state"], "provisional")
                self.assertEqual(response["session"]["comments_rev"],
                                 self._request(base, "/api/comments?path=paper.md")["comments_rev"])
                after = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                self.assertEqual(after["recommended_mode"], "view-latest")

    def test_identical_inflight_posts_share_one_model_invocation(self):
        body = "# Discussion\n\nA deterministic sentence for idempotency.\n"
        entered = threading.Event()
        release = threading.Event()
        call_count = 0

        def invoke(tool, _prompt, **_kwargs):
            nonlocal call_count
            call_count += 1
            entered.set()
            release.wait(timeout=5)
            return {
                "tool": tool, "returncode": 0, "elapsed_ms": 2,
                "output": json.dumps({"summary": "", "assistant_text": "", "findings": []}),
            }

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp, invoke_ai=invoke) as base:
                self._write_doc(tmp, body)
                preflight = self._request(base, "/api/review-preflight?path=paper.md")["preflight"]
                payload = {
                    "path": "paper.md", "base_rev": preflight["document"]["current_rev"],
                    "baseline_session_id": "", "comments_rev": preflight["comments"]["comments_rev"],
                    "mode": "initial", "tool": "codex", "rubric": "", "instruction": "",
                }
                first_result = {}

                def first_post():
                    first_result.update(self._request(base, "/api/review-runs", "POST", payload))

                first_thread = threading.Thread(target=first_post)
                first_thread.start()
                self.assertTrue(entered.wait(timeout=2))
                duplicate = self._request(base, "/api/review-runs", "POST", payload)
                self.assertTrue(duplicate["idempotent"])
                self.assertEqual(duplicate["run"]["status"], "running")
                release.set()
                first_thread.join(timeout=5)
                self.assertFalse(first_thread.is_alive())
                self.assertEqual(call_count, 1)
                self.assertEqual(first_result["run"]["id"], duplicate["run"]["id"])


if __name__ == "__main__":
    unittest.main()
