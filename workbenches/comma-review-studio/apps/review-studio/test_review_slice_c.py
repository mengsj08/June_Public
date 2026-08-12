#!/usr/bin/env python3
"""Scientific Review v1.1 Slice C writeback and recovery contracts."""
from contextlib import contextmanager
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

import server


class SliceCTests(unittest.TestCase):
    @contextmanager
    def _host(self, tmp):
        review_root = os.path.join(tmp, "review-sessions")
        events = os.path.join(tmp, "events.jsonl")
        with mock.patch.object(server, "DATA_ROOT", tmp), \
                mock.patch.object(server, "REVIEW_ROOT", review_root), \
                mock.patch.object(server, "EVENTS_PATH", events):
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{httpd.server_address[1]}"
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

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
    def _request_error(cls, base, path, payload):
        try:
            cls._request(base, path, "POST", payload)
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
    def _proposal(body, quote, finding_id, *, issue="Controlled issue", action="Calibrate claim"):
        finding = {
            "id": finding_id,
            "section": "Discussion",
            "quote_text": quote,
            "issue": issue,
            "action": action,
            "priority": "P1",
            "decision": "accepted",
            "evidence_requirement": "",
            "rationale": "Synthetic contract fixture.",
            "context_before": "",
            "context_after": "",
            "version": 1,
            "applied_comment_id": "",
            "applied_signature": "",
        }
        return server._anchor_finding(
            finding, body, server._rev(body), "paper.md")

    @classmethod
    def _review_run(cls, doc, comments, *, suffix="111111111111", operations=None):
        body = server._read_doc(doc)
        comments_rev = server._save_comments(doc, comments)
        session_id = f"review-{suffix}"
        run_id = f"run-{suffix}"
        run = {
            "schema_version": "comma-review-run/v1",
            "id": run_id,
            "session_id": session_id,
            "parent_session_id": "review-aaaaaaaaaaaa",
            "mode": "incremental",
            "input": {
                "document_rev": server._rev(body),
                "comments_rev": comments_rev,
                "changed_block_ids": ["block-1"],
                "affected_comment_ids": [comment.get("id") for comment in comments],
            },
            "operations": operations or [],
            "model_receipt": {"tool": "mock", "returncode": 0},
            "writeback_receipt_id": "",
            "status": "preview",
            "created_at": "2026-07-20T10:00:00",
            "updated_at": "2026-07-20T10:00:00",
        }
        session = {
            "id": session_id,
            "doc_path": "paper.md",
            "base_rev": server._rev(body),
            "document_rev": server._rev(body),
            "tool": "codex",
            "status": "preview",
            "summary": "Synthetic operation preview.",
            "findings": [
                operation["proposed_comment"] for operation in run["operations"]
                if isinstance(operation.get("proposed_comment"), dict)
            ],
            "messages": [],
            "writeback_receipts": [],
            "run": run,
            "created_at": "2026-07-20T10:00:00",
            "updated_at": "2026-07-20T10:00:00",
        }
        server._save_session(session)
        return session, run

    def test_atomic_writeback_is_idempotent_and_requires_explicit_human_update(self):
        body = """# Discussion

Create target sentence is unique.

Human edited target sentence is unique.

Withdraw target sentence is unique.
"""
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, body)
                human = server._comment_record({
                    "id": "c-human", "kind": "anchored", "author": "June",
                    "content": "Human-controlled wording.",
                    "quote_text": "Human edited target sentence is unique.",
                    "source": "ai-review", "source_key": "review-old:F-HUMAN",
                    "finding_id": "F-HUMAN", "finding_state": "accepted",
                    "human_edited": True,
                })
                withdrawn = server._comment_record({
                    "id": "c-withdraw", "kind": "anchored", "author": "AI Reviewer",
                    "content": "Legacy finding to withdraw.",
                    "quote_text": "Withdraw target sentence is unique.",
                    "source": "ai-review", "source_key": "review-old:F-WITHDRAW",
                    "finding_id": "F-WITHDRAW", "finding_state": "accepted",
                })
                operations = [
                    {
                        "id": "op-create", "action": "create", "finding_id": "F-CREATE",
                        "supersedes_finding_id": "", "target_comment_id": "", "reason": "new",
                        "proposed_comment": self._proposal(
                            body, "Create target sentence is unique.", "F-CREATE"),
                        "human_edited_target": False,
                    },
                    {
                        "id": "op-human", "action": "update", "finding_id": "F-HUMAN",
                        "supersedes_finding_id": "F-HUMAN", "target_comment_id": "c-human",
                        "reason": "explicit overwrite required",
                        "proposed_comment": self._proposal(
                            body, "Human edited target sentence is unique.", "F-HUMAN",
                            issue="Updated issue", action="Explicitly accepted update"),
                        "human_edited_target": True,
                    },
                    {
                        "id": "op-withdraw", "action": "withdraw", "finding_id": "F-WITHDRAW",
                        "supersedes_finding_id": "F-WITHDRAW", "target_comment_id": "c-withdraw",
                        "reason": "finding no longer applies", "proposed_comment": None,
                        "human_edited_target": False,
                    },
                    {
                        "id": "op-keep", "action": "keep", "finding_id": "F-HUMAN",
                        "supersedes_finding_id": "", "target_comment_id": "c-human",
                        "reason": "lineage retained", "proposed_comment": None,
                        "human_edited_target": True,
                    },
                    {
                        "id": "op-blocked", "action": "blocked", "finding_id": "F-BLOCKED",
                        "supersedes_finding_id": "", "target_comment_id": "",
                        "reason": "anchor is ambiguous", "proposed_comment": None,
                        "human_edited_target": False,
                    },
                ]
                _, run = self._review_run(doc, [human, withdrawn], operations=operations)
                payload = {
                    "base_rev": run["input"]["document_rev"],
                    "comments_rev": run["input"]["comments_rev"],
                    "accepted_operation_ids": [
                        "op-create", "op-human", "op-withdraw", "op-keep",
                    ],
                }
                before = server._read_json_file(doc + ".comments.json", {})
                status, blocked = self._request_error(base, f"/api/review-runs/{run['id']}/writeback", {
                    **payload, "accepted_operation_ids": ["op-blocked"],
                })
                self.assertEqual(status, 409)
                self.assertEqual(blocked["code"], "blocked_operation")
                self.assertEqual(before, server._read_json_file(doc + ".comments.json", {}))

                status, response = self._request(
                    base, f"/api/review-runs/{run['id']}/writeback", "POST", payload)
                self.assertEqual(status, 200)
                self.assertFalse(response["idempotent"])
                receipt = response["writeback"]
                self.assertEqual(len(receipt["created"]), 1)
                self.assertEqual(len(receipt["updated"]), 1)
                self.assertEqual(len(receipt["withdrawn"]), 1)
                self.assertEqual(len(receipt["kept"]), 1)
                self.assertEqual(receipt["blocked"][0]["operation_id"], "op-blocked")

                comments = server._load_comments(doc)
                human_after = next(comment for comment in comments if comment["id"] == "c-human")
                withdraw_after = next(comment for comment in comments if comment["id"] == "c-withdraw")
                created = next(comment for comment in comments if comment.get("finding_id") == "F-CREATE")
                self.assertTrue(human_after["human_edited"])
                self.assertIn("Explicitly accepted update", human_after["content"])
                self.assertEqual(withdraw_after["finding_state"], "withdrawn")
                self.assertEqual(created["finding_state"], "accepted")
                self.assertEqual(created["applied_operation_id"], "op-create")
                events = server._load_comment_events(doc)
                operation_events = [event for event in events if event.get("review_run_id") == run["id"]]
                self.assertEqual(len(operation_events), 3)
                self.assertEqual(
                    {event["operation_id"] for event in operation_events},
                    {"op-create", "op-human", "op-withdraw"},
                )

                status, repeated = self._request(
                    base, f"/api/review-runs/{run['id']}/writeback", "POST", payload)
                self.assertEqual(status, 200)
                self.assertTrue(repeated["idempotent"])
                self.assertEqual(repeated["writeback"]["id"], receipt["id"])
                self.assertEqual(len(server._load_comment_events(doc)), len(events))
                self.assertEqual(len(server._load_comments(doc)), len(comments))

                after_success = server._read_json_file(doc + ".comments.json", {})
                status, conflict = self._request_error(
                    base, f"/api/review-runs/{run['id']}/writeback", {
                        **payload, "accepted_operation_ids": ["op-create"],
                    })
                self.assertEqual(status, 409)
                self.assertEqual(conflict["code"], "operation_ids_conflict")
                self.assertEqual(after_success, server._read_json_file(doc + ".comments.json", {}))

    def test_frontend_exposes_grouped_explicit_operation_confirmation(self):
        with open(os.path.join(server.STATIC_ROOT, "editor.html"), encoding="utf-8") as handle:
            html = handle.read()
        with open(os.path.join(server.STATIC_ROOT, "app.js"), encoding="utf-8") as handle:
            script = handle.read()
        with open(os.path.join(server.STATIC_ROOT, "editor.css"), encoding="utf-8") as handle:
            styles = handle.read()
        self.assertIn('id="review-accept-all"', html)
        self.assertIn('id="review-operation-selection"', html)
        self.assertIn("{ state: 'pending', label: '待处理'", script)
        self.assertIn("{ state: 'candidate_resolved', label: '待确认已解决'", script)
        self.assertIn("{ state: 'system_conflict', label: '系统冲突'", script)
        self.assertIn("{ state: 'more', label: '更多'", script)
        self.assertIn("OPERATION_ACTION_LABEL", script)
        self.assertIn("accepted_operation_ids: acceptedOperationIds", script)
        self.assertIn("function acceptAllNonBlockedOperations()", script)
        self.assertIn("human-edited", styles)
        self.assertIn("review-badge", styles)
        self.assertIn("location-details", styles)
        self.assertIn("data-operation-accept", script)

    def test_document_comment_and_operation_drift_return_409_without_partial_write(self):
        body = "# Discussion\n\nA stable synthetic sentence.\n"
        cases = ("document", "comments", "operations")
        for index, drift in enumerate(cases, 2):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as raw_tmp:
                tmp = os.path.realpath(raw_tmp)
                with self._host(tmp) as base:
                    doc = self._write_doc(tmp, body)
                    operation = {
                        "id": "op-create", "action": "create", "finding_id": "F001",
                        "supersedes_finding_id": "", "target_comment_id": "", "reason": "new",
                        "proposed_comment": self._proposal(
                            body, "A stable synthetic sentence.", "F001"),
                        "human_edited_target": False,
                    }
                    _, run = self._review_run(
                        doc, [], suffix=f"{index:012d}", operations=[operation])
                    payload = {
                        "base_rev": run["input"]["document_rev"],
                        "comments_rev": run["input"]["comments_rev"],
                        "accepted_operation_ids": ["op-create"],
                    }
                    if drift == "document":
                        self._write_doc(tmp, body + "\nExternal document edit.\n")
                    elif drift == "comments":
                        server._save_comments(doc, [server._comment_record({
                            "id": "c-external", "kind": "overall",
                            "content": "External comment mutation.",
                        })])
                    else:
                        payload["accepted_operation_ids"] = ["op-unknown"]
                    before = server._read_json_file(doc + ".comments.json", {})
                    status, response = self._request_error(
                        base, f"/api/review-runs/{run['id']}/writeback", payload)
                    self.assertEqual(status, 409)
                    self.assertTrue(response["conflict"])
                    self.assertEqual(before, server._read_json_file(doc + ".comments.json", {}))
                    self.assertEqual(server._load_operation_journal()["entries"], [])

    def test_startup_reconciliation_finalizes_after_comment_write_before_receipt(self):
        body = "# Discussion\n\nCrash recovery sentence is unique.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp) as base:
                doc = self._write_doc(tmp, body)
                operation = {
                    "id": "op-recover", "action": "create", "finding_id": "F-RECOVER",
                    "supersedes_finding_id": "", "target_comment_id": "", "reason": "new",
                    "proposed_comment": self._proposal(
                        body, "Crash recovery sentence is unique.", "F-RECOVER"),
                    "human_edited_target": False,
                }
                _, run = self._review_run(
                    doc, [], suffix="333333333333", operations=[operation])
                payload = {
                    "base_rev": run["input"]["document_rev"],
                    "comments_rev": run["input"]["comments_rev"],
                    "accepted_operation_ids": ["op-recover"],
                }
                with mock.patch.object(
                        server, "_finalize_operation_writeback",
                        side_effect=RuntimeError("simulated crash before receipt finalize")):
                    status, response = self._request_error(
                        base, f"/api/review-runs/{run['id']}/writeback", payload)
                self.assertEqual(status, 500)
                self.assertIn("simulated crash", response["error"])
                self.assertEqual(len(server._load_comments(doc)), 1)
                self.assertEqual(len(server._load_comment_events(doc)), 1)
                self.assertEqual(len(server._load_operation_journal()["entries"]), 1)
                crashed_session, crashed_run = server._load_review_run(run["id"])
                self.assertEqual(crashed_run["status"], "preview")
                self.assertFalse(crashed_session["writeback_receipts"])

                report = server._reconcile_operation_journal()
                self.assertEqual(report, {
                    "pending": 1, "finalized": 1, "resumed": 0, "inconsistent": 0,
                })
                recovered_session, recovered_run = server._load_review_run(run["id"])
                self.assertEqual(recovered_run["status"], "completed")
                self.assertEqual(recovered_session["status"], "completed")
                self.assertEqual(len(recovered_session["writeback_receipts"]), 1)
                self.assertTrue(
                    recovered_session["writeback_receipts"][0]["recovered_from_journal"])
                self.assertEqual(server._load_operation_journal()["entries"], [])
                self.assertEqual(len(server._load_comments(doc)), 1)
                self.assertEqual(len(server._load_comment_events(doc)), 1)

                repeated = server._reconcile_operation_journal()
                self.assertEqual(repeated["pending"], 0)
                self.assertEqual(len(server._load_comments(doc)), 1)
                self.assertEqual(len(server._load_comment_events(doc)), 1)


if __name__ == "__main__":
    unittest.main()
