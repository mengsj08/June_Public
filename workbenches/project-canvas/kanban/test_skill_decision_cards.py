import importlib.util
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('scan_docs_skill_cards', HERE / 'scan-docs.py')
scan = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan)

def make_card(root, revision=1, status='done'):
    rel = 'project/个人调度/SKL-1_decision.md'
    path = root / rel; path.parent.mkdir(parents=True)
    path.write_text(f'''---
title: 决策
task_id: SKL-1
task_family: skill
created: 2026-07-12
updated: 2026-07-12
assignee: Owner
priority: P1
status: {status}
proposal_id: p1
proposal_revision: {revision}
evidence_hash: h{revision}
tags: []
---

## 执行结果

''', encoding='utf-8')
    return rel

def doc(rel, revision=1, status='done'):
    return {'path':rel, 'proposal_id':'p1', 'proposal_revision':str(revision), 'status':status}

def test_revision_reopens_same_real_card_and_auto_close_closes_it(tmp_path):
    rel = make_card(tmp_path)
    with patch.object(scan, 'REPO_ROOT', tmp_path), patch.object(scan, 'scan_all', return_value=[doc(rel)]):
        scan.sync_skill_decision_cards({'needs_decision':[{
            'id':'p1', 'proposal_revision':2, 'evidence_hash':'h2',
            'question':'重新登录后批准', 'next_action':'Owner 重新登录后点批准',
        }], 'invocations':[]})
    raw = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'proposal_revision: 2' in raw and 'status: review' in raw
    assert 'Owner 唯一需做动作：Owner 重新登录后点批准' in raw
    assert len(list((tmp_path / 'project/个人调度').glob('*.md'))) == 1
    with patch.object(scan, 'REPO_ROOT', tmp_path), patch.object(scan, 'scan_all', return_value=[doc(rel, 2, 'review')]):
        scan.sync_skill_decision_cards({'needs_decision':[], 'auto_close':[{'proposal_id':'p1'}]})
    raw = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'status: done' in raw and 'decision_state: auto_closed' in raw

def test_stale_and_failed_results_persist_to_visible_ledger(tmp_path):
    rel = make_card(tmp_path, status='review')
    invocation = {'params':{'proposalId':'p1','proposalRevision':1}}
    with patch.object(scan, 'REPO_ROOT', tmp_path), patch.object(scan, 'scan_all', return_value=[doc(rel, 1, 'review')]):
        scan.persist_skill_invocation_result(invocation, {
            'outcome':'stale', 'message':'revision stale；请刷新后重新选择',
        })
    raw = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'status: review' in raw and 'decision_state: stale' in raw
    assert '最近执行结果：**stale**' in raw
    assert 'next_action: revision stale；请刷新后重新选择' in raw

def test_subjective_cycle_moves_same_card_backstage_then_reopens(tmp_path):
    rel = make_card(tmp_path, revision=1, status='review')
    with patch.object(scan, 'REPO_ROOT', tmp_path), patch.object(
        scan, 'scan_all', return_value=[doc(rel, 1, 'review')]
    ):
        scan.sync_skill_decision_cards({
            'needs_decision': [],
            'decision_card_updates': [{
                'proposal_id':'p1', 'proposal_revision':2, 'evidence_hash':'h2',
                'decision_phase':'executing', 'attention_state':'backstage',
                'next_action':'按已锁定 brief 生成首例', 'review_url':'http://board/#hitl-cycle/p1',
            }],
        })
    raw = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'status: doing' in raw
    assert 'human_gate: false' in raw
    assert 'attention_scope: backstage' in raw
    assert 'decision_phase: executing' in raw
    assert '无需 Owner 动作' in raw

    with patch.object(scan, 'REPO_ROOT', tmp_path), patch.object(
        scan, 'scan_all', return_value=[doc(rel, 2, 'doing')]
    ):
        scan.sync_skill_decision_cards({'needs_decision':[{
            'id':'p1', 'proposal_revision':3, 'evidence_hash':'h3',
            'decision_phase':'artifact-review-pending',
            'question':'直接看首例', 'next_action':'打开页面直接判断',
            'review_url':'http://board/#hitl-cycle/p1',
        }], 'invocations':[]})
    raw = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'status: review' in raw
    assert 'human_gate: true' in raw
    assert 'attention_scope: owner' in raw
    assert 'decision_phase: artifact-review-pending' in raw
    assert '直接查看：http://board/#hitl-cycle/p1' in raw

def test_accepted_invocation_leaves_owner_inbox_without_closing_card(tmp_path):
    rel = make_card(tmp_path, status='review')
    invocation = {'params':{'proposalId':'p1','proposalRevision':1}}
    with patch.object(scan, 'REPO_ROOT', tmp_path), patch.object(
        scan, 'scan_all', return_value=[doc(rel, 1, 'review')]
    ):
        scan.persist_skill_invocation_result(invocation, {
            'outcome':'accepted', 'message':'已接收，等待原生执行',
        })
    raw = (tmp_path / rel).read_text(encoding='utf-8')
    assert 'status: doing' in raw
    assert 'human_gate: false' in raw
    assert 'attention_scope: backstage' in raw
    assert 'decision_state: accepted' in raw

def test_backstage_update_materializes_card_when_initial_snapshot_was_missed(tmp_path):
    proposal_id = 'skill-board/hitl-cycle/missed-initial'
    with patch.object(scan, 'REPO_ROOT', tmp_path), patch.object(scan, 'scan_all', return_value=[]):
        scan.sync_skill_decision_cards({
            'needs_decision': [],
            'decision_card_updates': [{
                'proposal_id': proposal_id,
                'proposal_revision': 2,
                'evidence_hash': 'h2',
                'decision_phase': 'executing',
                'attention_state': 'backstage',
                'next_action': '按已锁定 brief 生成首例',
                'review_url': 'http://board/#hitl-cycle/missed-initial',
                'skill_name': 'Example Motion Skill',
            }],
        })
    cards = list((tmp_path / 'project/个人调度').glob('*.md'))
    assert len(cards) == 1
    raw = cards[0].read_text(encoding='utf-8')
    assert f'proposal_id: {proposal_id}' in raw
    assert 'status: doing' in raw
    assert 'human_gate: false' in raw
    assert 'attention_scope: backstage' in raw
    assert 'decision_phase: executing' in raw
