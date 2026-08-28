from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sih_ref.core import PUBLIC_ITEM_FIELDS, classify_daily_health, normalize_date, normalize_item, public_item  # noqa: E402
from sih_ref.delivery import publish_webhook  # noqa: E402
from sih_ref.pipeline import run_pipeline  # noqa: E402
from sih_ref.render import render_site  # noqa: E402
from sih_ref.sources import NETWORK_SOURCE_KINDS, collect_source  # noqa: E402


def tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(str(file_path.relative_to(path)).encode())
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


class ReferencePipelineTests(unittest.TestCase):
    def run_demo(self, output: Path) -> dict:
        return run_pipeline(
            config_path=ROOT / "config" / "sources.demo.json",
            profile_path=ROOT / "config" / "profile.example.json",
            output_dir=output,
            as_of=date(2026, 1, 15),
            stateless=True,
            deterministic=True,
        )

    def test_offline_demo_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            result = self.run_demo(Path(first))
            self.run_demo(Path(second))
            self.assertEqual("complete", result["daily_status"])
            self.assertEqual(tree_digest(Path(first)), tree_digest(Path(second)))

    def test_public_items_use_positive_allowlist(self) -> None:
        raw = {
            "title": "A synthetic organoid benchmark",
            "url": "https://example.org/item",
            "published_at": "2026-01-15",
            "private_note": "must never pass through",
        }
        normalized = normalize_item(raw, {"id": "fixture", "kind": "fixture_jsonl"})
        projected = public_item({**normalized, "private_note": "still private"})
        self.assertEqual(set(PUBLIC_ITEM_FIELDS), set(projected))
        self.assertNotIn("private_note", projected)

    def test_demo_output_contains_no_private_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.run_demo(Path(temp))
            for line in (Path(temp) / "daily_items.jsonl").read_text(encoding="utf-8").splitlines():
                self.assertEqual(set(PUBLIC_ITEM_FIELDS), set(json.loads(line)))

    def test_network_sources_cannot_run_without_live_flag(self) -> None:
        with patch("sih_ref.sources._request", side_effect=AssertionError("network called")):
            for kind in NETWORK_SOURCE_KINDS:
                result = collect_source(
                    {"id": f"test-{kind}", "kind": kind, "enabled": True},
                    base_dir=ROOT,
                    live=False,
                    as_of=date(2026, 1, 15),
                )
                self.assertEqual("inactive", result.status)

    def test_required_live_source_without_live_flag_is_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            config = ROOT / "config" / "sources.live-smoke.json"
            result = run_pipeline(
                config_path=config,
                profile_path=ROOT / "config" / "profile.example.json",
                output_dir=temp_path,
                as_of=date(2026, 1, 15),
                live=False,
                stateless=True,
                deterministic=True,
            )
            self.assertEqual("degraded", result["daily_status"])

    def test_example_config_represents_every_capability_family(self) -> None:
        payload = json.loads((ROOT / "config" / "sources.example.json").read_text(encoding="utf-8"))
        kinds = {source["kind"] for source in payload["sources"]}
        expected = {
            "pubmed", "pubmed_journals", "arxiv", "rss", "hacker_news",
            "openalex_author", "email_directory", "imap", "feishu_export",
            "stork_inbox", "browser_snapshot", "legacy_jsonl",
        }
        self.assertTrue(expected.issubset(kinds))
        self.assertIn("llm", payload)
        self.assertIn("delivery", payload)

    def test_health_distinguishes_warning_degraded_and_failure(self) -> None:
        self.assertEqual("complete_with_warning", classify_daily_health([{"required": False, "status": "warning"}]))
        self.assertEqual(
            "degraded",
            classify_daily_health([{"required": True, "status": "ok"}, {"required": True, "status": "failed"}]),
        )
        self.assertEqual("failed", classify_daily_health([{"required": True, "status": "failed"}]))
        self.assertEqual(
            "complete_with_warning",
            classify_daily_health([{"required": True, "status": "ok"}, {"required": False, "status": "failed"}]),
        )
        self.assertEqual("failed", classify_daily_health([{"required": False, "status": "failed"}]))

    def test_rfc_feed_date_is_normalized(self) -> None:
        self.assertEqual("2026-01-15", normalize_date("Thu, 15 Jan 2026 08:30:00 +0000"))

    def test_webhook_needs_config_flag_and_https_environment(self) -> None:
        with patch("sih_ref.delivery.urlopen", side_effect=AssertionError("network called")):
            self.assertEqual("disabled", publish_webhook({}, {"enabled": False}, publish=True)["status"])
            self.assertEqual(
                "dry_run",
                publish_webhook({}, {"enabled": True, "endpoint_env": "SIH_TEST_ENDPOINT"}, publish=False)["status"],
            )
            with self.assertRaisesRegex(ValueError, "HTTPS endpoint"):
                publish_webhook({}, {"enabled": True, "endpoint_env": "SIH_TEST_ENDPOINT"}, publish=True)

    def test_llm_needs_config_and_cli_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch(
            "sih_ref.pipeline.llm_triage", side_effect=AssertionError("LLM called")
        ):
            result = run_pipeline(
                config_path=ROOT / "config" / "sources.demo.json",
                profile_path=ROOT / "config" / "profile.example.json",
                output_dir=Path(temp),
                as_of=date(2026, 1, 15),
                llm_enabled=True,
                stateless=True,
                deterministic=True,
            )
            health = json.loads((Path(temp) / "source_health.json").read_text(encoding="utf-8"))
            self.assertEqual("inactive", health["extensions"]["llm_triage"]["status"])
            self.assertEqual("complete", result["daily_status"])

    def test_html_projection_escapes_script_termination(self) -> None:
        malicious = "</script><script>alert('x')</script>"
        html = render_site(
            [{
                "item_id": "url:https://example.org/x",
                "title": malicious,
                "url": "https://example.org/x",
                "summary": malicious,
                "source_id": "fixture",
                "published_at": "2026-01-15",
                "tags": [],
                "reading_tier": "skim",
                "freshness_gate": "fresh",
                "topic_relevance": 0.5,
            }],
            {"daily_status": "complete", "source_count": 1, "loaded_source_count": 1},
            as_of="2026-01-15",
            synthetic_demo=True,
        )
        self.assertNotIn(malicious, html)
        self.assertIn("<\\/script>", html)

    def tearDown(self) -> None:
        shutil.rmtree(ROOT / "demo" / "output", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
