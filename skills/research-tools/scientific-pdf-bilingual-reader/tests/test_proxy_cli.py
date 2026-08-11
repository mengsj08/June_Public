import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from workbench import _locate_source_pages, read_translation_warnings, record_translation_refusal, run_proxy_cli


class ProxyCliTest(unittest.TestCase):
    def test_claude_is_isolated_and_prompt_goes_over_stdin(self):
        captured = {}

        def runner(cmd, **kwargs):
            captured.update(cmd=cmd, kwargs=kwargs)
            return subprocess.CompletedProcess(cmd, 0, stdout="译文\n", stderr="")

        self.assertEqual(run_proxy_cli("claude", "- X X ?", runner=runner), "译文")
        self.assertNotIn("- X X ?", captured["cmd"])
        self.assertEqual(captured["kwargs"]["input"], "- X X ?")
        for flag in ("--safe-mode", "--setting-sources", "--strict-mcp-config", "--tools", "--no-session-persistence", "--system-prompt"):
            self.assertIn(flag, captured["cmd"])

    def test_nonzero_exit_includes_stdout_even_when_stderr_is_empty(self):
        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 9, stdout="classifier refusal from stdout", stderr="")

        with self.assertRaisesRegex(RuntimeError, "classifier refusal from stdout"):
            run_proxy_cli("claude", "source", runner=runner)

    def test_policy_refusal_keeps_source_and_emits_warning_callback(self):
        source = "eAg g px A a o"
        prompt = f"Translate this.\n\nSource Text:\n{source}\n\nTranslated Text:"
        events = []

        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 1,
                stdout="API Error: Claude Code is unable to respond to this request, which appears to violate our Usage Policy.",
                stderr="",
            )

        self.assertEqual(run_proxy_cli("claude", prompt, runner=runner, on_refusal=events.append), source)
        self.assertEqual(events, [source])

    def test_authentication_failure_is_never_treated_as_refusal(self):
        prompt = "Source Text:\nsource\n\nTranslated Text:"

        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="API Error: Failed to authenticate", stderr="")

        with self.assertRaisesRegex(RuntimeError, "Failed to authenticate"):
            run_proxy_cli("claude", prompt, runner=runner, on_refusal=self.fail)

    def test_other_nonzero_exit_is_never_treated_as_refusal(self):
        prompt = "Source Text:\nsource\n\nTranslated Text:"

        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 2, stdout="unknown model", stderr="")

        with self.assertRaisesRegex(RuntimeError, "unknown model"):
            run_proxy_cli("claude", prompt, runner=runner, on_refusal=self.fail)

    def test_timeout_is_not_swallowed(self):
        def runner(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        with self.assertRaises(subprocess.TimeoutExpired):
            run_proxy_cli("claude", "Source Text:\nsource\n\nTranslated Text:", runner=runner)

    def test_refusal_source_is_located_to_pdf_page(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "translation-source.pdf"
            document = fitz.open()
            document.new_page().insert_text((72, 72), "ordinary first page")
            document.new_page().insert_text((72, 72), "eAg g px A a o 04 9 s xog qonm")
            document.save(source)
            document.close()
            pages = _locate_source_pages(
                folder, {"translation_source_file": source.name},
                "eAg g px A a o 04 9 s xog qonm eq og",
            )
            self.assertEqual(pages, [2])

    def test_refusal_warning_is_persisted_without_source_or_request_id(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            folder = data / "task123"
            folder.mkdir()
            source = folder / "translation-source.pdf"
            document = fitz.open()
            document.new_page().insert_text((72, 72), "eAg g px A a o 04 9 s xog qonm")
            document.save(source)
            document.close()
            (folder / "task.json").write_text(
                '{"id":"task123","translation_source_file":"translation-source.pdf"}'
            )
            original = "eAg g px A a o 04 9 s xog qonm"
            with patch("workbench.DATA", data):
                record_translation_refusal("task123", original)
                warnings = read_translation_warnings(folder)
            self.assertEqual(warnings[0]["pages"], [1])
            self.assertEqual(warnings[0]["code"], "translation_refusal_kept_source")
            serialized = (folder / "translation-warnings.jsonl").read_text()
            self.assertNotIn(original, serialized)
            self.assertNotIn("Request ID", serialized)


if __name__ == "__main__":
    unittest.main()
