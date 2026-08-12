#!/usr/bin/env python3
"""HTTP contracts for staged, no-overwrite manuscript imports."""
import json
import io
import base64
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from unittest import mock

import server


class ReviewImportTests(unittest.TestCase):
    def test_markdown_import_is_staged_audited_and_idempotently_committed(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            events = os.path.join(tmp, "events.jsonl")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", events):
                httpd, thread, base = self._start_server()
                try:
                    source = b"\xef\xbb\xbf# Synthetic manuscript\r\n\r\nA controlled claim.\r\n"
                    staged = self._stage(base, "study draft.md", source)
                    record = staged["import"]
                    import_id = record["id"]
                    self.assertEqual(record["status"], "staged")
                    self.assertEqual(record["candidate"]["suggested_target"], "study-draft.md")
                    self.assertIn("normalized line endings to LF", record["normalizations"])
                    self.assertFalse(os.path.exists(os.path.join(tmp, "study-draft.md")))

                    source_path = os.path.join(tmp, record["source"]["archive_path"])
                    with open(source_path, "rb") as fh:
                        self.assertEqual(fh.read(), source)
                    self.assertEqual(os.stat(source_path).st_mode & 0o222, 0)

                    committed = self._json_request(
                        base + f"/api/imports/{import_id}/commit", "POST",
                        {"target_name": "study-draft.md", "actor": "June"},
                    )
                    self.assertFalse(committed["reused"])
                    self.assertEqual(committed["import"]["status"], "committed")
                    self.assertEqual(committed["import"]["target"]["path"], "study-draft.md")
                    with open(os.path.join(tmp, "study-draft.md"), encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), "# Synthetic manuscript\n\nA controlled claim.\n")

                    history = self._json_request(base + "/api/versions?path=study-draft.md")
                    self.assertEqual(history["versions"][0]["kind"], "import")
                    fetched = self._json_request(base + f"/api/imports/{import_id}")
                    self.assertEqual(fetched["import"]["target"]["rev"], committed["import"]["target"]["rev"])

                    repeated = self._json_request(
                        base + f"/api/imports/{import_id}/commit", "POST",
                        {"target_name": "study-draft.md", "actor": "June"},
                    )
                    self.assertTrue(repeated["reused"])
                    with open(events, encoding="utf-8") as fh:
                        rows = [json.loads(line) for line in fh if line.strip()]
                    self.assertEqual([row["action"] for row in rows], ["import-manuscript"])
                    with urllib.request.urlopen(
                        base + "/api/export?path=study-draft.md&format=package", timeout=15,
                    ) as response:
                        package = response.read()
                    with zipfile.ZipFile(io.BytesIO(package)) as archive:
                        names = set(archive.namelist())
                        self.assertIn(f"provenance/imports/{import_id}/receipt.json", names)
                        self.assertIn(
                            f"provenance/imports/{import_id}/original/study-draft.md", names,
                        )
                finally:
                    self._stop_server(httpd, thread)

    def test_import_never_overwrites_and_detects_staged_candidate_drift(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with open(os.path.join(tmp, "occupied.md"), "w", encoding="utf-8") as fh:
                fh.write("# Existing\n")
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd, thread, base = self._start_server()
                try:
                    first = self._stage(base, "incoming.md", b"# Incoming\n")["import"]
                    status, error = self._json_error(
                        base + f"/api/imports/{first['id']}/commit", "POST",
                        {"target_name": "occupied.md"},
                    )
                    self.assertEqual(status, 409)
                    self.assertEqual(error["code"], "import_target_exists")
                    with open(os.path.join(tmp, "occupied.md"), encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), "# Existing\n")

                    second = self._stage(base, "drift.md", b"# Original\n")["import"]
                    candidate = server._import_candidate_path(second["id"])
                    with open(candidate, "w", encoding="utf-8") as fh:
                        fh.write("# Tampered\n")
                    status, error = self._json_error(
                        base + f"/api/imports/{second['id']}/commit", "POST",
                        {"target_name": "fresh.md"},
                    )
                    self.assertEqual(status, 409)
                    self.assertEqual(error["code"], "import_candidate_drift")
                    self.assertFalse(os.path.exists(os.path.join(tmp, "fresh.md")))
                finally:
                    self._stop_server(httpd, thread)

    def test_markdown_import_rejects_paths_invalid_utf8_and_unsupported_types(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd, thread, base = self._start_server()
                try:
                    for filename, content in (
                        ("../escape.md", b"# no\n"),
                        ("paper.txt", b"# no\n"),
                        ("bad.md", b"\xff\xfe"),
                    ):
                        status, _ = self._stage_error(base, filename, content)
                        self.assertEqual(status, 400)
                    self.assertEqual(
                        [name for name in os.listdir(tmp) if name.endswith(".md")], [],
                    )
                    capabilities = self._json_request(base + "/api/imports/capabilities")
                    accepted = {row["extension"]: row for row in capabilities["manuscript"]["accepted"]}
                    self.assertTrue(accepted[".md"]["ready"])
                    self.assertEqual(accepted[".docx"]["ready"], server._docx_converter_status()["ready"])

                    staged = self._stage(
                        base, "discard-me.md", b"# Private draft\n\n![Figure](figures/private.png)\n",
                    )["import"]
                    self.assertEqual(staged["candidate"]["missing_assets"], ["figures/private.png"])
                    self.assertIn("were not imported", staged["warnings"][0])
                    import_root = server._import_root(staged["id"])
                    self.assertTrue(os.path.isdir(import_root))
                    discarded = self._json_request(base + f"/api/imports/{staged['id']}", "DELETE")
                    self.assertEqual(discarded["discarded"], staged["id"])
                    self.assertFalse(os.path.exists(import_root))
                finally:
                    self._stop_server(httpd, thread)

    def test_frontend_exposes_staged_import_confirmation(self):
        with open(os.path.join(server.STATIC_ROOT, "editor.html"), encoding="utf-8") as fh:
            html = fh.read()
        with open(os.path.join(server.STATIC_ROOT, "app.js"), encoding="utf-8") as fh:
            script = fh.read()
        self.assertIn("id: 'import-manuscript'", script)
        self.assertIn("button.id = 'btn-import'", script)
        self.assertIn('id="import-modal"', html)
        self.assertIn('id="import-commit"', html)
        self.assertIn("/api/imports?${params}", script)
        self.assertIn("commitStagedImport", script)
        self.assertIn("discardStagedImport", script)

    def test_docx_safety_probe_blocks_editorial_decisions_and_external_resources(self):
        clean = self._synthetic_docx()
        report = server._inspect_docx(clean)
        self.assertFalse(report["tracked_changes"])
        self.assertFalse(report["comments"])

        with self.assertRaisesRegex(ValueError, "tracked changes"):
            server._inspect_docx(self._synthetic_docx(tracked=True))
        with self.assertRaisesRegex(ValueError, "Word comments"):
            server._inspect_docx(self._synthetic_docx(comments=True))
        with self.assertRaisesRegex(ValueError, "non-hyperlink external relationship"):
            server._inspect_docx(self._synthetic_docx(external_image=True))
        with self.assertRaisesRegex(ValueError, "unsafe ZIP path"):
            server._inspect_docx(self._synthetic_docx(zip_slip=True))
        with self.assertRaisesRegex(ValueError, "DTD or entities"):
            server._inspect_docx(self._synthetic_docx(xxe=True))
        with self.assertRaisesRegex(ValueError, "macros"):
            server._inspect_docx(self._synthetic_docx(macro=True))
        with self.assertRaisesRegex(ValueError, "compression ratio"):
            server._inspect_docx(self._synthetic_docx(zip_bomb=True))

    def test_docx_converter_status_supports_windows_without_macos_sandbox(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            node = os.path.join(tmp, "node.exe")
            with open(node, "w", encoding="utf-8") as handle:
                handle.write("fake node")
            for package in ("mammoth", "sanitize-html", "turndown", "turndown-plugin-gfm"):
                package_dir = os.path.join(tmp, "node_modules", *package.split("/"))
                os.makedirs(package_dir)
                with open(os.path.join(package_dir, "package.json"), "w", encoding="utf-8") as handle:
                    handle.write("{}")
            real_isfile = os.path.isfile

            def isfile_without_sandbox(path):
                if path == "/usr/bin/sandbox-exec":
                    return False
                return real_isfile(path)

            with mock.patch.object(server.sys, "platform", "win32"), \
                    mock.patch.object(server.os.path, "isfile", side_effect=isfile_without_sandbox), \
                    mock.patch.object(server, "_project_root", return_value=tmp), \
                    mock.patch.dict(os.environ, {"COMMA_REVIEW_NODE_BIN": node}, clear=False):
                status = server._docx_converter_status()
            self.assertTrue(status["ready"])
            self.assertEqual(status["sandbox"], "")
            self.assertEqual(status["isolation"], "windows-local-pinned-converter")

    def test_docx_windows_converter_runs_without_sandbox_command(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            source = os.path.join(tmp, "source.docx")
            with open(source, "wb") as handle:
                handle.write(b"fake")
            command_rows = []

            def fake_run(command, **_kwargs):
                command_rows.append(command)
                output_root = command[-2]
                os.makedirs(output_root, exist_ok=True)
                with open(os.path.join(output_root, "result.json"), "w", encoding="utf-8") as handle:
                    json.dump({
                        "markdown": "# Converted\n",
                        "assets": [],
                        "messages": [],
                        "versions": {"mammoth": "fake"},
                    }, handle)
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(server, "_docx_converter_status", return_value={
                "ready": True,
                "node": r"C:\Tools\node.exe",
                "sandbox": "",
                "script": r"C:\Repo\apps\review-studio\importers\docx_to_markdown.mjs",
                "isolation": "windows-local-pinned-converter",
                "detail": "ready",
            }), mock.patch.object(server.subprocess, "run", side_effect=fake_run):
                converted = server._convert_docx_candidate(source, "import-aaaaaaaaaaaaaaaa")
            self.assertEqual(command_rows[0][0], r"C:\Tools\node.exe")
            self.assertNotIn("-f", command_rows[0])
            self.assertEqual(converted["isolation"], "windows-local-pinned-converter")
            self.assertEqual(converted["markdown"], "# Converted\n")

    def test_docx_converts_in_no_network_sandbox_and_commits_assets_contract(self):
        if not server._docx_converter_status()["ready"]:
            self.skipTest(server._docx_converter_status()["detail"])
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd, thread, base = self._start_server()
                try:
                    staged = self._stage(base, "synthetic-study.docx", self._synthetic_docx(include_image=True))["import"]
                    self.assertEqual(staged["status"], "staged")
                    self.assertEqual(staged["converter"]["id"], "mammoth-sanitize-turndown-gfm")
                    self.assertEqual(staged["candidate"]["suggested_target"], "synthetic-study.md")
                    self.assertIn("# Synthetic Article", staged["preview"])
                    self.assertIn("*qualified*", staged["preview"])
                    self.assertIn("[evidence link](https://example.org/evidence)", staged["preview"])
                    self.assertRegex(staged["preview"], r"-\s+First review item")
                    self.assertIn("| Endpoint | Value |", staged["preview"])
                    self.assertIn("*Figure 1. Synthetic control image.*", staged["preview"])
                    self.assertEqual(len(staged["candidate"]["assets"]), 1)
                    self.assertIn(f"assets/{staged['id']}/figure-", staged["preview"])

                    committed = self._json_request(
                        base + f"/api/imports/{staged['id']}/commit", "POST",
                        {"target_name": "synthetic-study.md", "actor": "June"},
                    )["import"]
                    with open(os.path.join(tmp, "synthetic-study.md"), encoding="utf-8") as fh:
                        body = fh.read()
                    self.assertIn("# Synthetic Article", body)
                    self.assertIn("**controlled**", body)
                    self.assertRegex(body, r"-\s+First review item")
                    self.assertEqual(committed["target"]["asset_root"], f"assets/{staged['id']}")
                    asset = staged["candidate"]["assets"][0]
                    self.assertTrue(os.path.isfile(os.path.join(tmp, "assets", staged["id"], asset["name"])))
                    with urllib.request.urlopen(
                        base + "/api/asset?doc=synthetic-study.md&source=" +
                        urllib.parse.quote(f"assets/{staged['id']}/{asset['name']}", safe=""),
                        timeout=10,
                    ) as response:
                        self.assertEqual(response.headers.get_content_type(), "image/png")
                finally:
                    self._stop_server(httpd, thread)

    def test_docx_tiff_image_is_converted_or_placeholdered_without_rejecting_manuscript(self):
        if not server._docx_converter_status()["ready"]:
            self.skipTest(server._docx_converter_status()["detail"])
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = os.path.realpath(raw_tmp)
            with mock.patch.object(server, "DATA_ROOT", tmp), \
                    mock.patch.object(server, "EVENTS_PATH", os.path.join(tmp, "events.jsonl")):
                httpd, thread, base = self._start_server()
                try:
                    staged = self._stage(
                        base, "tiff-study.docx",
                        self._synthetic_docx(include_image=True, image_extension="tiff"),
                    )["import"]
                    self.assertEqual(staged["status"], "staged")
                    conversions = staged["candidate"]["asset_conversions"]
                    self.assertEqual(conversions[0]["source_media_type"], "image/tiff")
                    expected_status = "converted" if server._sips_path() else "placeholder"
                    self.assertEqual(conversions[0]["status"], expected_status)
                    if expected_status == "converted":
                        self.assertEqual(staged["candidate"]["assets"][0]["media_type"], "image/png")
                        self.assertIn(".png", staged["preview"])
                    else:
                        self.assertIn("Image omitted", staged["preview"])

                    fallback = self._stage(
                        base, "broken-tiff.docx",
                        self._synthetic_docx(
                            include_image=True, image_extension="tiff", image_bytes=b"not a real tiff"),
                    )["import"]
                    self.assertEqual(fallback["status"], "staged")
                    self.assertEqual(
                        fallback["candidate"]["asset_conversions"][0]["status"], "placeholder")
                    self.assertIn("Image omitted", fallback["preview"])
                    self.assertIn("replaced DOCX TIFF image", " ".join(fallback["warnings"]))
                finally:
                    self._stop_server(httpd, thread)

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
    def _synthetic_tiff_bytes():
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        sips = server._sips_path()
        if not sips:
            return b"tiff conversion unavailable"
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.png")
            target = os.path.join(tmp, "target.tiff")
            with open(source, "wb") as handle:
                handle.write(png)
            completed = subprocess.run(
                [sips, "-s", "format", "tiff", source, "--out", target],
                capture_output=True, text=True, timeout=30, check=False,
                stdin=subprocess.DEVNULL,
            )
            if completed.returncode != 0:
                return b"tiff conversion failed"
            with open(target, "rb") as handle:
                return handle.read()

    @staticmethod
    def _stage(base, filename, content):
        quoted = urllib.parse.quote(filename, safe="")
        request = urllib.request.Request(
            f"{base}/api/imports?kind=manuscript&filename={quoted}",
            data=content, method="POST", headers={"Content-Type": "text/markdown"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _synthetic_docx(*, tracked=False, external_image=False, zip_slip=False, include_image=False,
                        comments=False, xxe=False, macro=False, zip_bomb=False,
                        image_extension="png", image_bytes=None):
        image_media_type = "image/tiff" if image_extension == "tiff" else "image/png"
        image_payload = image_bytes
        if image_payload is None and image_extension == "tiff":
            image_payload = ReviewImportTests._synthetic_tiff_bytes()
        elif image_payload is None:
            image_payload = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
        content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  %s
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
  %s
</Types>''' % (
            f'<Default Extension="{image_extension}" ContentType="{image_media_type}"/>' if include_image else '',
            '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>' if comments else '',
        )
        if macro:
            content_types = content_types.replace(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
                "application/vnd.ms-word.document.macroEnabled.main+xml",
            )
        package_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
        document_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
  <Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.org/evidence" TargetMode="External"/>
  %s
  %s
</Relationships>''' % (
            '<Relationship Id="rIdRemote" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.invalid/private.png" TargetMode="External"/>'
            if external_image else '',
            f'<Relationship Id="rIdImage1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/figure.{image_extension}"/>'
            if include_image else '',
        )
        styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:qFormat/></w:style>
  <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/><w:basedOn w:val="Normal"/></w:style>
</w:styles>'''
        numbering = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl></w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>'''
        claim = (
            '<w:ins w:id="1" w:author="Synthetic"><w:r><w:t>controlled</w:t></w:r></w:ins>'
            if tracked else '<w:r><w:rPr><w:b/></w:rPr><w:t>controlled</w:t></w:r>'
        )
        drawing = '''
    <w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
      <wp:extent cx="914400" cy="914400"/><wp:docPr id="1" name="Synthetic Figure"/>
      <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
          <pic:nvPicPr><pic:cNvPr id="0" name="figure.%s"/><pic:cNvPicPr/></pic:nvPicPr>
          <pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rIdImage1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
          <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
        </pic:pic>
      </a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>''' % image_extension if include_image else ''
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Synthetic Article</w:t></w:r></w:p>
    <w:p><w:r><w:t xml:space="preserve">A </w:t></w:r>{claim}<w:r><w:t xml:space="preserve"> and </w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>qualified</w:t></w:r><w:r><w:t xml:space="preserve"> claim with an </w:t></w:r><w:hyperlink r:id="rIdLink"><w:r><w:t>evidence link</w:t></w:r></w:hyperlink><w:r><w:t>.</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>First review item</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Endpoint</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>Response</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>42%</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    {drawing}
    <w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r><w:t>Figure 1. Synthetic control image.</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>'''
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", package_rels)
            archive.writestr("word/document.xml", document)
            archive.writestr("word/styles.xml", styles)
            archive.writestr("word/numbering.xml", numbering)
            archive.writestr("word/_rels/document.xml.rels", document_rels)
            if include_image:
                archive.writestr(
                    f"word/media/figure.{image_extension}",
                    image_payload,
                )
            if zip_slip:
                archive.writestr("../escape.txt", "blocked")
            if comments:
                archive.writestr(
                    "word/comments.xml",
                    '<?xml version="1.0"?><w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="0"><w:p><w:r><w:t>Editorial note</w:t></w:r></w:p></w:comment></w:comments>',
                )
            if xxe:
                archive.writestr(
                    "word/settings.xml",
                    '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
                )
            if macro:
                archive.writestr("word/vbaProject.bin", b"synthetic macro probe")
            if zip_bomb:
                archive.writestr("word/media/compression-probe.bin", b"A" * (2 * 1024 * 1024))
        return buffer.getvalue()

    @staticmethod
    def _stage_error(base, filename, content):
        quoted = urllib.parse.quote(filename, safe="")
        request = urllib.request.Request(
            f"{base}/api/imports?kind=manuscript&filename={quoted}",
            data=content, method="POST", headers={"Content-Type": "text/markdown"},
        )
        try:
            urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()
        raise AssertionError("request unexpectedly succeeded")

    @staticmethod
    def _json_request(url, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _json_error(url, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()
        raise AssertionError("request unexpectedly succeeded")


if __name__ == "__main__":
    unittest.main()
