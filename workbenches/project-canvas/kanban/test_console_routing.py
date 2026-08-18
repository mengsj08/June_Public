#!/usr/bin/env python3
"""调度台分流不变量测试(2026-07-03,KAN-109/111 隐身事故的固化回归)。

两条不变量:
1. 显式人闸 review 豁免治理分流——只有 human gate 才进入 Owner 验收面。
2. kanban 家族卡的治理判定只认结构化字段(domain/tags/stage/前缀),不猜标题关键词。
   (旧行为:标题命中「看板/调度台/验收/队列」即整卡扫出调度台,曾吞掉 44% 活跃卡,
    含 3 张本该在「等我验收」的 review 卡。)
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_RENDER_BOARD = _HERE / 'static' / 'kanban' / 'modules' / 'render-board.js'


def test_console_routing_invariants():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ isGovernanceBurdenTask, isConsoleReviewTask }} from {str(_RENDER_BOARD.as_uri())!r};

      const fail = (msg) => {{ throw new Error(msg); }};

      // 不变量 1:显式人闸 review 卡即使满身治理信号,也不许被分流,必须进「等我验收」
      const reviewKanban = {{ task_id: 'KAN-901', task_family: 'kanban', status: 'review',
        title: '看板调度台验收队列治理规则', tags: [], responsibility: 'pi-gated', human_gate: true, attention_scope: 'owner' }};
      if (isGovernanceBurdenTask(reviewKanban)) fail('review kanban 卡被治理分流(不变量 1 破)');
      if (!isConsoleReviewTask(reviewKanban, 'Owner')) fail('review kanban 卡未进等我验收');

      const reviewGov = {{ task_id: 'GOV-901', task_family: 'governance', status: 'review',
        title: '治理巡检整改', domain: 'governance', responsibility: 'pi-gated', human_gate: true, attention_scope: 'owner' }};
      if (isGovernanceBurdenTask(reviewGov)) fail('review GOV 卡被治理分流(review 豁免应无条件)');
      if (!isConsoleReviewTask(reviewGov, 'Owner')) fail('review GOV 卡未进等我验收');

      const aiReview = {{ task_id: 'KAN-906', task_family: 'kanban', status: 'review',
        title: 'AI 自检结果', responsibility: 'ai-owned', human_gate: false, attention_scope: 'backstage' }};
      if (isConsoleReviewTask(aiReview, 'Owner')) fail('AI-owned review 不得冒充 Owner 验收');

      // 不变量 2:kanban 家族靠结构化字段,标题关键词不再触发分流
      const productTodo = {{ task_id: 'KAN-902', task_family: 'kanban', status: 'todo',
        title: '看板评论分支·调度台画布·验收泳道·队列', tags: ['kanban'] }};
      if (isGovernanceBurdenTask(productTodo)) fail('kanban 产品卡被标题关键词误扫(不变量 2 破)');

      const explicitGov = {{ task_id: 'KAN-903', task_family: 'kanban', status: 'todo',
        title: '普通标题', domain: 'governance' }};
      if (!isGovernanceBurdenTask(explicitGov)) fail('显式 domain:governance 的 kanban 卡应分流');

      const explicitGovTag = {{ task_id: 'KAN-904', task_family: 'kanban', status: 'todo',
        title: '普通标题', tags: ['governance'] }};
      if (!isGovernanceBurdenTask(explicitGovTag)) fail('tags 含 governance 的 kanban 卡应分流');

      // 既有行为守住:GOV 前缀 todo 仍分流;done 不分流
      const govTodo = {{ task_id: 'GOV-902', task_family: 'governance', status: 'todo', title: '巡检' }};
      if (!isGovernanceBurdenTask(govTodo)) fail('GOV todo 卡应保持分流');
      const doneGov = {{ ...govTodo, status: 'done' }};
      if (isGovernanceBurdenTask(doneGov)) fail('done 卡不应分流');
      // KAN-999:治理身份只认显式字段,GOVERNANCE_SIGNAL_RE 文本兜底已退役——
      // 无任何显式治理字段的卡,标题再像治理也不分流(0703「只认显式字段」先例的收尾)。
      const legacyText = {{ task_id: 'X-1', status: 'todo', title: '治理巡检遗留清理' }};
      if (isGovernanceBurdenTask(legacyText)) fail('关键词文本兜底应已退役,纯标题治理卡不得分流');
      // KAN-999:显式 stage 永远优先——domain=governance 但 stage 标了别的链,不算治理域成员。
      const foreignStage = {{ task_id: 'KAN-905', status: 'todo', domain: 'governance', stage: 'km/curate', title: '文献策展' }};
      if (isGovernanceBurdenTask(foreignStage)) fail('显式外链 stage 的卡不应被治理域吸走');

      console.log('console routing invariants ok');
    """
    result = subprocess.run(
        [node, '--input-type=module', '-e', script],
        capture_output=True, text=True, check=True,
    )
    assert 'console routing invariants ok' in result.stdout
