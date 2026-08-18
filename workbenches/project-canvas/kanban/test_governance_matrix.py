#!/usr/bin/env python3
"""Tests for the governance inspection matrix loader (链路视图的治理矩阵数据源)."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def test_loads_valid_matrix(tmp_path):
    matrix = {
        'verified_at': '2026-06-09',
        'workspaces': ['ResearchLab'],
        'rules': [{'key': 'G1', 'title': '域即边界', 'cells': {'ResearchLab': {'state': 'pass'}}}],
    }
    path = tmp_path / 'matrix.json'
    path.write_text(json.dumps(matrix, ensure_ascii=False), encoding='utf-8')

    with patch.object(scan_mod, 'GOVERNANCE_MATRIX_PATH', path):
        result = scan_mod.load_governance_matrix()

    assert result['ok'] is True
    assert result['verified_at'] == '2026-06-09'
    assert result['rules'][0]['key'] == 'G1'


def test_missing_file_returns_error(tmp_path):
    with patch.object(scan_mod, 'GOVERNANCE_MATRIX_PATH', tmp_path / 'absent.json'):
        result = scan_mod.load_governance_matrix()
    assert result['ok'] is False


def test_invalid_json_and_missing_rules_return_error(tmp_path):
    broken = tmp_path / 'broken.json'
    broken.write_text('{not json', encoding='utf-8')
    with patch.object(scan_mod, 'GOVERNANCE_MATRIX_PATH', broken):
        assert scan_mod.load_governance_matrix()['ok'] is False

    no_rules = tmp_path / 'no_rules.json'
    no_rules.write_text(json.dumps({'workspaces': []}), encoding='utf-8')
    with patch.object(scan_mod, 'GOVERNANCE_MATRIX_PATH', no_rules):
        assert scan_mod.load_governance_matrix()['ok'] is False


# 针对私有 governance/matrix.json 实文件的校验用例未随仓迁移;loader 行为由上方用例覆盖。
