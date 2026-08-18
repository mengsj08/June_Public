import importlib.util
from pathlib import Path
from unittest.mock import patch


_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs_canvas_ref', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def test_filename_resolution_reports_roots_and_repairs_after_file_arrives(tmp_path):
    allowed = tmp_path / 'Documents'
    workdir = allowed / 'case'
    task = allowed / 'cards' / 'card.md'
    workdir.mkdir(parents=True)
    task.parent.mkdir(parents=True)
    task.write_text('---\ntitle: t\n---\n', encoding='utf-8')
    config = {'open_allowed_roots': [str(allowed)]}
    fm = {'workdir': str(workdir)}

    with patch.object(scan_mod, 'REPO_ROOT', allowed):
        missing = scan_mod.resolve_canvas_source_ref('outside.md', task, fm, config=config)
        assert missing['status'] == 'missing'
        assert str(workdir) in missing['searched_roots']
        assert missing['allowed_roots'] == [str(allowed)]

        repaired = workdir / 'outside.md'
        repaired.write_text('real content', encoding='utf-8')
        resolved = scan_mod.resolve_canvas_source_ref('outside.md', task, fm, config=config)
    assert resolved['status'] == 'resolved'
    assert resolved['resolved_path'] == str(repaired)
