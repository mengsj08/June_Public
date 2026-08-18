#!/usr/bin/env python3
"""Tests for the governance outbound gate."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pytest


_HERE = Path(__file__).resolve().parent
_OUTBOUND_GATE = _HERE.parent / "governance" / "outbound_gate.py"
if not _OUTBOUND_GATE.is_file():
    pytest.skip("missing optional source path: governance/outbound_gate.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("outbound_gate", _OUTBOUND_GATE)
outbound_gate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = outbound_gate
_spec.loader.exec_module(outbound_gate)


def test_clean_text_passes_and_appends_ledger(tmp_path):
    ledger = tmp_path / "OUTBOUND_LEDGER.jsonl"
    result = outbound_gate.build_check_result(
        "Public release note with no sensitive markers.",
        target="clean-public-note",
        meeting_rules=[],
    )

    outbound_gate.append_ledger(result, ledger)

    assert result["verdict"] == "pass"
    assert result["counts"] == {
        "private_path": 0,
        "credential": 0,
        "email": 0,
        "internal_host": 0,
        "meeting_identity_mix": 0,
    }
    rows = ledger.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    entry = json.loads(rows[0])
    assert entry["content_sha256"] == result["sha256"]
    assert "Public release note" not in rows[0]


def test_private_path_hits_without_echoing_path_in_human_output(tmp_path):
    result = outbound_gate.build_check_result(
        "Please inspect /Users/example/workspace/private-note.md",
        target="private-path-demo",
        meeting_rules=[],
    )
    human = outbound_gate.format_human(result)

    assert result["verdict"] == "hit"
    assert result["counts"]["private_path"] == 1
    assert result["findings"][0]["category"] == "private_path"
    assert "SoT_Owner/private-note" not in human


def test_fake_credential_hits_and_ledger_omits_content(tmp_path):
    ledger = tmp_path / "OUTBOUND_LEDGER.jsonl"
    text = "Use temporary token sk-FAKE000 only in this synthetic test."

    first = outbound_gate.build_check_result(
        text,
        target="fake-secret-demo",
        channel="unit-test",
        meeting_rules=[],
    )
    second = outbound_gate.build_check_result(text, target="fake-secret-demo", channel="unit-test", meeting_rules=[])
    outbound_gate.append_ledger(first, ledger)
    outbound_gate.append_ledger(second, ledger)

    rows = ledger.read_text(encoding="utf-8").splitlines()
    assert first["verdict"] == "hit"
    assert first["channel"] == "unit-test"
    assert first["counts"]["credential"] == 1
    assert len(rows) == 2
    assert "sk-FAKE" not in "\n".join(rows)
    first_row = json.loads(rows[0])
    assert first_row["channel"] == "unit-test"
    assert first_row["content_sha256"] == json.loads(rows[1])["content_sha256"]


def test_check_packet_uses_review_packet_channel_and_never_blocks(tmp_path):
    source = tmp_path / "packet.md"
    ledger = tmp_path / "OUTBOUND_LEDGER.jsonl"
    source.write_text("Synthetic packet contains sk-FAKE000 for gate coverage.\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(_HERE.parent / "governance" / "check_packet.py"),
            str(source),
            "--ledger",
            str(ledger),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert "VERDICT hit" in proc.stdout
    assert "CHANNEL review-packet" in proc.stdout
    row = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert row["channel"] == "review-packet"
    assert row["verdict"] == "hit"
    assert "sk-FAKE" not in json.dumps(row)


def test_meeting_identity_mix_uses_loaded_canonical_rules():
    result = outbound_gate.build_check_result(
        "Source code abc42 and Public Name are mixed in one outbound note.",
        target="meeting-rule-demo",
        meeting_rules=[{"aliases": ["abc42"], "target": "Public Name"}],
    )

    assert result["verdict"] == "hit"
    assert result["counts"]["meeting_identity_mix"] == 1
