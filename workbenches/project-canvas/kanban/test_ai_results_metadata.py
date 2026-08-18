#!/usr/bin/env python3
"""KAN-834 回归:/api/ai-results 序列化必须透出 entry.metadata（含 fork 父指针）。

背景:分叉线程的父子关系存在 metadata.fork.{parent_run_id, parent_index}。
旧序列化用显式字段白名单,漏掉 metadata,导致前端树逻辑(buildThreadTree/
createBranchGroup)拿不到 fork,每条分叉退化成底部平铺卡片而非嵌套。
既有 test_ai_thread_tree.py 直接喂带 metadata 的假数据给前端 JS,从不经过
本端点,所以抓不到这个丢字段的 bug——本测试专门补这层边界。

Run: CI=true python3 -m pytest shared/toolkit/kanban/test_ai_results_metadata.py -v
"""

import json
from pathlib import Path
import importlib.util
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)
Handler = scan_mod.Handler


def _make_get_handler(path):
    """最小 Handler:只设 path,把 _json 输出截获下来。"""
    class _Resp:
        code = None
        data = None

    resp = _Resp()

    class TestHandler(Handler):
        def __init__(self):
            self.path = path

        def _json(self, data, code=200):
            resp.code = code
            resp.data = data

    return TestHandler(), resp


def test_ai_results_preserves_fork_metadata():
    parent = {
        'id': 'parent99', 'tool': 'codex', 'path': 'project/X/t.md', 'status': 'completed',
        'messages': [{'role': 'user', 'content': 'hi'}, {'role': 'ai', 'content': 'yo'}],
        'metadata': {'dialogue': {'origin': 'card_chat'}},
    }
    child = {
        'id': 'child01', 'tool': 'codex', 'path': 'project/X/t.md', 'status': 'completed',
        'messages': [{'role': 'user', 'content': 'fork'}],
        'metadata': {'fork': {
            'parent_run_id': 'parent99', 'parent_index': 1, 'parent_entry_id': 'parent99#1',
        }},
    }

    handler, resp = _make_get_handler('/api/ai-results?path=project/X/t.md')
    with patch.object(scan_mod, '_queue_get_by_path', return_value=[parent, child]):
        handler.do_GET()

    assert resp.code == 200
    assert resp.data['ok'] is True
    by_id = {r['run_id']: r for r in resp.data['results']}
    assert set(by_id) == {'parent99', 'child01'}

    # 核心回归断言:fork 子条目必须带 metadata.fork,且父指针完整
    assert 'metadata' in by_id['child01'], 'ai-results 丢失了 metadata（KAN-834 回归）'
    fork = (by_id['child01']['metadata'] or {}).get('fork') or {}
    assert fork.get('parent_run_id') == 'parent99'
    assert fork.get('parent_index') == 1
    # 父条目的 metadata 也应透出(非 fork 类)
    assert 'metadata' in by_id['parent99']
