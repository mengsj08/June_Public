import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from workbench import (
    ACTIVE_TASKS, ACTIVE_TASKS_LOCK, PROXY_BEHAVIOR_VERSION,
    engine_fatal_marker, proxy_provider, running_task_is_stale,
    reset_translation_warnings, terminate_recorded_engine,
)
from qa_alpha import load_refusal_pages


class WorkbenchResilienceTest(unittest.TestCase):
    def tearDown(self):
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.clear()

    def test_proxy_model_version_and_legacy_format_resolve_provider(self):
        self.assertEqual(proxy_provider(f"claude+{PROXY_BEHAVIOR_VERSION}"), "claude")
        self.assertEqual(proxy_provider("claude"), "claude")

    def test_running_task_is_stale_only_when_not_active_here(self):
        task = {"id": "task1", "status": "running"}
        self.assertTrue(running_task_is_stale(task))
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.add("task1")
        self.assertFalse(running_task_is_stale(task))

    def test_authentication_failures_are_fatal_markers(self):
        self.assertEqual(engine_fatal_marker("API Error: Failed to authenticate"), "Failed to authenticate")
        self.assertEqual(engine_fatal_marker("OAuth session expired; login again"), "OAuth session expired")
        self.assertIsNone(engine_fatal_marker("ordinary retryable output"))

    def test_only_recorded_matching_pdf2zh_process_is_terminated(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "engine.pid").write_text("321")
            checked = subprocess.CompletedProcess([], 0, stdout=f"pdf2zh {folder}/translation-source.pdf", stderr="")
            with patch("workbench.subprocess.run", return_value=checked), patch(
                "workbench.os.kill", side_effect=[None, ProcessLookupError],
            ) as killed:
                self.assertTrue(terminate_recorded_engine(folder))
            killed.assert_any_call(321, 15)
            self.assertFalse((folder / "engine.pid").exists())

    def test_previous_run_refusal_warning_is_absent_from_next_run_qa(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            warning_file = folder / "translation-warnings.jsonl"
            warning_file.write_text(
                '{"code":"translation_refusal_kept_source","pages":[14]}\n',
                encoding="utf-8",
            )
            self.assertEqual(load_refusal_pages(warning_file), {14})
            reset_translation_warnings(folder)
            self.assertEqual(load_refusal_pages(warning_file), set())
            self.assertEqual(warning_file.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
