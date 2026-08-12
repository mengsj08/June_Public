#!/usr/bin/env python3
"""Deterministic tests for the structured review/writeback core."""
import json
import os
import tempfile
import unittest
from unittest import mock

import server


class ReviewOrchestratorTests(unittest.TestCase):
    def test_json_fence_and_finding_normalization(self):
        parsed = server._extract_json(
            '```json\n{"summary":"ok","findings":[{"quote_text":"Exact quote here",'
            '"issue":"Broad claim","action":"Narrow it","priority":"P1"}]}\n```'
        )
        rows = server._normalize_findings(parsed["findings"])
        self.assertEqual(rows[0]["id"], "F001")
        self.assertEqual(rows[0]["priority"], "P1")
        self.assertEqual(rows[0]["decision"], "accepted")

    def test_anchor_states(self):
        body = "# Result\n\nA unique clinical claim needs evidence.\n\nRepeated line.\n\nRepeated line.\n"
        rev = server._rev(body)
        findings = server._normalize_findings([
            {"id": "F001", "quote_text": "A unique clinical claim needs evidence.",
             "issue": "Broad", "action": "Qualify it"},
            {"id": "F002", "quote_text": "Repeated line.",
             "issue": "Unclear", "action": "Disambiguate"},
        ])
        server._reanchor_findings(findings, body, rev, "paper.md")
        self.assertEqual(findings[0]["anchor_state"], "ready")
        self.assertEqual(findings[0]["section"], "Result")
        self.assertEqual(findings[1]["anchor_state"], "ambiguous")

    def test_idempotent_writeback_and_revision_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "paper.md")
            events = os.path.join(tmp, "events.jsonl")
            body = "# Result\n\nA unique clinical claim needs evidence.\n\nRepeated line.\n\nRepeated line.\n"
            with open(doc, "w", encoding="utf-8") as fh:
                fh.write(body)
            session = {
                "id": "review-aaaaaaaaaaaa",
                "base_rev": server._rev(body),
                "status": "ready",
                "findings": server._normalize_findings([
                    {"id": "F001", "quote_text": "A unique clinical claim needs evidence.",
                     "issue": "Broad claim", "action": "Narrow it", "priority": "P1"},
                    {"id": "F002", "quote_text": "Repeated line.",
                     "issue": "Repeated", "action": "Choose one", "priority": "P2"},
                ]),
                "writeback_receipts": [],
            }
            with mock.patch.object(server, "EVENTS_PATH", events), \
                    mock.patch.object(server, "DATA_ROOT", tmp):
                first = server._writeback_session(session, doc)
                self.assertEqual(len(first["created"]), 1)
                self.assertEqual(len(first["blocked"]), 1)
                second = server._writeback_session(session, doc)
                self.assertEqual(len(second["created"]), 0)
                self.assertEqual(second["skipped"][0]["reason"], "unchanged")
                session["findings"][0]["action"] = "Narrow it and cite the cohort."
                third = server._writeback_session(session, doc)
                self.assertEqual(len(third["updated"]), 1)
                with open(doc + ".comments.json", encoding="utf-8") as fh:
                    comments = json.load(fh)["comments"]
                self.assertEqual(len(comments), 1)
                self.assertIn("cite the cohort", comments[0]["content"])

                session["findings"][0]["decision"] = "rejected"
                withdrawn = server._writeback_session(session, doc)
                self.assertEqual(withdrawn["updated"][0]["action"], "withdrawn")
                with open(doc + ".comments.json", encoding="utf-8") as fh:
                    comments = json.load(fh)["comments"]
                self.assertEqual(comments[0]["finding_state"], "withdrawn")
                self.assertEqual(comments[0]["lifecycle_state"], "active")

                with open(doc, "a", encoding="utf-8") as fh:
                    fh.write("\nChanged after review.\n")
                conflict = server._writeback_session(session, doc)
                self.assertTrue(conflict["conflict"])
                self.assertEqual(session["status"], "needs_rebase")

    def test_discussion_removal_keeps_ledger_fact(self):
        session = {"findings": server._normalize_findings([
            {"id": "F001", "quote_text": "Exact quote here", "issue": "Issue", "action": "Action"}
        ])}
        server._apply_finding_ops(session, [{"op": "remove", "finding_id": "F001"}])
        self.assertEqual(len(session["findings"]), 1)
        self.assertEqual(session["findings"][0]["decision"], "rejected")


if __name__ == "__main__":
    unittest.main()
