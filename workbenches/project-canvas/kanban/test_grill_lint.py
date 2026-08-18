#!/usr/bin/env python3
"""Tests for the read-only Owner execution-card grill lint."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs_grill', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _write_card(root, name, *, task_id, status, assignee, grill_status=None):
    task_dir = root / 'project' / '个人调度'
    task_dir.mkdir(parents=True, exist_ok=True)
    grill_line = '' if grill_status is None else f'grill_status: {grill_status}\n'
    (task_dir / name).write_text(
        f"""---
title: Grill lint fixture
task_id: {task_id}
task_family: governance
status: {status}
assignee: {assignee}
{grill_line}---

## 要做什么
Fixture.
""",
        encoding='utf-8',
    )


def test_grill_lint_flags_missing_and_pending_with_status_alias(tmp_path):
    _write_card(tmp_path, 'GOV-1_missing.md', task_id='GOV-1', status='in-progress', assignee='Owner')
    _write_card(tmp_path, 'GOV-2_pending.md', task_id='GOV-2', status='in_progress', assignee='Owner', grill_status='pending')
    _write_card(tmp_path, 'GOV-3_done_grill.md', task_id='GOV-3', status='doing', assignee='Owner', grill_status='done-3项收敛')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_grill_lint_report(scan_mod.scan_all())

    assert report['checked_owner_execution_cards'] == 3
    assert report['missing_grill_status'] == 1
    assert report['pending_grill'] == 1
    assert [item['task_id'] for item in report['candidates']] == ['GOV-1', 'GOV-2']


def test_grill_lint_ignores_ai_review_and_done_cards(tmp_path):
    _write_card(tmp_path, 'GOV-4_ai.md', task_id='GOV-4', status='in-progress', assignee='Codex')
    _write_card(tmp_path, 'GOV-5_review_gate.md', task_id='GOV-5', status='review', assignee='Owner')
    _write_card(tmp_path, 'GOV-6_done.md', task_id='GOV-6', status='done', assignee='Owner')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_grill_lint_report(scan_mod.scan_all())

    assert report['checked_owner_execution_cards'] == 0
    assert report['missing_grill_status'] == 0
    assert report['pending_grill'] == 0
    assert report['candidates'] == []
