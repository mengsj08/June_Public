#!/usr/bin/env python3
"""BigApple Gateway discovery, transport, and Executor receipt contracts."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from unittest import mock

import bigapple_gateway
import review_executor
import server


class _FakeBigAppleHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, _format, *_args):
        return

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.requests.append(("GET", self.path, None))
        if self.path == "/api/health":
            return self._json({"status": "ok"})
        if self.path.startswith("/api/chat/sessions/session-1/messages"):
            return self._json({"messages": []})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        self.requests.append(("POST", self.path, payload))
        if self.path == "/api/chat/sessions":
            return self._json({
                "session": {
                    "id": "session-1",
                    "provider_id": "provider-test",
                    "model": "model-test",
                },
            }, 201)
        if self.path == "/api/chat":
            frames = [
                {"type": "text", "data": "SSE "},
                {"type": "text", "data": "assistant "},
                {"type": "text", "data": "result"},
                {"type": "final_text", "data": "SSE assistant result"},
                {
                    "type": "result",
                    "data": json.dumps({
                        "usage": {"input_tokens": 10, "output_tokens": 3},
                        "is_error": False,
                        "session_id": "runtime-session",
                        "provider_key": "fixture-provider",
                        "provider_debug": {"raw_provider_response": {"ok": True}},
                    }, ensure_ascii=False),
                },
                {"type": "done", "data": ""},
            ]
            chunk = "".join(
                "data: " + json.dumps(frame, ensure_ascii=False) + "\n\n"
                for frame in frames
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        return self._json({"error": "not found"}, 404)


class BigAppleGatewayTests(unittest.TestCase):
    def setUp(self):
        _FakeBigAppleHandler.requests = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeBigAppleHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def test_gateway_discovery_health_and_sse_submission(self):
        with mock.patch.dict(os.environ, {"COMMA_REVIEW_BIGAPPLE_GATEWAY": self.base}, clear=False):
            self.assertEqual(bigapple_gateway.discover_gateway(), self.base)
            status = bigapple_gateway.gateway_status()
            self.assertTrue(status["ready"])
            result = bigapple_gateway.submit_task(
                "Return a concise result.",
                working_directory=os.getcwd(),
                timeout=5,
                schema={"type": "object"},
            )
        self.assertEqual(result["output"], "SSE assistant result")
        self.assertNotIn("usage", result["output"])
        self.assertNotIn("provider_debug", result["output"])
        self.assertEqual(result["session_id"], "session-1")
        chat_payload = next(payload for method, path, payload in _FakeBigAppleHandler.requests
                            if method == "POST" and path == "/api/chat")
        self.assertIn("Return only one JSON object", chat_payload["content"])

    def test_executor_wraps_bigapple_gateway_in_standard_receipt(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            metadata = {
                "run_id": "run-bigapple",
                "trace_root": os.path.join(tmp, "trace-bigapple"),
                "queued_at": "2026-07-21T10:00:00",
                "adapter": {"id": "legacy"},
                "profile": {"id": "legacy"},
                "skill": {"id": "test"},
                "provider": {"tool": "bigapple", "transport": "bigapple_gateway"},
                "input_manifest": {"document": {"path": "paper.md"}},
                "prompt_template_hash": "sha256:template",
                "prompt_hash": "sha256:prompt",
            }
            with mock.patch.dict(os.environ, {"COMMA_REVIEW_BIGAPPLE_GATEWAY": self.base}, clear=False):
                result = review_executor.invoke_provider(
                    "bigapple", "prompt", timeout=5, schema=None,
                    executable=self.base, cwd=tmp, metadata=metadata)
            receipt = result["receipt"]
            self.assertEqual(receipt["schema_version"], "comma-review-run-receipt/v1")
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["provider"]["tool"], "bigapple")
            self.assertEqual(receipt["provider"]["transport"], "bigapple_gateway")
            self.assertEqual(receipt["web_policy"], {"mode": "disabled", "web_search_used": False})
            self.assertEqual(result["output"], "SSE assistant result")
            self.assertNotIn("provider_debug", result["output"])
            self.assertTrue(os.path.isfile(os.path.join(result["trace_root"], "receipt.json")))
            self.assertTrue(receipt["trace"]["events_sha256"].startswith("sha256:"))

    def test_server_reports_bigapple_as_unavailable_without_gateway(self):
        with mock.patch.object(server, "gateway_status", return_value={
            "available": False,
            "ready": False,
            "auth_state": "not_running",
            "version": "",
            "detail": "未发现正在运行的 BigApple Desktop Gateway",
            "gateway_url": "",
        }):
            status = server._cli_status("bigapple")
            self.assertFalse(status["ready"])
            with self.assertRaises(server.CliUnavailableError) as ctx:
                server._require_cli("bigapple")
        self.assertIn("Gateway 未运行", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
