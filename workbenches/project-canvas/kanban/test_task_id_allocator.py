import importlib.util
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    'kanban_task_id_allocator_tested',
    _HERE / 'task_id_allocator.py',
)
allocator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(allocator)


def test_next_task_sequence_uses_recursive_disk_maximum(tmp_path):
    project = tmp_path / 'project' / '个人调度'
    archive = project / '.archive'
    archive.mkdir(parents=True)
    (project / 'KAN-8_Active.md').write_text('', encoding='utf-8')
    (archive / 'KAN-14_Archived.md').write_text('', encoding='utf-8')
    (project / 'KAN-invalid_Ignored.md').write_text('', encoding='utf-8')

    assert allocator.max_task_sequence_on_disk(tmp_path, 'KAN') == 14
    assert allocator.next_task_sequence(tmp_path, 'KAN', 9) == 15


def test_next_task_sequence_preserves_ahead_counter(tmp_path):
    project = tmp_path / 'project' / 'Hermes'
    project.mkdir(parents=True)
    (project / 'HER-4_Existing.md').write_text('', encoding='utf-8')

    assert allocator.next_task_sequence(tmp_path, 'HER', 20) == 21


def test_max_task_sequence_rejects_invalid_prefix(tmp_path):
    with pytest.raises(ValueError, match='invalid task_id prefix'):
        allocator.max_task_sequence_on_disk(tmp_path, '../KAN')
