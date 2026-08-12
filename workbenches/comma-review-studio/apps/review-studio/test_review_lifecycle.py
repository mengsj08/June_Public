#!/usr/bin/env python3
"""SKL-99 cross-run finding lifecycle contracts."""
from contextlib import contextmanager
import copy
import os
import tempfile
import unittest
from unittest import mock

import server


def _base_finding(**overrides):
    raw = {
        "id": "F001",
        "section": "",
        "section_id": "",
        "scope_intent": "quote",
        "issue_family": "template_repetition",
        "quote_text": "Template phrase repeats.",
        "issue": "同一模板化问题重复出现。",
        "action": "合并成一条主 finding 处理。",
        "priority": "P1",
        "decision": "accepted",
        "evidence_requirement": "",
        "rationale": "Synthetic lifecycle fixture.",
        "context_before": "",
        "context_after": "",
        "evidence_quotes": [],
        "no_quote_required": False,
    }
    raw.update(overrides)
    return raw


def _resolve(body, raw):
    finding = server._normalize_finding(raw, raw.get("id") or "F001")
    assert finding is not None
    return server._anchor_finding(finding, body, server._rev(body), "paper.md")


class ReviewLifecycleTests(unittest.TestCase):
    @contextmanager
    def _store(self, tmp):
        with mock.patch.object(server, "DATA_ROOT", tmp), \
                mock.patch.object(server, "REVIEW_ROOT", os.path.join(tmp, "review-sessions")), \
                mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
            yield

    @staticmethod
    def _write_doc(tmp, body):
        path = os.path.join(tmp, "paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    @staticmethod
    def _comment_from_finding(finding, *, comment_id="c-lineage", finding_state="accepted",
                              workflow_state="active", comment_version=1, replies=None):
        return server._comment_record({
            "id": comment_id,
            "author": "AI Reviewer",
            "content": server._comment_content(finding),
            "priority": finding.get("priority") or "P2",
            "source": "ai-review",
            "source_key": f"review-old:{finding.get('id')}",
            "finding_id": finding.get("id"),
            "finding_state": finding_state,
            "workflow": {"state": workflow_state},
            "comment_version": comment_version,
            "replies": replies or [],
            **server._finding_comment_payload(finding),
        }, strict=False)

    @staticmethod
    def _save_run(doc, comments, operations, *, suffix="222222222222"):
        body = server._read_doc(doc)
        comments_rev = server._save_comments(doc, comments)
        session = {
            "id": f"review-{suffix}",
            "doc_path": "paper.md",
            "base_rev": server._rev(body),
            "document_rev": server._rev(body),
            "tool": "codex",
            "status": "preview",
            "findings": [
                op["proposed_comment"] for op in operations
                if isinstance(op.get("proposed_comment"), dict)
            ],
            "messages": [],
            "writeback_receipts": [],
            "run": {
                "schema_version": "comma-review-run/v1",
                "id": f"run-{suffix}",
                "session_id": f"review-{suffix}",
                "parent_session_id": "review-old",
                "mode": "forced-full",
                "input": {
                    "document_rev": server._rev(body),
                    "comments_rev": comments_rev,
                    "changed_block_ids": [],
                    "affected_comment_ids": [item.get("id") for item in comments],
                },
                "operations": operations,
                "model_receipt": {"tool": "mock", "returncode": 0},
                "writeback_receipt_id": "",
                "status": "preview",
                "created_at": "2026-07-20T10:00:00",
                "updated_at": "2026-07-20T10:00:00",
            },
        }
        server._save_session(session)
        return session, session["run"]

    def test_10_and_11_are_covered_by_existing_slice_c_contracts(self):
        # Fixture 10: test_review_slice_c.py::test_atomic_writeback_is_idempotent_and_requires_explicit_human_update
        # covers human_edited targets and requires explicit acceptance before overwrite.
        # Fixture 11: test_review_slice_c.py::test_document_comment_and_operation_drift_return_409_without_partial_write
        # covers document/comment revision drift and no-partial-write locks.
        self.assertTrue(True)

    def test_12_ten_repeated_findings_compress_to_one_lineage_with_occurrences(self):
        body = "# Results\n\n" + "\n\n".join(["Template phrase repeats." for _ in range(10)]) + "\n"
        findings = [
            _resolve(body, _base_finding(id=f"F{i:03d}", quote_text="Template phrase repeats."))
            for i in range(1, 11)
        ]
        operations = server._initial_run_operations(findings)
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["aggregation"]["input_operation_count"], 10)
        self.assertEqual(operations[0]["aggregation"]["user_visible_finding_count"], 1)
        self.assertEqual(len(operations[0]["proposed_comment"]["evidence_occurrences"]), 10)
        self.assertEqual(operations[0]["proposed_comment"]["evidence_summary"]["verified_occurrence_count"], 10)

    def test_13_declined_finding_resurfaces_on_same_lineage_and_can_be_muted(self):
        body = "# Discussion\n\nTemplate phrase repeats.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._store(tmp):
                doc = self._write_doc(tmp, body)
                old_finding = _resolve(body, _base_finding(id="F001"))
                old_comment = self._comment_from_finding(
                    old_finding, finding_state="withdrawn", workflow_state="declined_once")
                new_finding = _resolve(body, _base_finding(id="F999"))
                operations = server._normalize_run_operations([{
                    "id": "op-resurface", "action": "create", "finding_id": "F999",
                    "supersedes_finding_id": "", "target_comment_id": "",
                    "reason": "", "proposed_comment": _base_finding(id="F999"),
                }], body, server._rev(body), "paper.md", [old_comment])
                self.assertEqual(len(operations), 1)
                operation = operations[0]
                self.assertEqual(operation["action"], "keep")
                self.assertEqual(operation["target_comment_id"], "c-lineage")
                self.assertTrue(operation["resurfacing_notice"]["previous_declined"])
                self.assertTrue(operation["resurfacing_notice"]["same_blocks_unchanged"])
                self.assertTrue(operation["resurfacing_notice"]["mute_available"])
                _, run = self._save_run(doc, [old_comment], operations)
                server._confirm_review_run_writeback(run["id"], {
                    "base_rev": run["input"]["document_rev"],
                    "comments_rev": run["input"]["comments_rev"],
                    "accepted_operation_ids": ["op-resurface"],
                })
                resurfaced = server._load_comments(doc)[0]
                self.assertEqual(resurfaced["workflow"]["state"], "resurfaced")
                self.assertEqual(resurfaced["review_history"][-1]["state"], "resurfaced")
                muted = server._mute_finding_lineage(doc, "c-lineage", actor="June")
                self.assertEqual(muted["comment"]["workflow"]["state"], "muted_by_user")
                actions = [event["action"] for event in server._load_comment_events(doc)]
                self.assertIn("lineage-resurfaced", actions)
                self.assertIn("lineage-muted", actions)
                self.assertEqual(new_finding["finding_lineage_id"], old_finding["finding_lineage_id"])

    def test_13b_resurfacing_notice_message_uses_verified_hash_state(self):
        body = "# Discussion\n\nTemplate phrase repeats.\n"
        old_finding = _resolve(body, _base_finding(id="F001"))
        proposed = _resolve(body, _base_finding(id="F999"))
        old_comment = self._comment_from_finding(
            old_finding, finding_state="withdrawn", workflow_state="declined_once")

        unchanged = server._lineage_notice(old_comment, proposed)
        self.assertEqual(unchanged["block_hash_state"], "unchanged")
        self.assertEqual(unchanged["message"], "上轮未采纳；相关原文自上轮未变化；本轮再次提出")

        changed_comment = copy.deepcopy(old_comment)
        changed_comment["evidence_occurrences"][0]["block_hash"] = "sha256:changed"
        changed = server._lineage_notice(changed_comment, proposed)
        self.assertEqual(changed["block_hash_state"], "changed")
        self.assertEqual(changed["message"], "上轮未采纳；相关原文自上轮已变化；本轮再次提出")
        self.assertNotIn("未变化", changed["message"])

        unverified_comment = copy.deepcopy(old_comment)
        unverified_comment["evidence_occurrences"][0].pop("block_hash", None)
        unverified = server._lineage_notice(unverified_comment, proposed)
        self.assertEqual(unverified["block_hash_state"], "unverified")
        self.assertEqual(unverified["message"], "上轮未采纳；本轮再次提出（原文变化状态未核验）")
        self.assertNotIn("未变化", unverified["message"])

    def test_14_candidate_resolved_is_pending_confirmation_not_auto_close(self):
        body = "# Results\n\nA unique controlled claim needs qualification.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._store(tmp):
                doc = self._write_doc(tmp, body)
                finding = _resolve(body, _base_finding(
                    id="F001",
                    issue_family="claim_scope",
                    quote_text="A unique controlled claim needs qualification.",
                    issue="结论边界过宽。",
                    action="限定结论。"))
                comment = self._comment_from_finding(finding, comment_id="c-resolve")
                operations = server._normalize_run_operations([{
                    "id": "op-resolved", "action": "candidate_resolved",
                    "finding_id": "F001", "supersedes_finding_id": "F001",
                    "target_comment_id": "c-resolve", "reason": "explicitly rechecked",
                    "proposed_comment": None,
                    "resolution_review": {
                        "before_text": "A unique controlled claim needs qualification.",
                        "after_text": "A unique controlled claim is now qualified.",
                        "new_evidence": "The current text narrows the claim.",
                    },
                }], body, server._rev(body), "paper.md", [comment])
                self.assertEqual(operations[0]["action"], "candidate_resolved")
                _, run = self._save_run(doc, [comment], operations)
                server._confirm_review_run_writeback(run["id"], {
                    "base_rev": run["input"]["document_rev"],
                    "comments_rev": run["input"]["comments_rev"],
                    "accepted_operation_ids": ["op-resolved"],
                })
                candidate = server._load_comments(doc)[0]
                self.assertEqual(candidate["workflow"]["state"], "candidate_resolved")
                self.assertEqual(candidate["finding_state"], "accepted")
                self.assertEqual(candidate["resolution_review"]["new_evidence"], "The current text narrows the claim.")
                confirmed = server._confirm_candidate_resolved(doc, ["c-resolve"], actor="June")[-1]["comment"]
                self.assertEqual(confirmed["workflow"]["state"], "resolved")
                restored = server._restore_candidate_resolved(doc, ["c-resolve"], actor="June")[-1]["comment"]
                self.assertEqual(restored["workflow"]["state"], "active")
                actions = [event["action"] for event in server._load_comment_events(doc)]
                self.assertIn("candidate-resolved", actions)
                self.assertIn("candidate-resolved-confirmed", actions)
                self.assertIn("candidate-resolved-restored", actions)

    def test_15_location_refinement_respects_existing_user_discussion(self):
        body = "# Discussion\n\nSpecific refined quote appears once.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._store(tmp):
                doc = self._write_doc(tmp, body)
                section_finding = _resolve(body, _base_finding(
                    id="F001",
                    scope_intent="document",
                    issue_family="structure",
                    quote_text="",
                    no_quote_required=True,
                    issue="全文结构问题。",
                    action="重排结构。"))
                quote_finding = _resolve(body, _base_finding(
                    id="F777",
                    issue_family="structure",
                    quote_text="Specific refined quote appears once.",
                    issue="全文结构问题。",
                    action="重排结构。"))
                quiet_comment = self._comment_from_finding(section_finding, comment_id="c-quiet")
                discussed_comment = self._comment_from_finding(
                    section_finding, comment_id="c-discussed", comment_version=2,
                    replies=[{"id": "reply-1", "author": "June", "content": "Keep thread here."}])
                quiet_ops = server._normalize_run_operations([{
                    "id": "op-refine", "action": "create", "finding_id": "F777",
                    "supersedes_finding_id": "", "target_comment_id": "",
                    "reason": "", "proposed_comment": _base_finding(
                        id="F777", issue_family="structure",
                        quote_text="Specific refined quote appears once.",
                        issue="全文结构问题。", action="重排结构。"),
                }], body, server._rev(body), "paper.md", [quiet_comment])
                self.assertEqual(quiet_ops[0]["action"], "update")
                self.assertEqual(quiet_ops[0]["lineage_transition"], "placement_refined")
                discussed_ops = server._normalize_run_operations([{
                    "id": "op-link", "action": "create", "finding_id": "F777",
                    "supersedes_finding_id": "", "target_comment_id": "",
                    "reason": "", "proposed_comment": _base_finding(
                        id="F777", issue_family="structure",
                        quote_text="Specific refined quote appears once.",
                        issue="全文结构问题。", action="重排结构。"),
                }], body, server._rev(body), "paper.md", [discussed_comment])
                self.assertEqual(discussed_ops[0]["action"], "keep")
                self.assertEqual(discussed_ops[0]["lineage_transition"], "evidence_link_added")
                _, run = self._save_run(doc, [discussed_comment], discussed_ops, suffix="333333333333")
                server._confirm_review_run_writeback(run["id"], {
                    "base_rev": run["input"]["document_rev"],
                    "comments_rev": run["input"]["comments_rev"],
                    "accepted_operation_ids": ["op-link"],
                })
                after = server._load_comments(doc)[0]
                self.assertEqual(after["placement"]["scope"], "document")
                self.assertFalse(after.get("source_locator"))
                self.assertEqual(len(after["evidence_links"]), 1)
                self.assertEqual(server._load_comment_events(doc)[0]["action"], "evidence-link-added")


if __name__ == "__main__":
    unittest.main()
