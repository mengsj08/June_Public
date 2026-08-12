#!/usr/bin/env python3
"""Graceful no-CLI behavior for all AI entrypoints."""
from contextlib import contextmanager
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

import review_agents
import server


GUIDE = "未检测到可用 AI provider，请启动并登录 BigApple 桌面应用，或安装并登录 Codex/Claude CLI"
PROJECT_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))


class ReviewCliDegradationTests(unittest.TestCase):
    @contextmanager
    def _host(self, tmp):
        executor = server.ReviewExecutor(os.path.join(tmp, "executor-traces"))
        patches = [
            mock.patch.object(server, "DATA_ROOT", tmp),
            mock.patch.object(server, "REVIEW_ROOT", os.path.join(tmp, "review-sessions")),
            mock.patch.object(server, "CONVERSATION_ROOT", os.path.join(tmp, "conversations")),
            mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")),
            mock.patch.object(server, "_REVIEW_EXECUTOR", executor),
            mock.patch.object(server, "_ACTIVE_REVIEW_RUNS", {}),
            mock.patch.object(server, "gateway_status", return_value={
                "available": False,
                "ready": False,
                "auth_state": "not_running",
                "version": "",
                "detail": "未发现正在运行的 BigApple Desktop Gateway",
                "gateway_url": "",
            }),
            mock.patch.dict(os.environ, {
                "COMMA_REVIEW_CODEX_BIN": os.path.join(tmp, "missing-codex"),
                "COMMA_REVIEW_CLAUDE_BIN": os.path.join(tmp, "missing-claude"),
            }, clear=False),
        ]
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
            return response.status, json.load(response)

    @classmethod
    def _request_error(cls, base, path, method="POST", payload=None):
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
            "rubric_version": review_agents.ACADEMIC_RUBRIC_CANONICAL_SHA256,
            "output_schema_version": review_agents.ACADEMIC_OUTPUT_SCHEMA_VERSION,
        }

    def assertCliUnavailable(self, status, payload):
        self.assertEqual(status, 503)
        self.assertEqual(payload["code"], "cli_unavailable")
        self.assertIn(GUIDE, payload["error"])

    def test_windows_open_browser_uses_startfile(self):
        with mock.patch.object(server.sys, "platform", "win32"), \
                mock.patch.object(server.os, "startfile", create=True) as startfile, \
                mock.patch.object(server.subprocess, "Popen") as popen:
            server._open_browser("http://127.0.0.1:8891")
        startfile.assert_called_once_with("http://127.0.0.1:8891")
        popen.assert_not_called()

    def test_windows_launchers_match_shell_entrypoint(self):
        with open(os.path.join(PROJECT_ROOT, "start-review-studio.cmd"), encoding="utf-8") as handle:
            cmd = handle.read()
        with open(os.path.join(PROJECT_ROOT, "start-review-studio.ps1"), encoding="utf-8") as handle:
            ps1 = handle.read()
        for script in (cmd, ps1):
            self.assertIn("apps", script)
            self.assertIn("review-studio", script)
            self.assertIn("server.py", script)
            self.assertIn("--doctor --serve --open", script)

    def test_all_ai_entrypoints_return_clear_cli_guidance_when_no_cli_is_ready(self):
        body = "# Results\n\nThis selected claim needs context.\n"
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            self._write_doc(tmp, body)
            with self._host(tmp) as base:
                _, runtime = self._request(base, "/api/runtime/capabilities")
                self.assertFalse(any(tool["ready"] for tool in runtime["tools"]))
                self.assertTrue(all(not tool["capabilities"]["structured_review"] for tool in runtime["tools"]))

                _, doc = self._request(base, "/api/doc?path=paper.md")
                preflight_path = "/api/review-preflight?" + urllib.parse.urlencode({
                    "path": "paper.md",
                    **self._agent_identity(),
                })
                _, preflight = self._request(base, preflight_path)

                checks = [
                    ("/api/ai-run", {
                        "path": "paper.md", "tool": "codex",
                        "selection": "This selected claim needs context.",
                        "prompt": "解释这段。",
                    }),
                    ("/api/conversations", {
                        "path": "paper.md", "base_rev": doc["rev"], "tool": "codex",
                        "source_quote": {
                            "quote_text": "This selected claim needs context.",
                            "source_locator": {"text_index": body.index("This selected")},
                        },
                        "message": "讨论这段。",
                    }),
                    ("/api/document-summary", {
                        "path": "paper.md", "base_rev": doc["rev"],
                        "tool": "codex", "regenerate": False,
                    }),
                    ("/api/review-runs", {
                        "path": "paper.md",
                        "base_rev": preflight["preflight"]["document"]["current_rev"],
                        "comments_rev": preflight["preflight"]["comments"]["comments_rev"],
                        "baseline_session_id": "",
                        "mode": "initial",
                        "tool": "codex",
                        **self._agent_identity(),
                    }),
                    ("/api/evidence-sources/evidence-aaaaaaaaaaaaaaaa/summary", {
                        "path": "paper.md", "tool": "codex",
                        "confirmed_data_transfer": True,
                    }),
                ]
                for path, payload in checks:
                    with self.subTest(path=path):
                        status, error = self._request_error(base, path, "POST", payload)
                        self.assertCliUnavailable(status, error)

        with open(os.path.join(server.STATIC_ROOT, "app.js"), encoding="utf-8") as handle:
            script = handle.read()
        with open(os.path.join(server.STATIC_ROOT, "editor.css"), encoding="utf-8") as handle:
            css = handle.read()
        self.assertIn(GUIDE, script)
        self.assertIn("AI · ${readyCount} 可用", script)
        self.assertIn("cli-status.offline", css)


if __name__ == "__main__":
    unittest.main()
