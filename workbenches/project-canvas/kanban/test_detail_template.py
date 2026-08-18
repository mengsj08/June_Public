#!/usr/bin/env python3
"""Tests for detail page template routing."""

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_RENDER_DETAIL = _HERE / 'static' / 'kanban' / 'modules' / 'render-detail.js'
_RENDER_DETAIL_MODULES = (
    _RENDER_DETAIL,
    _HERE / 'static' / 'kanban' / 'modules' / 'render-detail-actions.js',
    _HERE / 'static' / 'kanban' / 'modules' / 'render-detail-view.js',
)


def test_next_step_relay_only_exposes_derived_task():
    actions = (_HERE / 'static' / 'kanban' / 'modules' / 'render-detail-actions.js').read_text(encoding='utf-8')
    api = (_HERE / 'static' / 'kanban' / 'modules' / 'api.js').read_text(encoding='utf-8')
    start = actions.index('  function appendNextStepRelay(task) {')
    end = actions.index('  function appendDangerZone(task) {', start)
    relay = actions[start:end]

    assert relay.count("document.createElement('button')") == 1
    assert '派生子任务' in relay
    for retired in (
        '晋升为场景', '用 AI 填充场景草稿', '查看晋升场景',
        '交接团队', '扫前沿对标', '/api/promote', '/api/team/handoff',
        '/api/spawn-prior-art',
    ):
        assert retired not in actions
        assert retired not in api


def test_detail_relay_template_applies_to_all_real_task_cards():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ shouldRenderNextStepRelay }} from {str(_RENDER_DETAIL.as_uri())!r};

      const taskPath = 'project/个人调度/skill治理文档漂移修正-旧Intake与旧三视图.md';
      const statuses = ['todo', 'in-progress', 'review', 'done'];
      for (const status of statuses) {{
        if (!shouldRenderNextStepRelay({{ status, path: taskPath }})) {{
          throw new Error(`expected relay template for real task status ${{status}}`);
        }}
      }}

      if (shouldRenderNextStepRelay({{ status: 'review', title: '动态摘要，无任务文件' }})) {{
        throw new Error('non-task summaries without path must not render task relay controls');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_activity_source_history_hides_empty_ledgers_and_compacts_real_records():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ activitySourceHistoryModel }} from {str(_RENDER_DETAIL.as_uri())!r};

      if (activitySourceHistoryModel({{ok: true, count: 0, entries: []}}) !== null) {{
        throw new Error('empty ledgers must not render an activity entry');
      }}
      const entries = Array.from({{length: 14}}, (_, index) => ({{event: `event-${{index}}`}}));
      const model = activitySourceHistoryModel({{
        ok: true,
        count: 14,
        source_counts: {{canvas: 3, lineage: 4, comments: 7}},
        entries,
      }});
      if (!model || model.count !== 14) throw new Error('record count drifted');
      if (model.recent.length !== 12 || model.recent[0].event !== 'event-13') {{
        throw new Error('history must show the latest twelve records first');
      }}
      if (model.sourceCounts.canvas !== 3 || model.sourceCounts.lineage !== 4 || model.sourceCounts.comments !== 7) {{
        throw new Error('source counts drifted');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)

    source = '\n'.join(path.read_text(encoding='utf-8') for path in _RENDER_DETAIL_MODULES)
    assert '事实时间线' not in source
    assert "label.textContent = '活动与来源'" in source
    assert 'if (!model || !history.isConnected) return' in source
    assert 'history.hidden = false' in source
