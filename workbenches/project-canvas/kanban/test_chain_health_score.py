#!/usr/bin/env python3
"""Frontend chain health score tests."""

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_RENDER_BOARD = _HERE / 'static' / 'kanban' / 'modules' / 'render-board.js'


def test_frontend_chain_health_score_four_signals_and_routing():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ buildChainStageBuckets, chainHealthScore, normalizeFrontendChains }} from {str(_RENDER_BOARD.as_uri())!r};

      const chain = normalizeFrontendChains([{{
        key: 'gov',
        title: '治理链',
        stages: [
          {{ key: 'gov/sense', title: '感知', responsibility: 'ai-owned' }},
          {{ key: 'gov/triage', title: '判断', responsibility: 'ai-owned' }},
          {{ key: 'gov/fix', title: '整改', responsibility: 'shared' }},
          {{ key: 'gov/accept', title: '验收', responsibility: 'pi-gated' }},
        ],
      }}])[0];
      const now = Date.parse('2026-06-18T00:00:00Z');

      const blocked = chainHealthScore(chain, [{{
        task_id: 'GOV-BLOCKED',
        status: 'blocked',
        stage: 'gov/fix',
        status_changed_at: '2026-06-18',
      }}], now, 'Owner');
      if (blocked.tier !== 'bad') throw new Error(`blocked task should force bad tier, got ${{blocked.tier}}`);
      if (blocked.signals.blocked !== 1) throw new Error(`expected one blocked signal, got ${{blocked.signals.blocked}}`);
      if (blocked.bottleneck.stageKey !== 'gov/fix' || blocked.bottleneck.reason !== '卡死 1') {{
        throw new Error(`blocked bottleneck mismatch: ${{JSON.stringify(blocked.bottleneck)}}`);
      }}

      // KAN-999「等 Owner 动作」一本账：等你 = pi-gated ∧ todo/review 才计数罚分；
      // review ∧ ai-owned = AI 代收中（弱信号不罚分）；无 responsibility 的 review 卡不再一刀切计成 Owner 债。
      const waiting = chainHealthScore(chain, [
        {{ task_id: 'GOV-PI', status: 'todo', responsibility: 'pi-gated', stage: 'gov/accept', status_changed_at: '2026-06-18' }},
        {{ task_id: 'GOV-PI-REVIEW', status: 'review', responsibility: 'pi-gated', stage: 'gov/accept', status_changed_at: '2026-06-18' }},
        {{ task_id: 'GOV-REVIEW', status: 'review', assignee: 'Owner', stage: 'gov/fix', status_changed_at: '2026-06-18' }},
        {{ task_id: 'GOV-PROXY', status: 'review', responsibility: 'ai-owned', stage: 'gov/fix', status_changed_at: '2026-06-18' }},
        {{ task_id: 'GOV-GATE', status: 'in-progress', responsibility: 'pi-gated', stage: 'gov/fix', status_changed_at: '2026-06-18' }},
      ], now, 'Owner');
      if (waiting.signals.waitingDecision !== 2) throw new Error(`expected two owner-action cards (pi-gated todo+review), got ${{waiting.signals.waitingDecision}}`);
      if (waiting.signals.aiProxyReview !== 1) throw new Error(`expected one ai-proxy review, got ${{waiting.signals.aiProxyReview}}`);
      if (waiting.penalties.waitingDecision !== 16) throw new Error(`waiting penalty should only count owner-action cards (2*8), got ${{waiting.penalties.waitingDecision}}`);
      if (!String(waiting.bottleneck.reason).startsWith('等你')) {{
        throw new Error(`waiting bottleneck should say 等你, got ${{waiting.bottleneck.reason}}`);
      }}

      const stalled = chainHealthScore(chain, [{{
        task_id: 'GOV-STALLED',
        status: 'in-progress',
        stage: 'gov/fix',
        status_changed_at: '2026-05-20',
      }}], now, 'Owner');
      if (stalled.signals.stalled !== 1) throw new Error(`expected one true stalled task, got ${{stalled.signals.stalled}}`);
      if (stalled.penalties.stalled <= 0) throw new Error('true stalled task should deduct score once status_changed_at exists');

      const inert = chainHealthScore(chain, [{{
        task_id: 'GOV-OLD-UPDATED',
        status: 'in-progress',
        stage: 'gov/fix',
        updated: '2026-05-20',
      }}], now, 'Owner');
      if (inert.signals.stalled !== 0 || inert.score !== 100) {{
        throw new Error(`missing status_changed_at must be inert, got ${{JSON.stringify(inert.signals)}} score=${{inert.score}}`);
      }}
      const inferred = chainHealthScore(chain, [{{
        task_id: 'GOV-INFERRED',
        status: 'in-progress',
        stage: 'gov/fix',
        status_changed_at: '2026-05-20',
        status_changed_at_inferred: true,
      }}], now, 'Owner');
      if (inferred.signals.stalled !== 0 || inferred.score !== 100) {{
        throw new Error(`inferred status_changed_at must be inert, got ${{JSON.stringify(inferred.signals)}} score=${{inferred.score}}`);
      }}

      const stackedTasks = Array.from({{ length: 8 }}, (_, idx) => ({{
        task_id: `GOV-S${{idx}}`,
        status: 'todo',
        stage: 'governance/triage',
        status_changed_at: '2026-06-18',
      }}));
      const stacked = chainHealthScore(chain, stackedTasks, now, 'Owner');
      if (stacked.bottleneck.stageKey !== 'gov/triage') throw new Error(`stacked bottleneck should map to gov/triage, got ${{stacked.bottleneck.stageKey}}`);
      if (stacked.bottleneck.stackOver !== 2) throw new Error(`expected stack over 2, got ${{stacked.bottleneck.stackOver}}`);
      if (stacked.signals.stackOver !== 2) throw new Error(`expected stack signal 2, got ${{stacked.signals.stackOver}}`);

      const clean = chainHealthScore(chain, [
        {{ task_id: 'GOV-OK', status: 'todo', stage: 'gov/sense', status_changed_at: '2026-06-18' }},
        {{ task_id: 'GOV-DONE', status: 'done', stage: 'gov/fix', status_changed_at: '2026-06-01' }},
      ], now, 'Owner');
      if (clean.score !== 100 || clean.tier !== 'good') {{
        throw new Error(`clean chain should be 100/good, got ${{clean.score}}/${{clean.tier}}`);
      }}

      // KAN-999 链路由只认显式字段：stage.kw 关键词兜底已删除；显式治理卡无细分 stage 时
      // 用确定性映射（review→gov/accept 其余→gov/triage）；未标显式归属的卡不入任何链。
      const routed = normalizeFrontendChains([
        {{ key: 'km', stages: [{{ key: 'km/intake_dispatch', title: '入口', kw: ['候选'] }}] }},
        {{ key: 'team', stages: [{{ key: 'team/curate', title: '策展' }}] }},
        {{ key: 'gov', stages: [{{ key: 'gov/triage', title: '判断' }}, {{ key: 'gov/fix', title: '整改', kw: ['治理'] }}, {{ key: 'gov/accept', title: '验收' }}] }},
      ]);
      const buckets = buildChainStageBuckets([
        {{
          task_id: 'GOV-13',
          title: 'skill候选侦察scheduled-agent-parked',
          task_family: 'governance',
          status: 'todo',
          project: '个人调度',
        }},
        {{
          task_id: 'GOV-14',
          title: '治理验收中的卡',
          task_family: 'governance',
          status: 'review',
          project: '个人调度',
        }},
        {{
          task_id: 'CHN-7',
          title: '团队群 Chat 定期爬取',
          status: 'blocked',
          stage: 'team/ingest',
        }},
        {{
          task_id: 'KMO-77',
          title: '候选文献筛选（无显式 stage 不入链）',
          task_family: 'knowledge',
          status: 'todo',
        }},
      ], routed);
      if ((buckets.byChain.km['km/intake_dispatch'] || []).length !== 0) {{
        throw new Error('kw keyword fallback must be retired: no card may enter km without explicit stage');
      }}
      if ((buckets.byChain.gov['gov/triage'] || []).length !== 1) {{
        throw new Error('explicit governance todo card without sub-stage should map deterministically into gov/triage');
      }}
      if ((buckets.byChain.gov['gov/accept'] || []).length !== 1) {{
        throw new Error('explicit governance review card without sub-stage should map deterministically into gov/accept');
      }}
      if ((buckets.byChain.gov['gov/fix'] || []).length !== 0) {{
        throw new Error('gov/fix keyword routing must be retired');
      }}
      if ((buckets.byChain.team['team/curate'] || []).length !== 1) {{
        throw new Error('legacy team/ingest should map into team/curate');
      }}
      if (!buckets.unassigned.some((task) => task.task_id === 'KMO-77')) {{
        throw new Error('non-governance card without explicit stage should stay unassigned');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)
