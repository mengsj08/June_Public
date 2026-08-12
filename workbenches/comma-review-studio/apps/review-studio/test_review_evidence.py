#!/usr/bin/env python3
"""Synthetic PDF EvidenceSource extraction and provenance contracts."""
import json
import io
import os
import stat
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from unittest import mock

import server


def _write_executable(path, source):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR)
    return path


class ReviewEvidenceTests(unittest.TestCase):
    def test_pdf_extraction_thresholds_are_deterministic(self):
        status, metrics = server._classify_pdf_pages([
            {"page": 1, "text": "A" * 2200},
            {"page": 2, "text": "B" * 300},
        ])
        self.assertEqual(status, "usable")
        self.assertEqual(metrics["text_usable_ratio"], 1.0)

        status, metrics = server._classify_pdf_pages([
            {"page": 1, "text": "A" * 250},
            {"page": 2, "text": ""},
            {"page": 3, "text": ""},
        ])
        self.assertEqual(status, "partial")
        self.assertEqual(metrics["text_usable_pages"], 1)

        status, metrics = server._classify_pdf_pages([
            {"page": 1, "text": ""}, {"page": 2, "text": "caption"},
        ])
        self.assertEqual(status, "image_only")
        self.assertLess(metrics["total_non_whitespace_chars"], 200)

    def test_pdf_becomes_separate_page_anchored_evidence_source(self):
        if not server._pdf_extractor_status()["ready"]:
            self.skipTest(server._pdf_extractor_status()["detail"])
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# Manuscript\n\nThe canonical Markdown remains separate.\n")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd, thread, base = self._start_server()
                try:
                    page = "Controlled PDF evidence sentence. " * 45
                    source = self._synthetic_pdf([page, page])
                    attached = self._attach(base, "paper.md", "context.pdf", source)
                    record = attached["source"]
                    self.assertFalse(attached["reused"])
                    self.assertEqual(record["access_level"], "uploaded_pdf")
                    self.assertEqual(record["extraction_status"], "usable")
                    self.assertFalse(record["full_text_confirmed"])
                    self.assertEqual(record["metrics"]["page_count"], 2)
                    self.assertEqual(record["metrics"]["text_usable_pages"], 2)
                    self.assertNotIn("pages", record)

                    detail = self._json_request(
                        base + f"/api/evidence-sources/{record['id']}?path=paper.md&include_text=1"
                    )["source"]
                    self.assertEqual([row["page"] for row in detail["pages"]], [1, 2])
                    self.assertIn("Controlled PDF evidence sentence", detail["pages"][0]["text"])

                    confirmed = self._json_request(
                        base + f"/api/evidence-sources/{record['id']}/confirm-full-text", "POST",
                        {"path": "paper.md", "confirmed": True, "actor": "June"},
                    )["source"]
                    self.assertTrue(confirmed["full_text_confirmed"])
                    self.assertEqual(confirmed["full_text_confirmed_by"], "June")

                    repeated = self._attach(base, "paper.md", "renamed.pdf", source)
                    self.assertTrue(repeated["reused"])
                    sources = self._json_request(base + "/api/evidence-sources?path=paper.md")["sources"]
                    self.assertEqual(len(sources), 1)
                    with urllib.request.urlopen(
                        base + "/api/export?path=paper.md&format=package", timeout=15,
                    ) as response:
                        package = response.read()
                    with zipfile.ZipFile(io.BytesIO(package)) as archive:
                        names = set(archive.namelist())
                        self.assertIn(f"evidence/{record['id']}/record.json", names)
                        self.assertIn(f"evidence/{record['id']}/pages.json", names)
                        self.assertIn(f"evidence/{record['id']}/source/context.pdf", names)
                    with open(os.path.join(tmp, "paper.md"), encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), "# Manuscript\n\nThe canonical Markdown remains separate.\n")
                finally:
                    self._stop_server(httpd, thread)

    def test_image_only_pdf_is_not_presented_as_full_text(self):
        if not server._pdf_extractor_status()["ready"]:
            self.skipTest(server._pdf_extractor_status()["detail"])
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# Manuscript\n")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd, thread, base = self._start_server()
                try:
                    record = self._attach(base, "paper.md", "scan.pdf", self._synthetic_pdf([""]))["source"]
                    self.assertEqual(record["extraction_status"], "image_only")
                    self.assertTrue(any("OCR" in warning for warning in record["warnings"]))
                    status, error = self._json_error(
                        base + f"/api/evidence-sources/{record['id']}/confirm-full-text", "POST",
                        {"path": "paper.md", "confirmed": True},
                    )
                    self.assertEqual(status, 400)
                    self.assertIn("usable extraction", error["error"])
                finally:
                    self._stop_server(httpd, thread)

    def test_evidence_enters_only_an_explicitly_selected_conversation(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            body = "# Results\n\nThis selected claim needs context.\n"
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write(body)
            extracted = {
                "pages": [
                    {"page": 1, "text": "Evidence page one. " * 140},
                    {"page": 2, "text": "Evidence page two with the comparator cohort. " * 90},
                ],
                "metadata": {"title": "Synthetic evidence"},
                "warnings": [],
                "versions": {"pdfjs_dist": "fixture"},
            }
            captured_prompts = []

            def fake_ai(_tool, prompt, **_kwargs):
                captured_prompts.append(prompt)
                if "summarizing an explicitly authorized PDF EvidenceSource" in prompt:
                    return {
                        "tool": "codex",
                        "output": json.dumps({
                            "summary_3_6": ["结论一 [p.1]", "结论二 [p.2]", "仍需核查完整性。"],
                        }, ensure_ascii=False),
                        "returncode": 0, "elapsed_ms": 1,
                    }
                if "rigorous scientific manuscript reviewer" in prompt:
                    return {
                        "tool": "codex",
                        "output": json.dumps({
                            "summary": "无新增问题", "assistant_text": "已读取显式资料。", "findings": [],
                        }, ensure_ascii=False),
                        "returncode": 0, "elapsed_ms": 1,
                    }
                return {"tool": "codex", "output": "仅基于显式提供的 PDF 上下文回答。", "returncode": 0, "elapsed_ms": 1}

            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")), \
                    mock.patch.object(server, "CONVERSATION_ROOT", os.path.join(tmp, "conversations")), \
                    mock.patch.object(server, "REVIEW_ROOT", os.path.join(tmp, "review-sessions")), \
                    mock.patch.object(server, "_extract_pdf_pages", return_value=extracted), \
                    mock.patch.object(server, "_invoke_ai", side_effect=fake_ai):
                evidence, _ = server._create_pdf_evidence_source(
                    os.path.join(tmp, "paper.md"), "context.pdf", b"%PDF-1.4\nfixture", "application/pdf",
                )
                httpd, thread, base = self._start_server()
                try:
                    document = self._json_request(base + "/api/doc?path=paper.md")
                    started = self._json_request(base + "/api/conversations", "POST", {
                        "path": "paper.md", "base_rev": document["rev"], "tool": "codex",
                        "source_quote": {
                            "quote_text": "This selected claim needs context.",
                            "source_locator": {"text_index": body.index("This selected")},
                        },
                        "message": "这份证据能支持什么？",
                        "evidence_source_ids": [evidence["id"]],
                    })
                    self.assertEqual(started["session"]["evidence_sources"][0]["id"], evidence["id"])
                    self.assertIn(f'<AUTHORIZED_EVIDENCE id="{evidence["id"]}"', captured_prompts[0])
                    self.assertIn("[PDF page 2]", captured_prompts[0])
                    self.assertIn("comparator cohort", captured_prompts[0])

                    preflight = self._json_request(base + "/api/review-preflight?path=paper.md")["preflight"]
                    review = self._json_request(base + "/api/review-runs", "POST", {
                        "path": "paper.md",
                        "base_rev": preflight["document"]["current_rev"],
                        "comments_rev": preflight["comments"]["comments_rev"],
                        "baseline_session_id": "",
                        "mode": "initial", "tool": "codex",
                        "evidence_source_ids": [evidence["id"]],
                    })
                    self.assertEqual(review["session"]["evidence_sources"][0]["id"], evidence["id"])
                    self.assertIn(f'<AUTHORIZED_EVIDENCE id="{evidence["id"]}"', captured_prompts[1])
                    self.assertIn("[PDF page 2]", captured_prompts[1])

                    status, error = self._json_error(
                        base + f"/api/evidence-sources/{evidence['id']}/summary", "POST",
                        {"path": "paper.md", "tool": "codex", "confirmed_data_transfer": False},
                    )
                    self.assertEqual(status, 400)
                    self.assertIn("explicit confirmation", error["error"])
                    summarized = self._json_request(
                        base + f"/api/evidence-sources/{evidence['id']}/summary", "POST",
                        {"path": "paper.md", "tool": "codex", "confirmed_data_transfer": True},
                    )
                    self.assertEqual(len(summarized["summary"]["summary_3_6"]), 3)
                    self.assertEqual(summarized["source"]["summaries"][0]["tool"], "codex")
                    self.assertIn("[PDF page 2]", captured_prompts[2])
                finally:
                    self._stop_server(httpd, thread)

    def test_evidence_summary_codex_schema_uses_file_path_from_http_entrypoint(self):
        with tempfile.TemporaryDirectory() as raw_tmp, tempfile.TemporaryDirectory() as raw_bin:
            tmp = os.path.realpath(raw_tmp)
            fake_codex = _write_executable(os.path.join(raw_bin, "codex"), f"""#!{sys.executable}
import json
import os
import sys
if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
if sys.argv[1:3] == ["login", "status"]:
    raise SystemExit(0)
schema = sys.argv[sys.argv.index("--output-schema") + 1]
if schema.lstrip().startswith("{{") or not os.path.isfile(schema):
    print(f"Failed to read output schema file {{schema}}: No such file or directory (os error 2)", file=sys.stderr)
    raise SystemExit(1)
with open(schema, encoding="utf-8") as handle:
    loaded = json.load(handle)
if "summary_3_6" not in loaded.get("properties", {{}}):
    raise SystemExit(3)
out = sys.argv[sys.argv.index("--output-last-message") + 1]
open(out, "w", encoding="utf-8").write(json.dumps({{
    "summary_3_6": ["证据摘要一 [p.1]", "证据摘要二 [p.1]", "证据摘要三 [p.1]"]
}}, ensure_ascii=False))
print(json.dumps({{"type": "thread.started", "thread_id": "thread-schema-file"}}))
""")
            with open(os.path.join(tmp, "paper.md"), "w", encoding="utf-8") as fh:
                fh.write("# Manuscript\n\nThe canonical Markdown remains separate.\n")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")), \
                    mock.patch.dict(os.environ, {"COMMA_REVIEW_CODEX_BIN": fake_codex}, clear=False):
                doc = os.path.join(tmp, "paper.md")
                evidence_id = "evidence-1234567890abcdef"
                root = server._evidence_root(doc, evidence_id)
                os.makedirs(root, exist_ok=True)
                server._atomic_write_json(os.path.join(root, "pages.json"), [
                    {"page": 1, "text": "Controlled extracted PDF evidence. " * 90},
                ])
                source_bytes = b"%PDF-1.4\nsynthetic local pdf\n"
                server._atomic_write_bytes(os.path.join(root, "source.pdf"), source_bytes)
                server._atomic_write_json(server._evidence_record_path(doc, evidence_id), {
                    "schema_version": "comma-review-evidence-source/v1",
                    "id": evidence_id,
                    "doc_path": "paper.md",
                    "attached_rev": server._rev("# Manuscript\n\nThe canonical Markdown remains separate.\n"),
                    "kind": "pdf",
                    "state": "active",
                    "access_level": "uploaded_pdf",
                    "extraction_status": "usable",
                    "full_text_confirmed": True,
                    "source": {
                        "filename": "context.pdf",
                        "media_type": "application/pdf",
                        "byte_count": len(source_bytes),
                        "sha256": server._sha256_bytes(source_bytes),
                        "archive_path": os.path.relpath(os.path.join(root, "source.pdf"), tmp),
                    },
                    "extractor": {"id": "fixture", "version": "1", "components": {}},
                    "metadata": {},
                    "metrics": {
                        "page_count": 1,
                        "total_non_whitespace_chars": 2700,
                        "text_usable_pages": 1,
                        "text_usable_ratio": 1.0,
                        "page_metrics": [{"page": 1, "non_whitespace_chars": 2700, "text_usable": True}],
                    },
                    "warnings": [],
                    "created_at": "2026-07-21T10:00:00",
                    "updated_at": "2026-07-21T10:00:00",
                    "record_version": 1,
                })
                httpd, thread, base = self._start_server()
                try:
                    summarized = self._json_request(
                        base + f"/api/evidence-sources/{evidence_id}/summary", "POST",
                        {"path": "paper.md", "tool": "codex", "confirmed_data_transfer": True},
                    )
                    self.assertEqual(len(summarized["summary"]["summary_3_6"]), 3)
                    trace_root = os.path.join(tmp, ".comma-review", "executor-traces")
                    schema_files = []
                    for dirpath, _dirnames, filenames in os.walk(trace_root):
                        schema_files.extend(
                            os.path.join(dirpath, name)
                            for name in filenames if name == "output_schema.json"
                        )
                    self.assertEqual(len(schema_files), 1)
                finally:
                    self._stop_server(httpd, thread)

    def test_frontend_keeps_pdf_evidence_separate_and_opt_in(self):
        with open(os.path.join(server.STATIC_ROOT, "editor.html"), encoding="utf-8") as fh:
            html = fh.read()
        with open(os.path.join(server.STATIC_ROOT, "app.js"), encoding="utf-8") as fh:
            script = fh.read()
        self.assertIn("id: 'evidence'", script)
        self.assertIn("button.id = 'btn-evidence'", script)
        self.assertIn('id="evidence-drawer"', html)
        self.assertIn('id="conversation-evidence-open"', html)
        self.assertIn("/api/evidence-sources?${params}", script)
        self.assertIn("evidence_source_ids: [...evidenceState.selectedIds]", script)
        self.assertIn("只会用于下一次新建的讨论或评审", script)
        self.assertIn("confirmed_data_transfer: true", script)
        self.assertIn("不会发送：原始 PDF 二进制", script)

    @staticmethod
    def _synthetic_pdf(page_texts):
        page_count = len(page_texts)
        font_id = 3 + page_count * 2
        objects = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: ("<< /Type /Pages /Kids [" + " ".join(
                f"{3 + index * 2} 0 R" for index in range(page_count)
            ) + f"] /Count {page_count} >>").encode("ascii"),
            font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        }
        for index, text in enumerate(page_texts):
            page_id = 3 + index * 2
            content_id = page_id + 1
            chunks = [str(text)[start:start + 80] for start in range(0, len(str(text)), 80)] or [""]
            escaped = [chunk.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for chunk in chunks]
            commands = " T* ".join(f"({chunk}) Tj" for chunk in escaped)
            stream = f"BT /F1 10 Tf 12 TL 50 750 Td {commands} ET".encode("latin-1")
            objects[page_id] = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
            objects[content_id] = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (font_id + 1)
        for object_id in range(1, font_id + 1):
            offsets[object_id] = len(payload)
            payload.extend(f"{object_id} 0 obj\n".encode("ascii"))
            payload.extend(objects[object_id])
            payload.extend(b"\nendobj\n")
        xref = len(payload)
        payload.extend(f"xref\n0 {font_id + 1}\n".encode("ascii"))
        payload.extend(b"0000000000 65535 f \n")
        for object_id in range(1, font_id + 1):
            payload.extend(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))
        payload.extend(
            f"trailer\n<< /Size {font_id + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return bytes(payload)

    @staticmethod
    def _start_server():
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, thread, f"http://127.0.0.1:{httpd.server_address[1]}"

    @staticmethod
    def _stop_server(httpd, thread):
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)

    @staticmethod
    def _attach(base, doc, filename, content):
        params = urllib.parse.urlencode({"path": doc, "filename": filename})
        request = urllib.request.Request(
            f"{base}/api/evidence-sources?{params}", data=content, method="POST",
            headers={"Content-Type": "application/pdf"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _json_request(url, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _json_error(url, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()
        raise AssertionError("request unexpectedly succeeded")


if __name__ == "__main__":
    unittest.main()
