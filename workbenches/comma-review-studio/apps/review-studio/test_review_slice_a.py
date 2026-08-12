#!/usr/bin/env python3
"""Socket-free directed contracts for Scientific Review v1.1 Slice A."""

import os
import tempfile
import types
import unittest

import server


def direct_request(path, method, payload):
    handler = object.__new__(server.Handler)
    handler.path = path
    handler._guard = types.MethodType(lambda self: True, handler)
    handler._read_json = types.MethodType(lambda self: dict(payload), handler)
    handler._send_json = types.MethodType(
        lambda self, body, status=200, headers=None: {"status": status, **body},
        handler,
    )
    return server.Handler._mutate(handler, method)


class SliceAContracts(unittest.TestCase):
    def test_item_routes_lock_lifecycle_and_append_exact_events(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            doc = os.path.join(tmp, "paper.md")
            with open(doc, "w", encoding="utf-8") as fh:
                fh.write("# Synthetic\n\nExact controlled quote.\n")
            original_root, original_events = server.DATA_ROOT, server.EVENTS_PATH
            server.DATA_ROOT = tmp
            server.EVENTS_PATH = os.path.join(tmp, "events.jsonl")
            try:
                created = direct_request("/api/comments?path=paper.md", "POST", {
                    "source": "ai-review", "kind": "anchored", "actor": "AI Reviewer",
                    "quote_text": "Exact controlled quote.", "content": "Synthetic finding.",
                })
                self.assertEqual(created["status"], 200)
                comment_id = created["comment"]["id"]
                self.assertEqual(created["comment"]["finding_state"], "provisional")

                edited = direct_request(f"/api/comments/{comment_id}?path=paper.md", "PATCH", {
                    "base_comment_version": 1, "actor": "June", "content": "Edited synthetic finding.",
                })
                self.assertEqual(edited["comment_version"], 2)
                self.assertTrue(edited["comment"]["human_edited"])
                stale = direct_request(f"/api/comments/{comment_id}?path=paper.md", "PATCH", {
                    "base_comment_version": 1, "actor": "Stale", "content": "Blocked stale edit.",
                })
                self.assertEqual(stale["status"], 409)
                self.assertEqual(stale["current_comment"]["comment_version"], 2)

                replied = direct_request(f"/api/comments/{comment_id}/replies?path=paper.md", "POST", {
                    "base_comment_version": 2, "actor": "June", "content": "Synthetic reply.",
                })
                self.assertEqual(replied["comment_version"], 3)
                withdrawn = direct_request(f"/api/comments/{comment_id}?path=paper.md", "DELETE", {
                    "base_comment_version": 3, "actor": "June", "reason": "controlled",
                })
                self.assertEqual(withdrawn["comment"]["lifecycle_state"], "withdrawn")
                restored = direct_request(f"/api/comments/{comment_id}/restore?path=paper.md", "POST", {
                    "base_comment_version": 4, "actor": "June",
                })
                self.assertEqual(restored["comment"]["id"], comment_id)
                self.assertEqual(restored["comment_version"], 5)

                events = server._load_comment_events(doc, comment_id)
                self.assertEqual([item["action"] for item in events], ["create", "edit", "reply", "withdraw", "restore"])
                self.assertTrue(all("content" not in item for item in events))
                with open(server._comment_events_path(doc), encoding="utf-8") as fh:
                    ledger = fh.read()
                self.assertNotIn("Exact controlled quote.", ledger)
                self.assertNotIn("Edited synthetic finding.", ledger)
            finally:
                server.DATA_ROOT = original_root
                server.EVENTS_PATH = original_events

    def test_document_only_capability_boundary_has_rendered_fixture(self):
        with open(os.path.join(server.STATIC_ROOT, "app.js"), encoding="utf-8") as fh:
            app = fh.read()
        with open(os.path.join(server.ROOT, "test_headless.py"), encoding="utf-8") as fh:
            headless = fh.read()
        self.assertIn("appliesTo: 'comments.list', count: 'comments'", app)
        self.assertIn('fixture.id = \'document-only-fixture\'', headless)
        self.assertIn("commentCountNodes: root.querySelectorAll('[data-comment-count]').length", headless)
        self.assertIn("commentActionNodes: root.querySelectorAll('[data-comment-action]').length", headless)
        self.assertIn('"commentCountNodes": 0', headless)
        self.assertIn('"commentActionNodes": 0', headless)


if __name__ == "__main__":
    unittest.main()
