#!/usr/bin/env python3
"""Tests for ownership lint false-open detection."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _write_card(root, name, *, task_id='GOV-1', extra='', body=''):
    task_dir = root / 'project' / '个人调度'
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / name
    path.write_text(
        f"""---
title: Governance lint scan
task_id: {task_id}
task_family: governance
status: todo
assignee: Owner
{extra}---

{body}
""",
        encoding='utf-8',
    )
    return path


def _standard_done_body():
    return """## 背景 / 来源
已完成的交付记录，需要被 Owner 看见后验收。

## 要做什么
回放 done 初建逃逸。

## 完成标准
- [x] 有交付记录

## 执行结果
已完成。
"""


def test_ownership_lint_flags_owner_visible_runtime_card(tmp_path):
    for idx, signal in enumerate(('lint 扫描', '探针生成', '记录回填', '账本统计'), start=1):
        _write_card(
            tmp_path,
            f'GOV-{idx}_false_open.md',
            task_id=f'GOV-{idx}',
            extra=f'stage: governance/lint\nnext_action: Codex 执行 {signal} 并回填结果\n',
        )

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_ownership_lint_report(scan_mod.scan_all())

    assert report['summary']['checked_active_cards'] == 4
    assert report['summary']['owner_visible_checked'] == 4
    assert report['summary']['suspected_misopened'] == 4
    assert [issue['type'] for issue in report['issues']] == ['suspected_false_open'] * 4
    assert all('runtime_signal' in issue['ai_owned_reversible_reasons'] for issue in report['issues'])


def test_ownership_lint_keeps_real_human_gate_visible(tmp_path):
    _write_card(
        tmp_path,
        'GOV-2_real_gate.md',
        task_id='GOV-2',
        extra='stage: governance/decision\nnext_action: Owner 确认是否发布对外文案\n',
    )

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_ownership_lint_report(scan_mod.scan_all())

    assert report['summary']['checked_active_cards'] == 1
    assert report['summary']['owner_visible_checked'] == 1
    assert report['summary']['suspected_misopened'] == 0
    assert report['issues'] == []


def test_ownership_lint_flags_kmo48_shape_done_at_creation(tmp_path):
    _write_card(
        tmp_path,
        'KMO-48_original_done_record.md',
        task_id='KMO-48',
        extra=(
            'status: done\n'
            'created: 2026-07-01\n'
            'updated: 2026-07-01\n'
            'status_changed_at: 2026-07-01\n'
            'kind: record\n'
            'responsibility: ai-owned\n'
            'safety: reversible\n'
        ),
        body=_standard_done_body(),
    )

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_ownership_lint_report(scan_mod.scan_all())

    assert report['summary']['checked_active_cards'] == 0
    assert report['summary']['checked_done_cards'] == 1
    assert report['summary']['done_at_creation_owner_visible'] == 1
    assert report['ok'] is False
    assert [issue['type'] for issue in report['issues']] == ['done_at_creation_owner_visible']
    assert report['issues'][0]['severity'] == 'error'


def test_ownership_lint_keeps_review_then_done_card_clear(tmp_path):
    _write_card(
        tmp_path,
        'GOV-3_review_then_done.md',
        task_id='GOV-3',
        extra=(
            'status: done\n'
            'created: 2026-07-01\n'
            'updated: 2026-07-02\n'
            'status_changed_at: 2026-07-02\n'
            'responsibility: ai-owned\n'
            'safety: reversible\n'
        ),
        body=_standard_done_body(),
    )

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_ownership_lint_report(scan_mod.scan_all())

    assert report['summary']['checked_done_cards'] == 1
    assert report['summary']['done_at_creation_owner_visible'] == 0
    assert report['ok'] is True
    assert report['issues'] == []


def test_ownership_lint_keeps_plain_done_task_clear(tmp_path):
    _write_card(
        tmp_path,
        'GOV-5_plain_done_task.md',
        task_id='GOV-5',
        extra=(
            'status: done\n'
            'created: 2026-07-01\n'
            'updated: 2026-07-01\n'
            'status_changed_at: 2026-07-01\n'
            'responsibility: ai-owned\n'
            'safety: reversible\n'
        ),
        body=_standard_done_body(),
    )

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_ownership_lint_report(scan_mod.scan_all())

    assert report['summary']['checked_done_cards'] == 1
    assert report['summary']['done_at_creation_owner_visible'] == 0
    assert report['issues'] == []


def test_ownership_lint_exempts_explicit_backstage_done_ledger(tmp_path):
    _write_card(
        tmp_path,
        'GOV-4_backstage_done.md',
        task_id='GOV-4',
        extra=(
            'status: done\n'
            'created: 2026-07-01\n'
            'updated: 2026-07-01\n'
            'status_changed_at: 2026-07-01\n'
            'responsibility: ai-owned\n'
            'safety: reversible\n'
            'audience: backstage\n'
        ),
        body=_standard_done_body(),
    )

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        report = scan_mod.build_ownership_lint_report(scan_mod.scan_all())

    assert report['summary']['checked_done_cards'] == 1
    assert report['summary']['backstage_done_exempted'] == 1
    assert report['summary']['done_at_creation_owner_visible'] == 0
    assert report['ok'] is True
    assert report['issues'] == []
