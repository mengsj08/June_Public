#!/usr/bin/env python3
"""Tests for subagent manifest profile linting."""

import importlib.util
import subprocess
import sys
from pathlib import Path
import pytest


_HERE = Path(__file__).resolve().parent
_MANIFEST_DIR = _HERE.parent / "governance" / "subagent-manifest"
_LINTER = _MANIFEST_DIR / "manifest_lint.py"
_PROFILES = _MANIFEST_DIR / "profiles"
if not _LINTER.is_file():
    pytest.skip("missing optional source path: governance/subagent-manifest/manifest_lint.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("manifest_lint", _LINTER)
manifest_lint = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = manifest_lint
_spec.loader.exec_module(manifest_lint)


def _profile(name):
    return manifest_lint.parse_profile((_PROFILES / f"{name}.yaml").read_text(encoding="utf-8"))


def test_repository_profiles_pass_lint():
    results = [manifest_lint.lint_profile_file(path) for path in sorted(_PROFILES.glob("*.yaml"))]

    assert len(results) == 3
    assert all(result.ok for result in results), results


def test_cli_reports_profiles_pass():
    proc = subprocess.run(
        [sys.executable, str(_LINTER), str(_PROFILES)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert "PASS" in proc.stdout
    assert "codex-governance-executor.yaml" in proc.stdout
    assert "external-reviewer.yaml" in proc.stdout


def test_missing_required_field_fails(tmp_path):
    source = (_PROFILES / "codex-governance-executor.yaml").read_text(encoding="utf-8")
    broken = "\n".join(line for line in source.splitlines() if not line.startswith("reviewer_role:"))
    path = tmp_path / "missing-reviewer.yaml"
    path.write_text(broken + "\n", encoding="utf-8")

    result = manifest_lint.lint_profile_file(path)

    assert result.ok is False
    assert "missing required field: reviewer_role" in result.errors


def test_cli_rejects_missing_required_field(tmp_path):
    path = tmp_path / "missing-profile-id.yaml"
    path.write_text(
        (_PROFILES / "external-reviewer.yaml")
        .read_text(encoding="utf-8")
        .replace("profile_id: external-reviewer\n", ""),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(_LINTER), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert "missing required field: profile_id" in proc.stdout


def test_example_scope_and_gate_profiles_match_section_4():
    codex = _profile("codex-governance-executor")
    external = _profile("external-reviewer")

    assert codex["vendor_binding"] == ["codex"]
    assert codex["write_scope"]["root"].endswith("/kanban-personal")
    assert codex["sanitizer_required"] is False
    assert codex["reviewer_role"] == "claude-supervisor"
    assert codex["human_gate_trigger"] == ["delete_source", "spend", "publish"]

    assert external["allowed_input_class"] == ["artifact:sanitized-packet"]
    assert external["allowed_tools"] == []
    assert external["write_scope"] == {"root": "deny-all", "outside_root": "deny"}
    assert external["output_contract"]["backfill"] == "ai-draft"
