#!/usr/bin/env python3
"""KAN-999「等 Owner 动作」一本账 + 链路由只认显式字段的回归测试。

三组用例（卡面完成标准）：
1. ownerActionNeeded 判定四象限（responsibility × status），含 AI 代收中 / gate 在途派生判定。
2. 业务 pi-gated 卡（无治理显式字段）不入治理链 / 治理域统计（review 实锤病灶：KAN-209/KAN-108 曾被吸进治理债）。
3. 双入口计数一致性：治理页顶部 needsDecision 与治理链健康行 waitingDecision 同源必然相等。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_RENDER_BOARD = _HERE / 'static' / 'kanban' / 'modules' / 'render-board.js'


def _run_node(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')
    return subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)


def test_owner_action_needed_four_quadrants():
    script = f"""
      import {{ ownerActionNeeded, isAiProxyReviewTask, isGateInFlightTask }} from {str(_RENDER_BOARD.as_uri())!r};
      const fail = (msg) => {{ throw new Error(msg); }};
      const card = (status, responsibility) => ({{ task_id: 'T-1', title: '象限卡', status, responsibility }});

      // pi-gated × status 四象限：todo/review 计 Owner 债，in-progress/done 不计。
      if (!ownerActionNeeded(card('todo', 'pi-gated'), 'Owner')) fail('pi-gated ∧ todo 应计等你动作（等你拍板）');
      if (!ownerActionNeeded(card('review', 'pi-gated'), 'Owner')) fail('pi-gated ∧ review 应计等你动作（等你验收）');
      if (ownerActionNeeded(card('in-progress', 'pi-gated'), 'Owner')) fail('pi-gated ∧ in-progress = gate 在途，不计 Owner 债');
      if (ownerActionNeeded(card('done', 'pi-gated'), 'Owner')) fail('done 卡永不计等你动作');

      // ai-owned × status：任何状态都不计 Owner 债；review 单列 AI 代收中。
      if (ownerActionNeeded(card('todo', 'ai-owned'), 'Owner')) fail('ai-owned todo 不计等你动作');
      if (ownerActionNeeded(card('review', 'ai-owned'), 'Owner')) fail('ai-owned review = AI 代收中，不计等你动作');
      if (ownerActionNeeded(card('review', ''), 'Owner')) fail('无 responsibility 的 review 卡不再一刀切计成 Owner 债');
      if (!isAiProxyReviewTask(card('review', 'ai-owned'))) fail('review ∧ ai-owned 应识别为 AI 代收中');
      if (isAiProxyReviewTask(card('review', 'pi-gated'))) fail('review ∧ pi-gated 是等你验收，不是 AI 代收');
      if (isAiProxyReviewTask(card('todo', 'ai-owned'))) fail('todo 卡不是代收');

      // gate 在途派生判定。
      if (!isGateInFlightTask(card('in-progress', 'pi-gated'))) fail('in-progress ∧ pi-gated 应识别为 gate 在途');
      if (isGateInFlightTask(card('in-progress', 'ai-owned'))) fail('ai-owned 在途卡不是 gate 在途');

      // 记录卡必须有显式 record 证据；human_gate/attention_scope 只负责注意力路由。
      const record = {{ task_id: 'R-1', title: '自动生成记录', status: 'review', responsibility: 'pi-gated', human_gate: false, attention_scope: 'backstage' }};
      // isConsoleRecordTask 对 pi-gated 卡显式豁免（responsibility 优先），故此卡仍计等你动作——
      // 换成无 responsibility 的纯记录卡验证记录豁免路径。
      const pureRecord = {{ task_id: 'R-2', title: '自动生成记录', status: 'review', doc_type: 'record', human_gate: false, attention_scope: 'backstage', responsibility: 'ai-owned' }};
      if (isAiProxyReviewTask(pureRecord)) fail('backstage 记录卡不应计入 AI 代收中');
      console.log('owner action four quadrants ok');
    """
    result = _run_node(script)
    assert 'owner action four quadrants ok' in result.stdout


def test_business_pi_gated_card_stays_out_of_governance():
    script = f"""
      import {{
        buildGovernanceBurdenModel,
        chainStageOf,
        isExplicitGovernanceTask,
        isGovernanceBurdenTask,
        normalizeFrontendChains,
      }} from {str(_RENDER_BOARD.as_uri())!r};
      const fail = (msg) => {{ throw new Error(msg); }};

      // review 实锤 fixture：北极星业务卡（无治理显式字段、responsibility=pi-gated）——
      // 旧 inferGovernanceStage 首行 pi-gated→gov/accept 一刀切曾把它们计成治理债。
      const investorCard = {{ task_id: 'KAN-209', task_family: 'kanban', title: '见投资人准备', status: 'todo', responsibility: 'pi-gated', project: '个人调度' }};
      const courseCard = {{ task_id: 'KAN-108', task_family: 'kanban', title: '课程推进拍板', status: 'review', responsibility: 'pi-gated', project: '个人调度' }};

      if (isExplicitGovernanceTask(investorCard)) fail('业务 pi-gated 卡不得判为治理域成员');
      if (isGovernanceBurdenTask(investorCard)) fail('业务 pi-gated 卡不得被治理分流');

      const gov = normalizeFrontendChains([{{ key: 'gov', stages: [
        {{ key: 'gov/triage', title: '判断' }}, {{ key: 'gov/accept', title: '验收' }},
      ] }}])[0];
      if (chainStageOf(investorCard, gov) !== null) fail('业务 pi-gated todo 卡不得入 gov 链');
      if (chainStageOf(courseCard, gov) !== null) fail('业务 pi-gated review 卡不得入 gov 链（旧 pi-gated→gov/accept 一刀切已删）');

      const model = buildGovernanceBurdenModel([investorCard, courseCard], ['Codex'], 'Owner');
      if (model.total !== 0) fail(`业务卡不得进治理域统计, got total=${{model.total}}`);
      if (model.needsDecision !== 0) fail(`业务卡不得计成治理债, got needsDecision=${{model.needsDecision}}`);
      console.log('business pi-gated stays out of gov ok');
    """
    result = _run_node(script)
    assert 'business pi-gated stays out of gov ok' in result.stdout


def test_dual_entry_counts_are_identical():
    script = f"""
      import {{
        buildGovernanceBurdenModel,
        chainHealthScore,
        normalizeFrontendChains,
      }} from {str(_RENDER_BOARD.as_uri())!r};
      const fail = (msg) => {{ throw new Error(msg); }};

      // 今日盘面的缩影 fixture（卡面「输入与材料」预期）：
      //  - GOV-398 todo·pi-gated / GOV-83 review·pi-gated / GOV-104 review·pi-gated → 等你动作 3
      //  - KAN-209 / KAN-108 业务 pi-gated → 不入 gov
      //  - SKL-21 review·ai-owned → AI 代收中；GOV-11 in-progress·pi-gated → gate 在途
      const tasks = [
        {{ task_id: 'GOV-398', task_family: 'governance', title: '督促通道定稿', status: 'todo', responsibility: 'pi-gated' }},
        {{ task_id: 'GOV-83', task_family: 'governance', title: '规则血统存量清算', status: 'review', responsibility: 'pi-gated' }},
        {{ task_id: 'GOV-104', task_family: 'governance', title: '治理口径定稿', status: 'review', responsibility: 'pi-gated' }},
        {{ task_id: 'GOV-11', task_family: 'governance', title: '机器判定探针', status: 'in-progress', responsibility: 'pi-gated' }},
        {{ task_id: 'SKL-21', task_family: 'skill', title: 'skill 治理复核', status: 'review', responsibility: 'ai-owned' }},
        {{ task_id: 'KAN-209', task_family: 'kanban', title: '见投资人准备', status: 'todo', responsibility: 'pi-gated' }},
        {{ task_id: 'KAN-108', task_family: 'kanban', title: '课程推进', status: 'review', responsibility: 'pi-gated' }},
        {{ task_id: 'GOV-0', task_family: 'governance', title: '已结治理卡', status: 'done' }},
      ];
      const gov = normalizeFrontendChains([{{ key: 'gov', stages: [
        {{ key: 'gov/sense', title: '感知' }}, {{ key: 'gov/triage', title: '判断' }},
        {{ key: 'gov/fix', title: '整改' }}, {{ key: 'gov/accept', title: '验收' }},
      ] }}])[0];

      const model = buildGovernanceBurdenModel(tasks, ['Codex'], 'Owner');
      const health = chainHealthScore(gov, tasks, Date.parse('2026-07-11T00:00:00Z'), 'Owner');

      // 双入口同源一致：治理页顶部计数 === 治理链健康行计数。
      if (model.needsDecision !== health.signals.waitingDecision) {{
        fail(`双入口计数不一致: 治理页 ${{model.needsDecision}} vs 链健康 ${{health.signals.waitingDecision}}`);
      }}
      if (model.needsDecision !== 3) fail(`预期等你动作 3（GOV-398/83/104）, got ${{model.needsDecision}}`);
      if (model.aiProxyReview !== 1) fail(`预期 AI 代收中 1（SKL-21）, got ${{model.aiProxyReview}}`);
      if (model.gateInFlight !== 1) fail(`预期 gate 在途 1（GOV-11）, got ${{model.gateInFlight}}`);
      if (health.signals.aiProxyReview !== 1) fail(`链健康应报 AI 代收中 1, got ${{health.signals.aiProxyReview}}`);
      // 罚分只罚 Owner 债：3 张 × 8 分。
      if (health.penalties.waitingDecision !== 24) fail(`waitingPenalty 应只罚 3 张 Owner 债 (24), got ${{health.penalties.waitingDecision}}`);
      // 每个数字可追到具体卡（refs 机制保留）。
      const refs = Object.values(health.stageStats).flatMap((stat) => stat.waitingDecisionRefs);
      const ids = refs.join(',');
      for (const id of ['GOV-398', 'GOV-83', 'GOV-104']) {{
        if (!ids.includes(id)) fail(`等你动作 refs 应含 ${{id}}, got ${{ids}}`);
      }}
      if (ids.includes('KAN-209') || ids.includes('KAN-108') || ids.includes('GOV-11') || ids.includes('SKL-21')) {{
        fail(`等你动作 refs 混入非 Owner 债卡: ${{ids}}`);
      }}
      // ownerActionTasks 列表与计数同源（治理页顶段直接消费）。
      const listIds = (model.ownerActionTasks || []).map((t) => t.task_id).sort().join(',');
      if (listIds !== 'GOV-104,GOV-398,GOV-83') fail(`ownerActionTasks 应为 GOV-104/398/83, got ${{listIds}}`);
      console.log('dual entry counts identical ok');
    """
    result = _run_node(script)
    assert 'dual entry counts identical ok' in result.stdout
