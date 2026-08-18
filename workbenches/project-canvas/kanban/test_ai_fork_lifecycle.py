#!/usr/bin/env python3
"""回归:分叉必须继承父线程的 dialogue lifecycle。

背景:未晋升旁聊(durable_on_promotion)靠 metadata.dialogue.lifecycle 被
Conversation Project Graph 投影跳过；旧 _handle_ai_fork 只带 metadata.fork,
丢失 lifecycle 后分叉支线会以 branch_placeholder 漏进长期图,绕过
「保留到地图」晋升闸(需求 SELECTION_BRANCH_ARCHIVE_REQUIREMENTS §2.2)。

Run: CI=true python3 -m pytest shared/toolkit/kanban/test_ai_fork_lifecycle.py -v
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs_fork_lifecycle', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _fork(parent):
    captured = {}

    def fake_add_entry(tool, path, workdir='', prompt_override=None, post_success_frontmatter=None,
                       metadata=None, dedupe_key=None, ai_profile=None):
        captured['metadata'] = metadata
        captured['ai_profile'] = ai_profile
        return 'child-1'

    with patch.object(scan_mod, '_queue_get_entry', return_value=parent), \
         patch.object(scan_mod, '_queue_add_entry', side_effect=fake_add_entry), \
         patch.object(scan_mod, '_queue_append_message'), \
         patch.object(scan_mod, '_queue_consume_next'):
        result = scan_mod._handle_ai_fork(parent['id'], 0, '继续追问')
    assert result['ok'] is True
    return captured


def test_fork_inherits_side_chat_lifecycle_and_profile():
    parent = {
        'id': 'parent-1', 'tool': 'claude', 'path': 'project/X/t.md', 'workdir': '',
        'ai_profile': 'deep_claude',
        'messages': [{'role': 'user', 'content': 'hi'}],
        'metadata': {'dialogue': {'origin': 'selection_side_chat', 'lifecycle': 'durable_on_promotion'}},
    }
    captured = _fork(parent)
    assert captured['metadata']['dialogue'] == {
        'origin': 'selection_side_chat', 'lifecycle': 'durable_on_promotion',
    }
    assert captured['metadata']['fork']['parent_run_id'] == 'parent-1'
    assert captured['ai_profile'] == 'deep_claude'


def test_fork_of_plain_run_adds_no_dialogue_metadata():
    parent = {
        'id': 'parent-2', 'tool': 'codex', 'path': 'project/X/t.md', 'workdir': '',
        'messages': [{'role': 'user', 'content': 'hi'}],
    }
    captured = _fork(parent)
    assert 'dialogue' not in captured['metadata']
    assert captured['metadata']['fork']['parent_run_id'] == 'parent-2'
