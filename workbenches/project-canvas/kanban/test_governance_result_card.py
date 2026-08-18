#!/usr/bin/env python3
"""Tests for the sanitized weekly governance result-card adapter."""

import importlib.util
from pathlib import Path
import pytest


_MODULE = Path(__file__).resolve().parents[1] / 'governance' / 'governance_result_card.py'
if not _MODULE.is_file():
    pytest.skip("missing optional source path: governance/governance_result_card.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location('governance_result_card', _MODULE)
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)


def test_projection_contains_counts_but_no_evidence_paths():
    projection = card.build_projection({
        'generated_at': '2026-07-14T09:00:00+08:00',
        'metrics': {'dirty_repos': 3, 'tracked_secret_repos': 1},
        'previous_metrics': {'dirty_repos': 2, 'tracked_secret_repos': 1},
        'paths': ['/Users/example/workspace/private/.env'],
    })

    assert projection['source'] == 'governance-scan/2026-W29'
    assert projection['status'] == 'todo'
    assert projection['positive_deltas'] == {'dirty_repos': 1}
    assert '/Users/' not in projection['body']
    assert '.env' not in projection['body']


def test_no_positive_delta_is_backstage_done_projection():
    projection = card.build_projection({
        'generated_at': '2026-07-14T09:00:00+08:00',
        'metrics': {'dirty_repos': 2},
        'previous_metrics': {'dirty_repos': 2},
    })

    assert projection['status'] == 'done'
    assert projection['positive_deltas'] == {}
    assert '不是 Owner 审批闸' in projection['body']


def test_upsert_reuses_one_weekly_card_and_second_call_is_noop():
    docs = []
    bodies = {}

    def create_document(project, title, assignee, priority, body, **kwargs):
        path = 'project/个人调度/GOV-1_weekly.md'
        docs.append({'path': path, 'task_id': 'GOV-1', 'title': title, 'status': 'todo'})
        bodies[path] = body
        return True, path, 'GOV-1'

    def update_frontmatter(path, field, value, **kwargs):
        next(item for item in docs if item['path'] == path)[field] = value
        return True, 'OK'

    def update_body(path, body):
        bodies[path] = body
        return True, 'OK'

    deps = {
        'scan_all': lambda: [dict(item) for item in docs],
        'create_document': create_document,
        'update_frontmatter_field': update_frontmatter,
        'update_task_body': update_body,
        'read_task_body': lambda doc: bodies.get(doc['path'], ''),
    }
    payload = {
        'generated_at': '2026-07-14T09:00:00+08:00',
        'metrics': {'dirty_repos': 1},
        'previous_metrics': {'dirty_repos': 0},
    }

    first, first_status = card.upsert_weekly_card(deps, payload)
    second, second_status = card.upsert_weekly_card(deps, payload)

    assert first_status == second_status == 200
    assert first['created'] is True
    assert second['created'] is False
    assert second['changed'] == []
    assert len(docs) == 1
    assert docs[0]['human_gate'] == 'false'
    assert docs[0]['attention_scope'] == 'backstage'
