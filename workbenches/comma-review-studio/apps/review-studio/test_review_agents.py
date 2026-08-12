#!/usr/bin/env python3
"""Gate 3 internal Academic Paper Review adapter contracts."""
from contextlib import contextmanager
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from unittest import mock

import review_agents
from review_executor import ReviewExecutor
import server


RUBRIC_HASH = "sha256:3b247cac76feb8508445cb3b1eaa8d68f4bbb57a8eed74f47e4c512185352a48"
BUNDLED_RUBRIC_HASH = "sha256:1d554b019b15ff6c4462e3e6a6b1a6c320b2539ba1a1c06bfda5681424d6d9fe"


class ReviewAgentTests(unittest.TestCase):
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
        for patch in patches:
            patch.start()
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
    def _agent_identity():
        return {
            "adapter_id": review_agents.ACADEMIC_ADAPTER_ID,
            "adapter_version": review_agents.ACADEMIC_ADAPTER_VERSION,
            "profile_id": review_agents.ACADEMIC_PROFILE_ID,
            "rubric_version": RUBRIC_HASH,
            "output_schema_version": review_agents.ACADEMIC_OUTPUT_SCHEMA_VERSION,
        }

    @staticmethod
    def _preflight_path():
        return "/api/review-preflight?" + urllib.parse.urlencode({
            "path": "paper.md",
            **ReviewAgentTests._agent_identity(),
        })

    def test_manifest_parses_and_registers_only_internal_academic_adapter(self):
        registry = review_agents.default_registry()
        manifests = registry.manifests()
        self.assertEqual(len(manifests), 1)
        manifest = manifests[0]
        self.assertEqual(manifest["schema_version"], "comma-review-agent-manifest/v1")
        self.assertTrue(review_agents.ACADEMIC_MANIFEST_PATH.is_file())
        self.assertEqual(manifest["adapter_id"], "academic-paper-review")
        self.assertEqual(manifest["kind"], "declarative-profile")
        self.assertEqual(manifest["trust"], "internal")
        with open(review_agents.ACADEMIC_MANIFEST_PATH, encoding="utf-8") as handle:
            manifest_file = json.load(handle)
        self.assertEqual(manifest_file["rubric_source"]["path"], "rubrics/academic-paper-review.md")
        self.assertNotIn("/Users/" + "a1234", manifest_file["rubric_source"]["path"])
        self.assertEqual(manifest_file["rubric_source"]["sha256"], BUNDLED_RUBRIC_HASH)
        self.assertEqual(manifest["rubric_source"]["sha256"], RUBRIC_HASH)
        self.assertEqual(manifest["rubric_source"]["mode"], "installed_workbench_reference")
        self.assertEqual(manifest["bundled_rubric_source"]["sha256"], BUNDLED_RUBRIC_HASH)
        self.assertEqual(manifest["rubric_version"], RUBRIC_HASH)
        self.assertEqual(manifest["rubric_lookup_order"][-1]["mode"], "bundled_compatibility_reference")
        self.assertEqual(manifest["writeback_default"], "preview")
        self.assertEqual(manifest["reviews"]["canonical_document"], True)
        self.assertEqual(manifest["reviews"]["original_materials"], "optional-evidence-sources")
        self.assertIn("web_search", manifest["forbidden_capabilities"])

    def test_prepared_review_request_includes_rubric_hash_and_input_contract(self):
        adapter = review_agents.default_registry().get(review_agents.ACADEMIC_ADAPTER_ID)
        review_input = {
            "schema_version": "comma-review-input/v1",
            "canonical_document": {
                "path": "paper.md",
                "revision": "rev-1",
                "sha256": "sha256:doc",
                "media_type": "text/markdown",
            },
            "original_materials": [{"kind": "evidence_source", "sha256": "sha256:pdf"}],
            "conversion_receipts": [{"id": "import-1", "sha256": "sha256:receipt"}],
        }
        prepared = adapter.prepare_review_request(
            document_body="# Result\n\nA claim.",
            document_path="paper.md",
            document_rev="rev-1",
            instruction="check claims",
            review_input=review_input,
            evidence_sources=[],
        )
        self.assertEqual(prepared.adapter_id, "academic-paper-review")
        self.assertEqual(prepared.rubric_version, RUBRIC_HASH)
        self.assertEqual(prepared.output_schema_version, "academic-paper-review-result/v1")
        self.assertEqual(prepared.review_input, review_input)
        self.assertIn(str(adapter.manifest["rubric_source"]["path"]), prepared.prompt)
        self.assertIn(RUBRIC_HASH, prepared.prompt)
        self.assertIn("Rubric mode: installed_workbench_reference", prepared.prompt)
        self.assertIn("ReviewAgentResult JSON schema", prepared.prompt)
        self.assertEqual(prepared.output_schema["properties"]["schema_version"]["const"],
                         "academic-paper-review-result/v1")

    def test_rubric_resolver_falls_back_to_bundled_copy_without_installed_skill(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with mock.patch.dict(os.environ, {"HOME": tmp, "CODEX_HOME": os.path.join(tmp, ".codex")}):
                source = review_agents._rubric_source()
        self.assertEqual(source["mode"], "bundled_compatibility_reference")
        self.assertEqual(source["sha256"], BUNDLED_RUBRIC_HASH)
        self.assertTrue(source["path"].endswith("review_agent_manifests/rubrics/academic-paper-review.md"))

    def test_review_agent_result_validation_strips_host_state_and_rejects_invalid_input(self):
        valid = {
            "schema_version": review_agents.ACADEMIC_OUTPUT_SCHEMA_VERSION,
            "summary": "summary",
            "recommendation": "minor revision",
            "confidence": "medium",
            "structured_sections": {"methods": {"risk": "medium"}},
            "metrics": {"finding_count": 1},
            "findings": [{
                "id": "F001",
                "issue_family": "claim_scope",
                "scope_intent": "quote",
                "quote_text": "A deterministic sentence.",
                "issue": "overclaim",
                "action": "qualify",
                "priority": "P1",
                "scientific_impact": "reduces unsupported inference",
                "no_quote_required": False,
                "finding_state": "accepted",
                "lifecycle_state": "active",
            }],
            "derived_artifacts": [],
        }
        normalized = review_agents.validate_review_agent_result(valid)
        self.assertNotIn("finding_state", normalized["findings"][0])
        self.assertNotIn("lifecycle_state", normalized["findings"][0])
        self.assertEqual(normalized["findings"][0]["decision"], "accepted")
        with self.assertRaises(review_agents.ReviewAgentError):
            review_agents.validate_review_agent_result({**valid, "schema_version": "wrong"})
        broken = json.loads(json.dumps(valid))
        broken["findings"][0].pop("action")
        with self.assertRaises(review_agents.ReviewAgentError):
            review_agents.validate_review_agent_result(broken)

    def test_academic_adapter_initial_run_is_preview_only_until_explicit_writeback(self):
        body = "# Discussion\n\nA unique controlled claim needs qualification.\n"
        agent_result = {
            "schema_version": review_agents.ACADEMIC_OUTPUT_SCHEMA_VERSION,
            "summary": "首轮 APR 预览。",
            "recommendation": "major revision",
            "confidence": "high",
            "structured_sections": {"discussion": {"assessment": "claim scope risk"}},
            "metrics": {"finding_count": 1},
            "findings": [{
                "id": "F001",
                "section": "Discussion",
                "scope_intent": "quote",
                "issue_family": "claim_scope",
                "quote_text": "A unique controlled claim needs qualification.",
                "context_before": "",
                "context_after": "",
                "evidence_quotes": [],
                "issue": "边界过宽。",
                "action": "限定结论。",
                "scientific_impact": "避免过度外推。",
                "priority": "P1",
                "no_quote_required": False,
                "finding_state": "accepted",
            }],
            "derived_artifacts": [{"kind": "structured-review", "sha256": "sha256:agent"}],
        }
        result = {
            "tool": "codex",
            "returncode": 0,
            "elapsed_ms": 4,
            "output": json.dumps(agent_result, ensure_ascii=False),
        }

        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with self._host(tmp, invoke_ai=lambda *_args, **_kwargs: result) as base:
                self._write_doc(tmp, body)
                preflight = self._request(base, self._preflight_path())["preflight"]
                response = self._request(base, "/api/review-runs", "POST", {
                    "path": "paper.md",
                    "base_rev": preflight["document"]["current_rev"],
                    "baseline_session_id": "",
                    "comments_rev": preflight["comments"]["comments_rev"],
                    "mode": "initial",
                    "tool": "codex",
                    **self._agent_identity(),
                })
                run = response["run"]
                session = response["session"]
                self.assertEqual(run["status"], "preview")
                self.assertEqual(session["status"], "preview")
                self.assertEqual(session["writeback_policy"], "preview")
                self.assertEqual(run["prepared_review_request"]["rubric_source"]["sha256"], RUBRIC_HASH)
                self.assertEqual(run["input"]["review_input"]["canonical_document"]["path"], "paper.md")
                self.assertEqual(run["operations"][0]["action"], "create")
                self.assertNotIn("finding_state", run["operations"][0]["proposed_comment"])
                self.assertEqual(run["derived_artifacts"][-1]["kind"], "result.md")
                self.assertEqual(response.get("writeback"), None)
                comments = self._request(base, "/api/comments?path=paper.md")["comments"]
                self.assertEqual(comments, [])

                writeback = self._request(base, f"/api/review-runs/{run['id']}/writeback", "POST", {
                    "base_rev": run["input"]["document_rev"],
                    "comments_rev": run["input"]["comments_rev"],
                    "accepted_operation_ids": [run["operations"][0]["id"]],
                })
                self.assertTrue(writeback["ok"])
                self.assertEqual(writeback["run"]["status"], "completed")
                comments = self._request(base, "/api/comments?path=paper.md")["comments"]
                self.assertEqual(len(comments), 1)
                self.assertEqual(comments[0]["finding_state"], "accepted")
                self.assertEqual(comments[0]["adapter_id"], "academic-paper-review")


if __name__ == "__main__":
    unittest.main()
