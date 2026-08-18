#!/usr/bin/env python3
"""Tests for archive_done_tasks (feeder 约定的回流闭环：done 卡定期移入 .archive/)."""

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _write_card(project_dir, name, status, updated):
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / name).write_text(f"""---
title: {name}
created: 2026-01-01
updated: {updated}
status: {status}
tags: []
---

Body.
""", encoding='utf-8')


def _days_ago(days):
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')


def test_archives_old_done_cards_only(tmp_path):
    proj = tmp_path / 'project' / '个人调度'
    _write_card(proj, 'old-done.md', 'done', _days_ago(10))
    _write_card(proj, 'fresh-done.md', 'done', _days_ago(2))
    _write_card(proj, 'old-todo.md', 'todo', _days_ago(30))

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        moved = scan_mod.archive_done_tasks(days=7)

    assert len(moved) == 1
    assert moved[0][0].endswith('old-done.md')
    assert not (proj / 'old-done.md').exists()
    assert (proj / '.archive' / 'old-done.md').exists()
    assert (proj / 'fresh-done.md').exists()
    assert (proj / 'old-todo.md').exists()


def test_archive_is_idempotent_and_skips_name_clash(tmp_path):
    proj = tmp_path / 'project' / '个人调度'
    _write_card(proj, 'card.md', 'done', _days_ago(10))
    (proj / '.archive').mkdir(parents=True)
    (proj / '.archive' / 'card.md').write_text('already archived', encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        moved = scan_mod.archive_done_tasks(days=7)

    assert moved == []
    assert (proj / 'card.md').exists()
    assert (proj / '.archive' / 'card.md').read_text(encoding='utf-8') == 'already archived'


def test_unparseable_updated_is_left_alone(tmp_path):
    proj = tmp_path / 'project' / '个人调度'
    _write_card(proj, 'no-date.md', 'done', '未知')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        moved = scan_mod.archive_done_tasks(days=7)

    assert moved == []
    assert (proj / 'no-date.md').exists()


def test_archived_cards_disappear_from_scan(tmp_path):
    proj = tmp_path / 'project' / '个人调度'
    _write_card(proj, 'old-done.md', 'done', _days_ago(10))

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        scan_mod.archive_done_tasks(days=7)
        with patch.object(scan_mod, 'load_config', return_value={}):
            docs = scan_mod.scan_all()

    assert docs == []
