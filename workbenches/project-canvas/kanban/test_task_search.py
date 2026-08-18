#!/usr/bin/env python3
"""Tests for the global task search (searchTasks) frontend helper."""

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_RENDER_BOARD = _HERE / 'static' / 'kanban' / 'modules' / 'render-board.js'


def test_search_tasks_matching_and_ranking():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ searchTasks }} from {str(_RENDER_BOARD.as_uri())!r};

      const tasks = [
        {{ task_id: 'XXX-30', title: '团队对接双向闭环落地', project: '个人调度', assignee: 'Codex', status: 'in-progress', tags: ['chains', 'team'] }},
        {{ task_id: 'XXX-21', title: '梳理链路逻辑 3/5：团队链', project: '个人调度', assignee: 'Owner', status: 'done', tags: ['chains', '链路梳理'] }},
        {{ task_id: 'GOV-1', title: '治理复核（每周）', project: '个人调度', assignee: 'Owner', status: 'todo', tags: ['governance'] }},
        {{ task_id: 'CJK-1', title: '评审并发布场景', project: '场景库运营', assignee: 'Owner', status: 'review', tags: [] }},
      ];

      if (searchTasks(tasks, '').length !== 0) throw new Error('empty query must return nothing');
      if (searchTasks(tasks, '   ').length !== 0) throw new Error('blank query must return nothing');

      const byId = searchTasks(tasks, 'gov-1');
      if (byId.length !== 1 || byId[0].task_id !== 'GOV-1') throw new Error('exact task_id should match case-insensitively');

      const byPrefix = searchTasks(tasks, 'xxx');
      if (byPrefix.length !== 2) throw new Error('task_id prefix should match both XXX cards');
      if (byPrefix[0].status === 'done') throw new Error('active card should rank above done card on ties');

      const byTitle = searchTasks(tasks, '团队');
      if (!byTitle.some((t) => t.task_id === 'XXX-30') || !byTitle.some((t) => t.task_id === 'XXX-21')) {{
        throw new Error('title keyword should match both team cards');
      }}

      const multiTerm = searchTasks(tasks, '团队 done');
      if (multiTerm.length !== 1 || multiTerm[0].task_id !== 'XXX-21') throw new Error('multi terms should AND across fields');

      const byTag = searchTasks(tasks, 'governance');
      if (byTag.length !== 1 || byTag[0].task_id !== 'GOV-1') throw new Error('tags should be searchable');

      const limited = searchTasks(tasks, 'owner', 2);
      if (limited.length !== 2) throw new Error('limit should cap results');

      console.log('OK');
    """
    result = subprocess.run(
        [node, '--input-type=module', '-e', script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'OK' in result.stdout
