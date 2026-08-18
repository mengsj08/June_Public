#!/usr/bin/env python3
"""Tests for governance source-anchor lint."""

import importlib.util
import sys
from pathlib import Path
import pytest


_HERE = Path(__file__).resolve().parent
_ANCHOR_LINT = _HERE.parent / "governance" / "anchor_lint.py"
if not _ANCHOR_LINT.is_file():
    pytest.skip("missing optional source path: governance/anchor_lint.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("anchor_lint", _ANCHOR_LINT)
anchor_lint = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = anchor_lint
_spec.loader.exec_module(anchor_lint)


def test_classifies_four_anchor_types_and_violations():
    text = """# Demo

- Transcript path 〔owner-confirmed 2026-07-03〕 ~/.codex/sessions/2026/07/03/demo.jsonl
- Transcript line 〔owner-confirmed 2026-07-03〕 see L12..L18
- Task card 〔owner-confirmed 2026-07-03〕 implementation card GOV-90
- Decision log 〔owner-confirmed 2026-07-03〕 DECISION_LOG 2026-07-03
- Oral 〔owner-confirmed 2026-07-03〕 Owner 口述直批 2026-07-03
- Weak 〔owner-confirmed 2026-07-03〕 only a date remains
- Missing 〔owner-confirmed〕 no dated source here
"""

    results = [
        anchor_lint.classify_entry(entry)
        for entry in anchor_lint.confirmed_entries(text, "demo.md")
    ]

    assert [result["verdict"] for result in results] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "pass",
        "date_only",
        "missing_anchor",
    ]
    assert results[0]["anchor_found"] == ["transcript"]
    assert results[1]["anchor_found"] == ["transcript"]
    assert results[2]["anchor_found"] == ["task_id"]
    assert results[3]["anchor_found"] == ["decision_log"]
    assert results[4]["anchor_found"] == ["oral_confirmation"]


def test_list_entry_does_not_steal_anchor_from_next_sibling():
    text = """# Demo

- Weak 〔owner-confirmed 2026-07-03〕 only a date remains
- Sibling with DECISION_LOG 2026-07-03 but no confirmed marker
"""

    results = [
        anchor_lint.classify_entry(entry)
        for entry in anchor_lint.confirmed_entries(text, "demo.md")
    ]

    assert len(results) == 1
    assert results[0]["line"] == 3
    assert results[0]["verdict"] == "date_only"


def test_heading_entry_can_use_body_anchor_until_next_same_level_heading():
    text = """# Demo

## Rule 〔owner-confirmed 2026-07-03〕
Body cites DECISION_LOG 2026-07-03.

## Next
No confirmed marker.
"""

    results = [
        anchor_lint.classify_entry(entry)
        for entry in anchor_lint.confirmed_entries(text, "demo.md")
    ]

    assert len(results) == 1
    assert results[0]["line"] == 3
    assert results[0]["verdict"] == "pass"
    assert results[0]["anchor_found"] == ["decision_log"]


def test_human_and_json_ready_shapes(tmp_path):
    path = tmp_path / "demo.md"
    path.write_text(
        "- Rule 〔owner-confirmed 2026-07-03〕 card KAN-200\n",
        encoding="utf-8",
    )

    results = anchor_lint.scan_paths([path], repo_root=tmp_path)
    human = anchor_lint.format_human(results)

    assert results == [
        {
            "file": "demo.md",
            "line": 1,
            "excerpt": "- Rule 〔owner-confirmed 2026-07-03〕 card KAN-200",
            "verdict": "pass",
            "anchor_found": ["task_id"],
        }
    ]
    assert "demo.md:1 |" in human
    assert "SUMMARY total=1 pass=1 missing_anchor=0 date_only=0" in human
