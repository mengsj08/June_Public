#!/usr/bin/env python3
"""Tests for Documents Doctor trial/deprecated tool residue scanning."""

import importlib.util
from datetime import datetime
from pathlib import Path
import pytest


_HERE = Path(__file__).resolve().parent
_GOV = _HERE.parent / "governance" / "scan_governance.py"
if not _GOV.is_file():
    pytest.skip("missing optional source path: governance/scan_governance.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("scan_governance", _GOV)
gov = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gov)


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder\n", encoding="utf-8")


def test_trial_tool_residue_classifies_workspace_semantics(tmp_path):
    docs = tmp_path / "Documents"
    skills = tmp_path / "skills"

    _touch(docs / "Archive" / "taskspace" / "docs" / "openclaw-plan.md")
    _touch(docs / "Public" / "Owner_Public" / "skills" / "openclaw" / "README.md")
    _touch(docs / "MixedTeamSpace" / "example-org" / "team-workspace" / "shared" / "openclaw-skills" / "README.md")
    _touch(docs / "MixedTeamSpace" / "TeamDocs" / "TeamSyn" / "wiki" / "OpenClaw.md")
    _touch(docs / "ResearchLab" / "SkillLab" / "Evaluation" / "agents" / "repos" / "qclaw-eval.md")
    _touch(docs / "ActiveArea" / "qclaw-note.md")
    _touch(skills / "openclaw-official" / "README.md")

    findings = gov.scan_trial_tool_residue(str(docs), skill_root=str(skills))
    by_category = {f["category"] for f in findings}

    assert by_category == {
        "archive",
        "public_skill",
        "team_workspace",
        "teamsyn",
        "evaluation",
        "active_residue",
        "skill_entry",
    }
    assert any(f["needs_review"] for f in findings if f["category"] == "active_residue")
    assert not any(f["needs_review"] for f in findings if f["category"] == "team_workspace")


def test_declared_archived_public_skill_is_report_only(tmp_path):
    docs = tmp_path / "Documents"
    repo = docs / "Public" / "Owner_Public"
    (repo / ".git").mkdir(parents=True)
    _touch(repo / "skills" / "openclaw" / "README.md")
    (repo / "README.md").write_text(
        "# Owner Public\n\n"
        "- `skills/openclaw/` - Archived skill. Kept for historical reference only; not recommended.\n",
        encoding="utf-8",
    )

    findings = gov.scan_trial_tool_residue(str(docs), skill_root=None)

    assert len(findings) == 1
    assert findings[0]["category"] == "public_skill"
    assert findings[0]["declared_archive"] is True
    assert findings[0]["needs_review"] is False


def test_unmarked_active_skill_still_needs_review(tmp_path):
    docs = tmp_path / "Documents"
    repo = docs / "ActiveRepo"
    (repo / ".git").mkdir(parents=True)
    _touch(repo / "skills" / "qclaw" / "README.md")
    (repo / "README.md").write_text("# Active Repo\n\n- `skills/qclaw/` is still being evaluated.\n", encoding="utf-8")

    findings = gov.scan_trial_tool_residue(str(docs), skill_root=None)

    assert len(findings) == 1
    assert findings[0]["category"] == "skill_entry"
    assert findings[0]["declared_archive"] is False
    assert findings[0]["needs_review"] is True


def test_trial_tool_governance_card_is_not_residue(tmp_path):
    docs = tmp_path / "Documents"
    card = docs / "project" / "个人调度" / "OpenClaw-QClaw试验工具残留治理.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(
        "---\n"
        f"source: {gov.TRIAL_TOOL_CARD_SOURCE}\n"
        "---\n\n"
        "<!-- TRIAL-TOOL-SCAN:BEGIN -->\n"
        "<!-- TRIAL-TOOL-SCAN:END -->\n",
        encoding="utf-8",
    )

    assert gov.scan_trial_tool_residue(str(docs), skill_root=None) == []


def test_trial_tool_scan_skips_team_handoff_publish_runtime(tmp_path):
    docs = tmp_path / "Documents"
    runtime_checkout = (
        docs
        / "AI-Agent-Hub"
        / "kanban-personal"
        / "shared"
        / "toolkit"
        / "kanban"
        / ".team-handoff-publish"
        / "team-workspace"
        / "run-20260613-212410"
    )
    _touch(runtime_checkout / "members" / "Owner" / "OpenClaw_Cases" / "README.md")
    _touch(runtime_checkout / "shared" / "openclaw-skills" / "README.md")

    assert gov.scan_trial_tool_residue(str(docs), skill_root=None) == []


def test_trial_tool_report_is_path_only_and_has_source(tmp_path):
    docs = tmp_path / "Documents"
    _touch(docs / "ActiveArea" / "openclaw-note.md")

    report, flags, findings = gov.build_report(str(docs), stale_days=30, skill_root=None)

    assert "Documents Doctor: 试验工具残留" in report
    assert gov.TRIAL_TOOL_CARD_SOURCE in report
    assert "ActiveArea/openclaw-note.md" in report
    assert "试验工具残留 1 项（1 项需复核）" in flags
    assert findings[0]["category"] == "active_residue"


def test_trial_tool_report_redacts_sensitive_path_segments(tmp_path):
    docs = tmp_path / "Documents"
    _touch(docs / "MixedTeamSpace" / "example-org" / "team-workspace" / "project" / "整体的密钥" / "openclaw-prod.pem")

    report, _, findings = gov.build_report(str(docs), stale_days=30, skill_root=None)

    assert findings[0]["display_rel"].endswith("[redacted-sensitive-file]")
    assert "整体的密钥" not in report
    assert "openclaw-prod.pem" not in report
    assert "[redacted-sensitive-segment]/[redacted-sensitive-file]" in report


def test_trial_tool_card_write_is_idempotent(tmp_path):
    docs = tmp_path / "Documents"
    _touch(docs / "ActiveArea" / "openclaw-note.md")
    findings = gov.scan_trial_tool_residue(str(docs), skill_root=None)
    card = tmp_path / "project" / "个人调度" / "OpenClaw-QClaw试验工具残留治理.md"
    fixed_now = datetime(2026, 6, 11, 9, 30)

    gov.write_trial_tool_card(str(card), findings, str(docs), now=fixed_now)
    first = card.read_text(encoding="utf-8")
    gov.write_trial_tool_card(str(card), findings, str(docs), now=fixed_now)
    second = card.read_text(encoding="utf-8")

    assert first == second
    assert second.count(gov.TRIAL_TOOL_CARD_SOURCE) == 2
    assert second.count(gov.TRIAL_TOOL_SCAN_BEGIN) == 1
    assert second.count(gov.TRIAL_TOOL_SCAN_END) == 1
    assert "source: documents-doctor/trial-tools-openclaw-qclaw" in second
    assert "status: todo" in second
