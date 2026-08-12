#!/usr/bin/env python3
"""SKL-102 Gate 1 agent-aware review run contracts."""
from contextlib import contextmanager
import json
import os
import tempfile
import unittest
from unittest import mock

import review_slice_b
import server


AGENT_A = {
    "adapter_id": "academic-paper-review",
    "adapter_version": "2026.07",
    "profile_id": "primary",
    "rubric_version": "rubric-a",
    "output_schema_version": "schema-a",
}
AGENT_B = {
    "adapter_id": "methods-reviewer",
    "adapter_version": "2026.07",
    "profile_id": "primary",
    "rubric_version": "rubric-a",
    "output_schema_version": "schema-a",
}
LEGACY_AGENT = {
    "adapter_id": "legacy",
    "adapter_version": "legacy",
    "profile_id": "legacy",
    "rubric_version": "legacy",
    "output_schema_version": "legacy",
}


def _base_finding(**overrides):
    raw = {
        "id": "F001",
        "section": "",
        "section_id": "",
        "scope_intent": "quote",
        "issue_family": "claim_scope",
        "quote_text": "A shared sentence needs narrower claims.",
        "issue": "结论边界过宽。",
        "action": "限定结论边界。",
        "priority": "P1",
        "decision": "accepted",
        "evidence_requirement": "",
        "rationale": "Synthetic agent-aware fixture.",
        "context_before": "",
        "context_after": "",
        "evidence_quotes": [],
        "no_quote_required": False,
    }
    raw.update(overrides)
    return raw


def _resolve(body, agent_identity, **overrides):
    raw = _base_finding(**overrides)
    finding = server._normalize_finding(raw, raw.get("id") or "F001")
    assert finding is not None
    return server._anchor_finding(
        finding, body, server._rev(body), "paper.md", agent_identity)


def _comment_from_finding(finding, *, comment_id, finding_state="accepted",
                          workflow_state="active"):
    return server._comment_record({
        "id": comment_id,
        "author": finding.get("adapter_id") or "AI Reviewer",
        "content": server._comment_content(finding),
        "priority": finding.get("priority") or "P2",
        "source": "ai-review",
        "source_key": f"review-old:{finding.get('id')}",
        "finding_id": finding.get("id"),
        "finding_state": finding_state,
        "workflow": {"state": workflow_state},
        **server._finding_comment_payload(finding),
    }, strict=False)


class ReviewAgentAwareTests(unittest.TestCase):
    @contextmanager
    def _store(self, tmp):
        with mock.patch.object(server, "DATA_ROOT", tmp), \
                mock.patch.object(server, "REVIEW_ROOT", os.path.join(tmp, "review-sessions")), \
                mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
            server._ACTIVE_REVIEW_RUNS.clear()
            yield
            server._ACTIVE_REVIEW_RUNS.clear()

    @staticmethod
    def _write_doc(tmp, body):
        path = os.path.join(tmp, "paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    @staticmethod
    def _save_running_session(agent_identity, *, session_suffix, doc_rev, comments_rev):
        session_id = f"review-{session_suffix}"
        run_id = f"run-{session_suffix}"
        fields = server._review_agent_fields(agent_identity)
        run = {
            "schema_version": "comma-review-run/v1",
            "id": run_id,
            "session_id": session_id,
            "mode": "initial",
            **fields,
            "input": {"document_rev": doc_rev, "comments_rev": comments_rev},
            "operations": [],
            "status": "running",
            "created_at": "2026-07-21T10:00:00",
            "updated_at": "2026-07-21T10:00:00",
        }
        session = {
            "id": session_id,
            "doc_path": "paper.md",
            "base_rev": doc_rev,
            "document_rev": doc_rev,
            **fields,
            "tool": "codex",
            "status": "running",
            "findings": [],
            "writeback_receipts": [],
            "run": run,
            "created_at": "2026-07-21T10:00:00",
            "updated_at": "2026-07-21T10:00:00",
        }
        server._save_session(session)
        return session, run

    @staticmethod
    def _save_completed_session(session_suffix, agent_identity, *, doc_rev, comments,
                                comments_rev, completed_at):
        fields = server._review_agent_fields(agent_identity)
        session = {
            "id": f"review-{session_suffix}",
            "doc_path": "paper.md",
            "base_rev": doc_rev,
            "document_rev": doc_rev,
            "comments_rev": comments_rev,
            "comments_snapshot": review_slice_b.comment_snapshot(comments),
            **fields,
            "status": "completed",
            "completed_at": completed_at,
            "updated_at": completed_at,
            "findings": [],
            "writeback_receipts": [],
        }
        server._save_session(session)
        return session

    def test_inflight_key_keeps_same_adapter_idempotent_without_cross_agent_reuse(self):
        body = "# Discussion\n\nA shared sentence needs narrower claims.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._store(tmp):
                doc = self._write_doc(tmp, body)
                doc_rev = server._rev(server._read_doc(doc))
                comments_rev = server._save_comments(doc, [])
                _, run_a = self._save_running_session(
                    AGENT_A, session_suffix="aaaaaaaaaaaa",
                    doc_rev=doc_rev, comments_rev=comments_rev)
                _, run_b = self._save_running_session(
                    AGENT_B, session_suffix="bbbbbbbbbbbb",
                    doc_rev=doc_rev, comments_rev=comments_rev)
                key_a = server._review_run_active_key(
                    "paper.md", doc_rev, comments_rev, "initial", "", AGENT_A)
                key_b = server._review_run_active_key(
                    "paper.md", doc_rev, comments_rev, "initial", "", AGENT_B)
                self.assertNotEqual(key_a, key_b)
                server._ACTIVE_REVIEW_RUNS[key_a] = run_a["id"]
                server._ACTIVE_REVIEW_RUNS[key_b] = run_b["id"]

                active_a = server._inflight_review_run(
                    "paper.md", doc_rev, comments_rev, "initial", "", AGENT_A)
                active_b = server._inflight_review_run(
                    "paper.md", doc_rev, comments_rev, "initial", "", AGENT_B)

                self.assertEqual(active_a[1]["id"], run_a["id"])
                self.assertEqual(active_b[1]["id"], run_b["id"])
                self.assertEqual(server._inflight_review_run(
                    "paper.md", doc_rev, comments_rev, "initial", "", AGENT_A)[1]["id"], run_a["id"])

    def test_latest_completed_baseline_is_selected_per_adapter_and_legacy_is_explicit(self):
        body = "# Discussion\n\nA shared sentence needs narrower claims.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._store(tmp):
                doc = self._write_doc(tmp, body)
                doc_rev = server._rev(server._read_doc(doc))
                comments = []
                comments_rev = server._save_comments(doc, comments)
                self._save_completed_session(
                    "aaaaaaaaaaaa", AGENT_A, doc_rev=doc_rev, comments=comments,
                    comments_rev=comments_rev, completed_at="2026-07-21T12:00:00")
                self._save_completed_session(
                    "bbbbbbbbbbbb", AGENT_B, doc_rev=doc_rev, comments=comments,
                    comments_rev=comments_rev, completed_at="2026-07-21T10:00:00")
                os.makedirs(server.REVIEW_ROOT, exist_ok=True)
                with open(os.path.join(server.REVIEW_ROOT, "review-cccccccccccc.json"),
                          "w", encoding="utf-8") as handle:
                    json.dump({
                        "id": "review-cccccccccccc",
                        "doc_path": "paper.md",
                        "base_rev": doc_rev,
                        "document_rev": doc_rev,
                        "comments_rev": comments_rev,
                        "status": "completed",
                        "completed_at": "2026-07-21T13:00:00",
                        "updated_at": "2026-07-21T13:00:00",
                        "findings": [],
                    }, handle)

                self.assertEqual(
                    server._latest_completed_session("paper.md", AGENT_B)["id"],
                    "review-bbbbbbbbbbbb")
                preflight, state = server._review_preflight_state(doc, AGENT_B)
                self.assertEqual(preflight["baseline_session"]["id"], "review-bbbbbbbbbbbb")
                self.assertEqual(state["baseline"]["id"], "review-bbbbbbbbbbbb")
                legacy = server._latest_completed_session("paper.md", LEGACY_AGENT)
                self.assertEqual(legacy["id"], "review-cccccccccccc")
                self.assertEqual(legacy["adapter_id"], "legacy")

    def test_finding_lineage_key_and_fl_id_include_adapter_identity(self):
        body = "# Discussion\n\nA shared sentence needs narrower claims.\n"
        finding_a = _resolve(body, AGENT_A)
        finding_a_repeat = _resolve(body, AGENT_A, id="F999")
        finding_b = _resolve(body, AGENT_B)

        self.assertEqual(finding_a["finding_lineage_key"], finding_a_repeat["finding_lineage_key"])
        self.assertEqual(finding_a["finding_lineage_id"], finding_a_repeat["finding_lineage_id"])
        self.assertNotEqual(finding_a["finding_lineage_key"], finding_b["finding_lineage_key"])
        self.assertNotEqual(finding_a["finding_lineage_id"], finding_b["finding_lineage_id"])
        self.assertTrue(finding_a["finding_lineage_key"].startswith(
            "agent|academic-paper-review|2026.07|primary|rubric-a|"))
        self.assertEqual(finding_b["adapter_id"], "methods-reviewer")

    def test_resurfacing_notice_and_lineage_mute_do_not_cross_adapter_scope(self):
        body = "# Discussion\n\nA shared sentence needs narrower claims.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._store(tmp):
                doc = self._write_doc(tmp, body)
                finding_a = _resolve(body, AGENT_A)
                finding_b = _resolve(body, AGENT_B, id="F777")
                comment_a = _comment_from_finding(
                    finding_a, comment_id="c-agent-a",
                    finding_state="withdrawn", workflow_state="declined_once")
                comment_b = _comment_from_finding(
                    finding_b, comment_id="c-agent-b",
                    finding_state="accepted", workflow_state="active")

                ops_b = server._normalize_run_operations([{
                    "id": "op-agent-b",
                    "action": "create",
                    "finding_id": "F777",
                    "proposed_comment": _base_finding(id="F777"),
                }], body, server._rev(body), "paper.md", [comment_a], AGENT_B)
                self.assertEqual(ops_b[0]["action"], "create")
                self.assertEqual(ops_b[0]["target_comment_id"], "")
                self.assertNotIn("resurfacing_notice", ops_b[0])

                ops_a = server._normalize_run_operations([{
                    "id": "op-agent-a",
                    "action": "create",
                    "finding_id": "F999",
                    "proposed_comment": _base_finding(id="F999"),
                }], body, server._rev(body), "paper.md", [comment_a], AGENT_A)
                self.assertEqual(ops_a[0]["action"], "keep")
                self.assertEqual(ops_a[0]["target_comment_id"], "c-agent-a")
                self.assertTrue(ops_a[0]["resurfacing_notice"]["previous_declined"])

                server._save_comments(doc, [comment_a, comment_b])
                muted = server._mute_finding_lineage(doc, "c-agent-a", actor="June")
                by_id = {comment["id"]: comment for comment in muted["comments"]}
                self.assertEqual(by_id["c-agent-a"]["workflow"]["state"], "muted_by_user")
                self.assertEqual(by_id["c-agent-b"]["workflow"]["state"], "active")
                self.assertEqual(muted["event"]["details"]["adapter_id"], "academic-paper-review")


if __name__ == "__main__":
    unittest.main()
