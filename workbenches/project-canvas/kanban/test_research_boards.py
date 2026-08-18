#!/usr/bin/env python3
"""Tests for research project board discovery (桥接「研究项目板」分组的数据源)."""

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _config(root, extra=None):
    cfg = {'research_boards_dir': str(root)}
    if extra:
        cfg.update(extra)
    return cfg


def test_discovers_panel_html_at_depth_one_and_two(tmp_path):
    (tmp_path / 'C3-Gastric' / 'codex_panel').mkdir(parents=True)
    (tmp_path / 'C3-Gastric' / 'codex_panel' / 'Codex_Execution_Panel.html').write_text('<html></html>')
    (tmp_path / 'WHF-AP-LLM').mkdir()
    (tmp_path / 'WHF-AP-LLM' / 'Project_Panel.html').write_text('<html></html>')

    boards = scan_mod.discover_research_boards(_config(tmp_path))

    names = [b['name'] for b in boards]
    assert names == ['C3-Gastric', 'WHF-AP-LLM']
    by_name = {b['name']: b for b in boards}
    assert by_name['C3-Gastric']['path'].endswith('Codex_Execution_Panel.html')
    assert by_name['WHF-AP-LLM']['path'].endswith('Project_Panel.html')


def test_skips_archive_dot_dirs_and_projects_without_panel(tmp_path):
    (tmp_path / '_archive' / 'Old').mkdir(parents=True)
    (tmp_path / '_archive' / 'Old_Panel.html').write_text('x')
    (tmp_path / '.hidden').mkdir()
    (tmp_path / 'NoPanelProject').mkdir()
    (tmp_path / 'NoPanelProject' / 'README.md').write_text('no panel here')

    boards = scan_mod.discover_research_boards(_config(tmp_path))

    assert boards == []


def test_panel_md_pointer_supports_url_and_relative_path(tmp_path):
    remote = tmp_path / 'RemoteProject'
    remote.mkdir()
    (remote / 'PANEL.md').write_text('# 项目板\n\nhttps://example.org/board\n')

    local = tmp_path / 'LocalProject'
    local.mkdir()
    (local / 'board.html').write_text('<html></html>')
    (local / 'PANEL.md').write_text('board.html\n')

    boards = scan_mod.discover_research_boards(_config(tmp_path))

    by_name = {b['name']: b for b in boards}
    assert by_name['RemoteProject']['url'] == 'https://example.org/board'
    assert by_name['RemoteProject']['path'] == ''
    assert by_name['LocalProject']['path'].endswith('board.html')


def test_config_entries_take_precedence_and_dedupe_by_name(tmp_path):
    (tmp_path / 'C3-Gastric').mkdir()
    (tmp_path / 'C3-Gastric' / 'Auto_Panel.html').write_text('x')

    boards = scan_mod.discover_research_boards(_config(tmp_path, {
        'research_boards': [
            {'name': 'C3-Gastric', 'url': 'https://example.org/manual'},
            {'name': 'ExtraBoard', 'path': str(tmp_path / 'C3-Gastric' / 'Auto_Panel.html')},
            {'name': '', 'url': 'https://example.org/ignored'},
            {'name': 'NoTarget'},
            'not-a-dict',
        ],
    }))

    names = [b['name'] for b in boards]
    assert names == ['C3-Gastric', 'ExtraBoard']
    assert boards[0]['url'] == 'https://example.org/manual'


def test_missing_dir_returns_config_entries_only(tmp_path):
    boards = scan_mod.discover_research_boards(_config(tmp_path / 'does-not-exist', {
        'research_boards': [{'name': 'OnlyManual', 'url': 'https://example.org/x'}],
    }))
    assert [b['name'] for b in boards] == ['OnlyManual']
