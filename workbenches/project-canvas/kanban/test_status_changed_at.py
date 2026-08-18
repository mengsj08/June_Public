#!/usr/bin/env python3
"""Tests for status_changed_at write/read behavior."""

import importlib.util
import re
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _write_task(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("""---
title: Sample
task_id: HER-1
created: 2026-06-01
updated: 2026-06-01
assignee: Owner
priority: medium
status: todo
tags: []
---

Body.
""", encoding='utf-8')


def test_status_update_writes_status_changed_at(tmp_path):
    task_path = tmp_path / 'project' / 'Hermes' / 'sample.md'
    _write_task(task_path)

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        ok, msg = scan_mod.update_frontmatter_field(
            'project/Hermes/sample.md',
            'status',
            'in-progress',
            _suppress_decision_log=True,
        )

    assert ok, msg
    fm_block = task_path.read_text(encoding='utf-8').split('---', 2)[1]
    assert 'status: in-progress' in fm_block
    match = re.search(r'^status_changed_at: (\d{4}-\d{2}-\d{2})$', fm_block, re.M)
    assert match


def test_scan_all_backfills_missing_status_changed_at_as_inferred(tmp_path):
    task_path = tmp_path / 'project' / 'Hermes' / 'sample.md'
    _write_task(task_path)

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project/Hermes']):
        docs = scan_mod.scan_all()

    assert len(docs) == 1
    assert docs[0]['status_changed_at'] == '2026-06-01'
    assert docs[0]['status_changed_at_inferred'] is True
