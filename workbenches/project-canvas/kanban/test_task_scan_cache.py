import importlib.util
import os
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('scan_docs_task_cache_test', HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan_mod)


def _write_card(path, *, title='First', status='todo'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '\n'.join([
            '---',
            f'title: {title}',
            'task_id: KAN-1',
            'created: 2026-08-14',
            'updated: 2026-08-14',
            f'status: {status}',
            'tags: []',
            '---',
            '',
            'body',
            '',
        ]),
        encoding='utf-8',
    )


def _scan_in(repo_root):
    with patch.object(scan_mod, 'REPO_ROOT', repo_root), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        return scan_mod.scan_all()


def test_second_scan_hits_directory_cache_without_reparsing(tmp_path):
    card = tmp_path / 'project' / 'Demo' / 'KAN-1.md'
    _write_card(card)
    scan_mod.task_scan_cache.reset()

    first = _scan_in(tmp_path)
    after_cold = scan_mod.task_scan_cache.stats()
    second = _scan_in(tmp_path)
    after_hot = scan_mod.task_scan_cache.stats()

    assert first == second
    assert after_cold['parsed_files'] == 1
    assert after_hot['parsed_files'] == 1
    assert after_hot['directory_hits'] == after_cold['directory_hits'] + 1


def test_api_write_invalidates_cached_card(tmp_path):
    card = tmp_path / 'project' / 'Demo' / 'KAN-1.md'
    _write_card(card)
    scan_mod.task_scan_cache.reset()
    assert _scan_in(tmp_path)[0]['status'] == 'todo'

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        ok, _message = scan_mod.update_frontmatter_field(
            'project/Demo/KAN-1.md',
            'status',
            'in-progress',
        )[:2]
        refreshed = scan_mod.get_data()['tasks']

    assert ok is True
    assert refreshed[0]['status'] == 'in-progress'
    assert scan_mod.task_scan_cache.stats()['invalidations'] >= 1


def test_external_edit_is_visible_on_next_api_read(tmp_path):
    card = tmp_path / 'project' / 'Demo' / 'KAN-1.md'
    _write_card(card, title='Before external edit')
    scan_mod.task_scan_cache.reset()
    assert _scan_in(tmp_path)[0]['title'] == 'Before external edit'

    previous = card.stat()
    _write_card(card, title='After external edit')
    # Make the metadata change deterministic even on a coarse-mtime filesystem.
    os.utime(card, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        refreshed = scan_mod.get_data()['tasks']

    assert refreshed[0]['title'] == 'After external edit'
    assert scan_mod.task_scan_cache.stats()['parsed_files'] == 2


def test_same_count_non_max_file_change_is_not_hidden_by_directory_signature(tmp_path):
    older = tmp_path / 'project' / 'Demo' / 'KAN-1.md'
    newer = tmp_path / 'project' / 'Demo' / 'KAN-2.md'
    _write_card(older, title='Older')
    _write_card(newer, title='Newer')
    base = 1_800_000_000_000_000_000
    os.utime(older, ns=(base, base))
    os.utime(newer, ns=(base + 10_000_000_000, base + 10_000_000_000))
    scan_mod.task_scan_cache.reset()
    _scan_in(tmp_path)

    _write_card(older, title='Older changed')
    os.utime(older, ns=(base + 1_000_000_000, base + 1_000_000_000))
    docs = _scan_in(tmp_path)

    assert {doc['title'] for doc in docs} == {'Older changed', 'Newer'}
    assert scan_mod.task_scan_cache.stats()['parsed_files'] == 3


def test_scan_keeps_caller_path_spelling_for_relative_path_guard(tmp_path, monkeypatch):
    card = tmp_path / 'project' / 'Demo' / 'KAN-1.md'
    _write_card(card)
    scan_mod.task_scan_cache.reset()
    seen = []

    def strict_skip(path, patterns):
        seen.append(str(path.relative_to(tmp_path)))
        return False

    monkeypatch.setattr(scan_mod, '_should_skip', strict_skip)
    monkeypatch.setattr(scan_mod, 'load_config', lambda: {'skip_patterns': ['*.never']})
    assert _scan_in(tmp_path)[0]['title'] == 'First'
    assert seen == ['project/Demo/KAN-1.md']


def test_soft_archive_removes_card_from_cached_scan(tmp_path):
    card = tmp_path / 'project' / 'Demo' / 'KAN-1.md'
    _write_card(card)
    scan_mod.task_scan_cache.reset()
    assert len(_scan_in(tmp_path)) == 1

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        result, status = scan_mod.archive_task_card('project/Demo/KAN-1.md')
        refreshed = scan_mod.scan_all()

    assert status == 200
    assert result['archived_path'] == 'project/Demo/.archive/KAN-1.md'
    assert refreshed == []
    assert (tmp_path / result['archived_path']).exists()
