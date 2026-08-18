#!/usr/bin/env python3
"""Tests for read-only team kanban feeder and digest generation."""

import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest


_HERE = Path(__file__).resolve().parent
if not (_HERE.parent / 'governance' / 'outbound_gate.py').is_file():
    pytest.skip('missing optional source path: governance/outbound_gate.py', allow_module_level=True)
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _config():
    return {
        'team_kanban_url': 'https://kb.example.test/',
        'team_sync': {
            'enabled': True,
            'target_user': 'Owner',
            'target_project': '个人调度',
            'token_header': 'X-Kanban-Token',
            'digest_path': 'shared/toolkit/kanban/.team-kanban-digest.json',
            'snapshot_path': 'shared/toolkit/kanban/.team-kanban-snapshot.json',
            'due_soon_days': 3,
            'stale_days': 3,
        },
    }


def _remote_payload():
    return {
        'tasks': [
            {
                'task_id': 'TK-1',
                'title': 'Assigned to Owner',
                'status': 'todo',
                'assignee': 'Owner',
                'due_date': '2026-06-13',
                'url': '/tasks/TK-1',
                'body': 'REMOTE BODY MUST NOT BE COPIED',
            },
            {
                'task_id': 'TK-2',
                'title': 'Created by Owner',
                'status': 'review',
                'assignee': 'Pat',
                'created_by': 'Owner',
                'due_date': '2026-06-30',
                'url': 'tasks/TK-2',
            },
            {
                'task_id': 'TK-3',
                'title': 'Other teammate',
                'status': 'in-progress',
                'assignee': 'Pat',
                'created_by': 'Pat',
            },
            {
                'task_id': 'TK-4',
                'title': 'Already done',
                'status': 'done',
                'assignee': 'Owner',
            },
        ],
    }


def _write_local_task(repo_root, rel_path, *, title, task_id, assignee, status='todo', due_date='2026-06-13'):
    path = repo_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
title: {title}
task_id: {task_id}
created: 2026-06-12
updated: 2026-06-12
assignee: {assignee}
priority: medium
status: {status}
due_date: {due_date}
tags: []
---

## 要做什么

本地团队仓库任务。
""", encoding='utf-8')
    return path


def _write_personal_task(repo_root, rel_path='project/个人调度/source.md', priority='high'):
    path = repo_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
title: Source Personal Task
task_id: XXX-30
workdir: project/个人调度/
created: 2026-06-12
updated: 2026-06-12
assignee: Owner
priority: {priority}
status: todo
tags: [team]
kind: task
domain: team
---

## 要做什么

把个人任务交接给团队。
""", encoding='utf-8')
    return path


def _local_config(tmp_path):
    cfg = _config()
    cfg['team_sync'].update({
        'source': 'local_repo',
        'local_repo_path': str(tmp_path / 'team-workspace'),
        'local_scan_dirs': ['project'],
    })
    return cfg


def _write_handoff_rules(board_root, team_repo):
    contract = board_root / 'shared' / 'toolkit' / 'kanban' / 'TEAM_HANDOFF_CONTRACT.md'
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text('# Contract\n\n> doc_type: rule · last_verified: 2026-06-13 · owner: Owner\n', encoding='utf-8')
    team_repo.mkdir(parents=True, exist_ok=True)
    (team_repo / 'CLAUDE.md').write_text('members/<assignee>/inbox symlink should exist\n', encoding='utf-8')
    (team_repo / 'README.md').write_text('project cards use YAML frontmatter\n', encoding='utf-8')


def _init_git_repo(repo_root):
    subprocess.run(['git', '-C', str(repo_root), 'init'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(['git', '-C', str(repo_root), 'branch', '-M', 'main'], check=True)
    subprocess.run(['git', '-C', str(repo_root), 'config', 'user.email', 'test@example.test'], check=True)
    subprocess.run(['git', '-C', str(repo_root), 'config', 'user.name', 'Test User'], check=True)
    subprocess.run(['git', '-C', str(repo_root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo_root), 'commit', '-m', 'initial'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _attach_bare_remote(repo_root, remote_path):
    subprocess.run(['git', 'init', '--bare', str(remote_path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(['git', '-C', str(repo_root), 'remote', 'add', 'origin', str(remote_path)], check=True)
    subprocess.run(['git', '-C', str(repo_root), 'push', '-u', 'origin', 'main'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _remote_show(remote_path, rel_path):
    proc = subprocess.run(
        ['git', '--git-dir', str(remote_path), 'show', f'main:{rel_path}'],
        capture_output=True,
        text=True,
    )
    return proc


def test_team_sync_manager_runs_once_when_enabled():
    calls = []
    cfg = _config()
    cfg['team_sync']['auto_sync'] = True
    cfg['team_sync']['interval_seconds'] = 30

    manager = scan_mod.TeamKanbanSyncManager(
        config=cfg,
        sync_fn=lambda config: calls.append(config) or {'ok': True},
    )
    result = manager.run_once()

    assert result == {'ok': True}
    assert calls == [cfg]
    status = manager.snapshot()
    assert status['enabled'] is True
    assert status['running'] is False
    assert status['last_result'] == {'ok': True}


def test_team_sync_manager_skips_when_auto_sync_disabled():
    cfg = _config()
    cfg['team_sync']['auto_sync'] = False
    manager = scan_mod.TeamKanbanSyncManager(config=cfg, sync_fn=lambda _config: {'ok': True})

    result = manager.run_once()

    assert result['skipped'] is True
    assert result['reason'] == 'disabled'


def test_team_kanban_sync_reads_local_repo_without_remote_credentials(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (board_root / 'project').mkdir(parents=True)
    (board_root / 'shared' / 'toolkit' / 'kanban').mkdir(parents=True)
    team_repo.mkdir(parents=True)
    (team_repo / '.kanban.config.json').write_text(json.dumps({
        'scan_dirs': ['project'],
        'skip_patterns': ['README.md'],
    }), encoding='utf-8')
    _write_local_task(team_repo, 'project/Alpha/TK-LOCAL-1.md', title='Local Owner task', task_id='TLK-1', assignee='Owner')
    _write_local_task(team_repo, 'project/Alpha/TK-LOCAL-2.md', title='Other teammate', task_id='TLK-2', assignee='Pat')
    _write_local_task(team_repo, 'project/Alpha/TK-LOCAL-3.md', title='Done Owner task', task_id='TLK-3', assignee='Owner', status='done')
    (team_repo / 'project' / 'Alpha' / 'README.md').write_text('ignored', encoding='utf-8')
    cfg = _local_config(tmp_path)
    now = datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc)

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod, 'STATE_FILE', board_root / '.kanban-state.json'), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        remote_data, fetch_status = scan_mod.fetch_team_kanban_data(cfg)
        assert fetch_status['ok'] is True
        assert fetch_status['source'] == 'local_repo'
        assert len(remote_data['tasks']) == 3

        result = scan_mod.sync_team_kanban(config=cfg)
        assert result['ok'] is True
        assert result['selected'] == 1
        docs = scan_mod.scan_all()
        pointers = [doc for doc in docs if str(doc.get('source', '')).startswith('team-kanban/')]
        assert len(pointers) == 1
        assert pointers[0]['title'] == 'Local Owner task'
        assert pointers[0]['status'] == 'todo'
        assert pointers[0]['team_path'] == 'project/Alpha/TK-LOCAL-1.md'

        digest, _snapshot = scan_mod.build_team_kanban_digest(
            scan_mod.select_team_kanban_tasks(remote_data, config=cfg),
            previous_snapshot={'tasks': {}},
            config=cfg,
            now=now,
        )
        assert digest['stats']['selected'] == 1
        assert digest['entries'][0]['title'] == 'Local Owner task'
        assert digest['entries'][0]['team_path'] == 'project/Alpha/TK-LOCAL-1.md'


def test_team_pointer_path_is_real_team_path_not_internal_source_id():
    cfg = _config()
    record = scan_mod.normalize_team_kanban_task({
        'task_id': 'TK-URL-1',
        'title': 'GitHub linked team card',
        'status': 'todo',
        'assignee': 'Owner',
        'remote_url': 'https://github.com/example-org/team-workspace/blob/main/project/本地kanban/card.md',
    }, config=cfg)

    assert record['source'] == 'team-kanban/TK-URL-1'
    assert record['team_path'] == 'project/本地kanban/card.md'
    assert record['path'] == 'project/本地kanban/card.md'


def test_team_kanban_digest_can_be_built_live_from_local_repo(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (board_root / 'shared' / 'toolkit' / 'kanban').mkdir(parents=True)
    _write_local_task(team_repo, 'project/Alpha/TK-LOCAL-1.md', title='Live local task', task_id='TLK-1', assignee='Owner')
    cfg = _local_config(tmp_path)

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod, 'STATE_FILE', board_root / '.kanban-state.json'), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        digest = scan_mod.load_team_kanban_digest(cfg)

    assert digest['ok'] is True
    assert digest['source'] == 'team-kanban-local'
    assert digest['is_stale'] is False
    assert digest['stats']['selected'] == 1
    assert digest['entries'][0]['title'] == 'Live local task'


def test_team_kanban_digest_marks_disabled_control_plane_stale(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    state_path = tmp_path / 'shape-last-run.json'
    manifest_path = tmp_path / 'shape-task.json'
    (board_root / 'shared' / 'toolkit' / 'kanban').mkdir(parents=True)
    _write_local_task(team_repo, 'project/Alpha/TK-LOCAL-1.md', title='Live local task', task_id='TLK-1', assignee='Owner')
    state_path.write_text(json.dumps({
        'ok': True,
        'status': 'success',
        'finished_at': '2026-06-12T09:00:00+00:00',
    }), encoding='utf-8')
    manifest_path.write_text(json.dumps({'status': 'DISABLED'}), encoding='utf-8')
    cfg = _local_config(tmp_path)
    cfg['team_sync']['sync_state_path'] = str(state_path)
    cfg['team_sync']['sync_task_manifest_path'] = str(manifest_path)

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod, 'STATE_FILE', board_root / '.kanban-state.json'), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        digest = scan_mod.load_team_kanban_digest(cfg)

    assert digest['ok'] is True
    assert digest['is_stale'] is True
    assert digest['stale_reason'] == 'task_disabled'
    assert digest['sync_status']['task_status'] == 'DISABLED'


def test_team_kanban_sync_filters_creates_digest_and_is_idempotent(tmp_path):
    (tmp_path / 'project').mkdir()
    (tmp_path / 'shared' / 'toolkit' / 'kanban').mkdir(parents=True)
    cfg = _config()
    now = datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc)

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'STATE_FILE', tmp_path / '.kanban-state.json'), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        result = scan_mod.sync_team_kanban_from_data(_remote_payload(), config=cfg, now=now)

        assert result['ok'] is True
        assert result['selected'] == 2
        assert result['created'] == 2
        assert result['updated'] == 0

        docs = scan_mod.scan_all()
        pointers = {doc['source']: doc for doc in docs if str(doc.get('source', '')).startswith('team-kanban/')}
        assert set(pointers) == {'team-kanban/TK-1', 'team-kanban/TK-2'}
        assert pointers['team-kanban/TK-1']['status'] == 'todo'
        assert pointers['team-kanban/TK-1']['domain'] == 'team'

        bodies = '\n'.join(path.read_text(encoding='utf-8') for path in (tmp_path / 'project' / '个人调度').glob('*.md'))
        assert 'REMOTE BODY MUST NOT BE COPIED' not in bodies
        assert 'https://kb.example.test/tasks/TK-1' in bodies
        assert 'https://kb.example.test/tasks/TK-2' in bodies

        digest_path = tmp_path / 'shared' / 'toolkit' / 'kanban' / '.team-kanban-digest.json'
        digest = json.loads(digest_path.read_text(encoding='utf-8'))
        types = [entry['type'] for entry in digest['entries']]
        assert types.count('new_card') == 2
        assert 'due_soon' in types

        second = scan_mod.sync_team_kanban_from_data(_remote_payload(), config=cfg, now=now)
        assert second['created'] == 0
        assert second['updated'] == 2
        docs_after_second = scan_mod.scan_all()
        pointers_after_second = [doc for doc in docs_after_second if str(doc.get('source', '')).startswith('team-kanban/')]
        assert len(pointers_after_second) == 2

        changed = _remote_payload()
        changed['tasks'][0]['status'] = 'in-progress'
        changed['tasks'][1]['assignee'] = 'Owner'
        third = scan_mod.sync_team_kanban_from_data(changed, config=cfg, now=now)
        assert third['created'] == 0
        assert third['updated'] == 2
        digest = json.loads(digest_path.read_text(encoding='utf-8'))
        changed_types = [entry['type'] for entry in digest['entries']]
        assert 'status_changed' in changed_types
        assert 'assignee_changed' in changed_types
        updated_docs = {doc['source']: doc for doc in scan_mod.scan_all() if str(doc.get('source', '')).startswith('team-kanban/')}
        assert updated_docs['team-kanban/TK-1']['status'] == 'in-progress'
        assert updated_docs['team-kanban/TK-2']['assignee'] == 'Owner'


def test_team_pointer_project_is_separate_from_handoff_target_project(tmp_path):
    (tmp_path / 'project').mkdir()
    (tmp_path / 'shared' / 'toolkit' / 'kanban').mkdir(parents=True)
    cfg = _config()
    cfg['team_sync']['target_project'] = '本地kanban'
    cfg['team_sync']['pointer_project'] = '个人调度'
    now = datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc)

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'STATE_FILE', tmp_path / '.kanban-state.json'), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        result = scan_mod.sync_team_kanban_from_data(_remote_payload(), config=cfg, now=now)

    assert result['ok'] is True
    assert result['created'] == 2
    assert list((tmp_path / 'project' / '个人调度').glob('*.md'))
    assert not (tmp_path / 'project' / '本地kanban').exists()


def test_team_digest_notifications_cover_four_event_types_and_dedupe(tmp_path):
    cfg = _config()
    cfg['feishu'] = {
        'app_id': 'app',
        'app_secret': 'secret',
        'member_open_ids': {'Owner': 'ou_owner'},
    }
    cfg['team_sync']['notify_state_path'] = 'shared/toolkit/kanban/.team-kanban-notify-state.json'
    digest = {
        'ok': True,
        'is_stale': True,
        'stale_days': 3,
        'sync_status': {'reason': 'task_disabled', 'task_status': 'DISABLED', 'last_checked_at': ''},
        'entries': [
            {'type': 'new_card', 'remote_task_id': 'TK-1', 'title': 'New', 'assignee': 'Owner', 'remote_url': 'https://kb/TK-1'},
            {'type': 'due_soon', 'remote_task_id': 'TK-2', 'title': 'Due', 'assignee': 'Owner', 'due_date': '2026-06-13'},
            {'type': 'status_changed', 'remote_task_id': 'TK-3', 'title': 'Handoff', 'assignee': 'Pat',
             'source_ref': 'personal-kanban/XXX-30', 'from_status': 'todo', 'to_status': 'review'},
        ],
    }

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod.feishu_notify, 'notify_member_event', return_value=None) as notify:
        first = scan_mod.notify_team_digest_events(digest, config=cfg)
        second = scan_mod.notify_team_digest_events(digest, config=cfg)

    assert first['sent'] == 4
    assert notify.call_count == 4
    assert second['sent'] == 0
    event_types = [call.args[1] for call in notify.call_args_list]
    assert event_types == ['sync_stale', 'team_assigned', 'team_due_soon', 'handoff_status_changed']


def test_team_feishu_smoke_skips_without_credentials(tmp_path):
    cfg = _config()
    cfg['team_sync']['notify_state_path'] = 'shared/toolkit/kanban/.team-kanban-notify-state.json'

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        result = scan_mod.test_team_feishu_notifications(cfg)

    assert result['skipped'] is True
    assert result['reason'] == 'feishu_disabled'
    assert result['expected_events'] == [
        'sync_stale',
        'team_assigned',
        'team_due_soon',
        'handoff_status_changed',
    ]


def test_team_feishu_smoke_sends_four_events_even_after_prior_dedupe(tmp_path):
    cfg = _config()
    cfg['feishu'] = {
        'app_id': 'app',
        'app_secret': 'secret',
        'member_open_ids': {'Owner': 'ou_owner'},
    }
    cfg['team_sync']['notify_state_path'] = 'shared/toolkit/kanban/.team-kanban-notify-state.json'
    state_path = tmp_path / 'shared' / 'toolkit' / 'kanban' / '.team-kanban-notify-state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({'sent': {'sync_stale:team-sync': '2026-06-12T09:00:00+00:00'}}), encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod.feishu_notify, 'notify_member_event', return_value=None) as notify:
        result = scan_mod.test_team_feishu_notifications(cfg)

    assert result['sent'] == 4
    assert notify.call_count == 4
    event_types = [call.args[1] for call in notify.call_args_list]
    assert event_types == ['sync_stale', 'team_assigned', 'team_due_soon', 'handoff_status_changed']


def test_handoff_task_to_team_writes_team_card_and_backfills_source(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''
    cfg['feishu'] = {
        'app_id': 'app',
        'app_secret': 'secret',
        'member_open_ids': {'Pat': 'ou_pat'},
    }

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod, '_team_repo_write_guard', return_value=(True, '', {'is_stale': False})), \
            patch.object(scan_mod.feishu_notify, 'notify_member_event', return_value=None):
        result, status = scan_mod.handoff_task_to_team('project/个人调度/source.md', 'Alpha', 'Pat', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'written'
    team_card = team_repo / result['team_path']
    content = team_card.read_text(encoding='utf-8')
    frontmatter = content.split('---', 2)[1]
    assert 'task_id:' not in frontmatter
    assert 'source: personal-kanban/XXX-30' in content
    assert (team_repo / result['assignee_inbox_symlink']).is_symlink()
    source = (board_root / 'project' / '个人调度' / 'source.md').read_text(encoding='utf-8')
    assert f"promoted_to: team-workspace/{result['team_path']}" in source
    assert 'next_action: handoff-team' in source


def test_handoff_task_to_team_publishes_scoped_git_commit_when_enabled(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    remote_repo = tmp_path / 'team-workspace.git'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    (team_repo / 'project' / 'Alpha' / '.gitkeep').write_text('', encoding='utf-8')
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    _attach_bare_remote(team_repo, remote_repo)
    (team_repo / 'CLAUDE.md').write_text('team rules\nlocal user note\n', encoding='utf-8')
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync'].update({
        'local_repo_path': str(team_repo),
        'sync_state_path': '',
        'handoff_publish_enabled': True,
        'handoff_publish_worktree_path': 'shared/toolkit/kanban/.team-handoff-publish/team-workspace',
        'handoff_publish_github_base_url': 'https://github.com/example-org/team-workspace',
    })
    cfg['feishu'] = {
        'app_id': 'app',
        'app_secret': 'secret',
        'member_open_ids': {'Pat': 'ou_pat'},
    }

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod.feishu_notify, 'notify_member_event', return_value=None) as notify:
        result, status = scan_mod.handoff_task_to_team('project/个人调度/source.md', 'Alpha', 'Pat', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'pushed'
    assert result['publish']['commit']
    assert result['remote_url'].startswith('https://github.com/example-org/team-workspace/blob/main/project/Alpha/')
    assert _remote_show(remote_repo, result['team_path']).returncode == 0
    assert (team_repo / result['team_path']).exists() is False
    assert 'CLAUDE.md' in subprocess.run(
        ['git', '-C', str(team_repo), 'status', '--porcelain'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    source = (board_root / 'project' / '个人调度' / 'source.md').read_text(encoding='utf-8')
    assert 'team_handoff_status: pushed' in source
    assert 'next_action: handoff-team-published' in source
    assert result['pointer_sync']['ok'] is True
    assert result['pointer_sync']['created'] == 1
    pointer_path = board_root / result['pointer_sync']['created_paths'][0]
    pointer_text = pointer_path.read_text(encoding='utf-8')
    assert 'source: team-kanban/' in pointer_text
    assert f"remote_url: {result['remote_url']}" in pointer_text
    assert f"team_path: {result['team_path']}" in pointer_text
    assert f"- 团队卡位置：{result['team_path']}" in pointer_text
    snapshot_path = board_root / result['pointer_sync']['snapshot_path']
    assert snapshot_path.exists()
    notify.assert_called_once()
    assert notify.call_args.kwargs['url'] == result['remote_url']


def test_handoff_task_to_team_publishes_unicode_project_path_when_enabled(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    remote_repo = tmp_path / 'team-workspace.git'
    (team_repo / 'project' / '本地kanban').mkdir(parents=True)
    (team_repo / 'project' / '本地kanban' / '.gitkeep').write_text('', encoding='utf-8')
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    _attach_bare_remote(team_repo, remote_repo)
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync'].update({
        'local_repo_path': str(team_repo),
        'sync_state_path': '',
        'handoff_publish_enabled': True,
        'handoff_publish_worktree_path': 'shared/toolkit/kanban/.team-handoff-publish/team-workspace',
        'handoff_publish_github_base_url': 'https://github.com/example-org/team-workspace',
    })

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod.feishu_notify, 'notify_member_event', return_value=None):
        result, status = scan_mod.handoff_task_to_team('project/个人调度/source.md', '本地kanban', 'Pat', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'pushed'
    assert result['publish']['commit']
    assert result['team_path'].startswith('project/本地kanban/')
    assert _remote_show(remote_repo, result['team_path']).returncode == 0
    assert '%E6%9C%AC%E5%9C%B0kanban' in result['remote_url']


def test_git_subprocess_env_imports_macos_system_proxy():
    scan_mod._GIT_PROXY_ENV_CACHE = {'loaded_at': 0, 'values': {}}
    scutil_output = """<dictionary> {
  HTTPEnable : 1
  HTTPPort : 7890
  HTTPProxy : 127.0.0.1
  HTTPSEnable : 1
  HTTPSPort : 7890
  HTTPSProxy : 127.0.0.1
}
"""
    with patch.dict(scan_mod.os.environ, {}, clear=True), \
            patch.object(
                scan_mod.PLATFORM_ADAPTER,
                'system_proxy_output',
                return_value=(True, scutil_output, ''),
            ):
        env = scan_mod._git_subprocess_env()

    assert env['GIT_TERMINAL_PROMPT'] == '0'
    assert env['HTTPS_PROXY'] == 'http://127.0.0.1:7890'
    assert env['HTTP_PROXY'] == 'http://127.0.0.1:7890'
    scan_mod._GIT_PROXY_ENV_CACHE = {'loaded_at': 0, 'values': {}}


def test_team_git_status_preserves_unicode_paths(tmp_path):
    repo = tmp_path / 'team-workspace'
    (repo / 'project' / '本地kanban').mkdir(parents=True)
    (repo / 'README.md').write_text('rules\n', encoding='utf-8')
    _init_git_repo(repo)
    rel_path = 'project/本地kanban/20260613-205754-XXX-41.md'
    (repo / rel_path).write_text('---\ntitle: 测试\n---\n', encoding='utf-8')

    rows, err = scan_mod._team_git_status(repo)

    assert err == ''
    assert {'status': '??', 'path': rel_path} in rows


def test_team_handoff_publish_checkout_handles_clone_timeout(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    cfg = _local_config(tmp_path)
    sync_cfg = cfg['team_sync']
    sync_cfg.update({
        'handoff_publish_enabled': True,
        'handoff_publish_worktree_path': 'shared/toolkit/kanban/.team-handoff-publish/team-workspace',
    })
    source_repo = tmp_path / 'team-workspace'
    (source_repo / '.git').mkdir(parents=True)

    def _raise_timeout(*args, **kwargs):
        cmd = args[0]
        if cmd[:4] == ['git', '-C', str(source_repo), 'fetch']:
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='fetch failed')
        assert cmd[:3] == ['git', 'clone', '--depth']
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get('timeout'))

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod, '_team_handoff_remote_url', return_value=('https://example.test/team.git', '')), \
            patch.object(scan_mod, '_git_subprocess_env', return_value={'GIT_TERMINAL_PROMPT': '0'}), \
            patch.object(scan_mod.subprocess, 'run', side_effect=_raise_timeout):
        checkout_path, remote_url, err = scan_mod._team_handoff_publish_checkout(sync_cfg, source_repo)

    assert checkout_path is None
    assert remote_url == 'https://example.test/team.git'
    assert err == 'git_clone_timeout'
    work_root = board_root / 'shared/toolkit/kanban/.team-handoff-publish/team-workspace'
    assert not list(work_root.glob('run-*'))


def test_handoff_task_to_team_blocks_when_remote_target_already_exists(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    remote_repo = tmp_path / 'team-workspace.git'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    (team_repo / 'project' / 'Alpha' / '.gitkeep').write_text('', encoding='utf-8')
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    _attach_bare_remote(team_repo, remote_repo)

    remote_work = tmp_path / 'remote-work'
    subprocess.run(['git', 'clone', str(remote_repo), str(remote_work)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(['git', '-C', str(remote_work), 'switch', 'main'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _write_local_task(remote_work, 'project/Alpha/existing.md', title='Remote Existing', task_id='ALP-9', assignee='Pat')
    subprocess.run(['git', '-C', str(remote_work), 'config', 'user.email', 'test@example.test'], check=True)
    subprocess.run(['git', '-C', str(remote_work), 'config', 'user.name', 'Test User'], check=True)
    subprocess.run(['git', '-C', str(remote_work), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(remote_work), 'commit', '-m', 'add remote existing'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(['git', '-C', str(remote_work), 'push', 'origin', 'main'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync'].update({
        'local_repo_path': str(team_repo),
        'sync_state_path': '',
        'handoff_draft_dir': 'shared/toolkit/kanban/.team-handoff-drafts',
        'handoff_publish_enabled': True,
        'handoff_publish_worktree_path': 'shared/toolkit/kanban/.team-handoff-publish/team-workspace',
    })

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        result, status = scan_mod.commit_team_handoff(
            'project/个人调度/source.md',
            'Alpha',
            'Owner',
            config=cfg,
            filename='existing.md',
            confirmed=True,
        )

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'publish_blocked'
    assert result['reason'] == 'publish_validation_failed'
    assert (board_root / result['draft_path']).exists()
    source = (board_root / 'project' / '个人调度' / 'source.md').read_text(encoding='utf-8')
    assert 'team_handoff_status: publish-blocked' in source
    assert 'next_action: handoff-team-publish-blocked' in source
    assert 'promoted_to:' not in source


def test_preview_team_handoff_reads_rules_and_does_not_write(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        result, status = scan_mod.preview_team_handoff('project/个人调度/source.md', 'Alpha', 'Owner', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'preview'
    assert result['can_commit'] is True
    assert not list((team_repo / 'project' / 'Alpha').glob('*.md'))
    assert not (team_repo / 'members' / 'Owner' / 'inbox').exists()
    assert any(rule['scope'] == 'personal_contract' and rule['exists'] for rule in result['rules_read'])
    assert any(step['action'] == 'create_or_verify_assignee_inbox_symlink' for step in result['write_plan'])


def test_preview_team_handoff_outbound_gate_reports_hit_without_blocking(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    task_path = _write_personal_task(board_root)
    task_text = task_path.read_text(encoding='utf-8')
    task_path.write_text(
        task_text.replace('title: Source Personal Task', 'title: Synthetic sk-FAKE000 Handoff'),
        encoding='utf-8',
    )
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        result, status = scan_mod.preview_team_handoff('project/个人调度/source.md', 'Alpha', 'Owner', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['can_commit'] is True
    assert result['outbound_gate']['report_only'] is True
    assert result['outbound_gate']['channel'] == 'team-handoff'
    assert result['outbound_gate']['verdict'] == 'hit'
    assert result['outbound_gate']['counts']['credential'] == 1
    ledger = board_root / 'shared' / 'toolkit' / 'governance' / 'OUTBOUND_LEDGER.jsonl'
    row = json.loads(ledger.read_text(encoding='utf-8').strip())
    assert row['channel'] == 'team-handoff'
    assert row['verdict'] == 'hit'
    assert 'sk-FAKE' not in json.dumps(row)
    assert not list((team_repo / 'project' / 'Alpha').glob('*.md'))


def test_team_handoff_priority_can_be_confirmed_independent_of_source_card(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    _write_personal_task(board_root, priority='medium')
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        preview, preview_status = scan_mod.preview_team_handoff(
            'project/个人调度/source.md',
            'Alpha',
            'Owner',
            config=cfg,
            priority='high',
        )
        result, status = scan_mod.commit_team_handoff(
            'project/个人调度/source.md',
            'Alpha',
            'Owner',
            config=cfg,
            filename=preview['filename'],
            confirmed=True,
            priority='high',
        )

    assert preview_status == 200
    assert preview['priority'] == 'high'
    assert 'priority: high' in preview['proposed_team_card']['content']
    assert status == 200
    assert result['ok'] is True
    assert result['priority'] == 'high'
    team_card = team_repo / result['team_path']
    assert 'priority: high' in team_card.read_text(encoding='utf-8')


def test_team_handoff_rejects_invalid_confirmed_priority(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _write_personal_task(board_root, priority='medium')
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        result, status = scan_mod.preview_team_handoff(
            'project/个人调度/source.md',
            'Alpha',
            'Owner',
            config=cfg,
            priority='urgent',
        )

    assert status == 400
    assert result['ok'] is False
    assert '团队优先级必须是' in result['error']


def test_commit_team_handoff_blocks_already_pushed_source_card(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    task_path = _write_personal_task(board_root)
    task_text = task_path.read_text(encoding='utf-8')
    task_path.write_text(task_text.replace(
        'domain: team\n---',
        '\n'.join([
            'domain: team',
            'promoted_to: team-workspace/project/Alpha/existing.md',
            'team_handoff_status: pushed',
            'team_handoff_url: https://github.com/example-org/team-workspace/blob/main/project/Alpha/existing.md',
            'next_action: handoff-team-published',
            '---',
        ]),
    ), encoding='utf-8')
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        preview, preview_status = scan_mod.preview_team_handoff('project/个人调度/source.md', 'Alpha', 'Owner', config=cfg)
        result, status = scan_mod.commit_team_handoff(
            'project/个人调度/source.md',
            'Alpha',
            'Owner',
            config=cfg,
            confirmed=True,
        )

    assert preview_status == 200
    assert preview['can_commit'] is False
    assert preview['reason'] == 'already_pushed'
    assert preview['existing_handoff']['team_path'] == 'project/Alpha/existing.md'
    assert status == 409
    assert result['ok'] is False
    assert result['existing_handoff']['status'] == 'pushed'
    assert not list((team_repo / 'project' / 'Alpha').glob('*.md'))


def test_commit_team_handoff_requires_human_confirmation(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        result, status = scan_mod.commit_team_handoff('project/个人调度/source.md', 'Alpha', 'Owner', config=cfg)

    assert status == 400
    assert result['ok'] is False
    assert not list((team_repo / 'project' / 'Alpha').glob('*.md'))


def test_handoff_task_to_team_allows_unrelated_dirty_outside_target(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _init_git_repo(team_repo)
    (team_repo / 'CLAUDE.md').write_text('team rules\nlocal note\n', encoding='utf-8')
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''
    cfg['feishu'] = {
        'transport': 'lark_cli',
        'member_open_ids': {'Owner': 'ou_owner'},
    }

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod.feishu_notify, 'notify_member_event', return_value=None) as notify:
        result, status = scan_mod.handoff_task_to_team('project/个人调度/source.md', 'Alpha', 'Owner', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'written'
    assert (team_repo / result['team_path']).exists()
    assert (team_repo / result['assignee_inbox_symlink']).is_symlink()
    assert result['sync_status']['ignored_dirty_outside_target'] == ['CLAUDE.md']
    notify.assert_called_once()


def test_handoff_task_to_team_blocks_unrelated_dirty_card_inside_target(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _write_local_task(team_repo, 'project/Alpha/unrelated.md', title='Unrelated', task_id='TK-9', assignee='Pat')
    _init_git_repo(team_repo)
    (team_repo / 'project' / 'Alpha' / 'unrelated.md').write_text("""---
title: Unrelated
task_id: TK-9
created: 2026-06-12
updated: 2026-06-13
assignee: Pat
priority: medium
status: in-progress
tags: []
---

## 要做什么

无关团队卡。
""", encoding='utf-8')
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['sync_state_path'] = ''
    cfg['team_sync']['handoff_draft_dir'] = 'shared/toolkit/kanban/.team-handoff-drafts'

    with patch.object(scan_mod, 'REPO_ROOT', board_root):
        result, status = scan_mod.handoff_task_to_team('project/个人调度/source.md', 'Alpha', 'Owner', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'draft'
    assert result['reason'] == 'team_card_not_related_to_target:project/Alpha/unrelated.md'
    assert not [path for path in (team_repo / 'project' / 'Alpha').glob('*.md') if path.name != 'unrelated.md']


def test_handoff_task_to_team_degrades_to_draft_when_guard_fails(tmp_path):
    board_root = tmp_path / 'kanban-personal'
    team_repo = tmp_path / 'team-workspace'
    (team_repo / 'project' / 'Alpha').mkdir(parents=True)
    _write_handoff_rules(board_root, team_repo)
    _write_personal_task(board_root)
    cfg = _local_config(tmp_path)
    cfg['team_sync']['local_repo_path'] = str(team_repo)
    cfg['team_sync']['handoff_draft_dir'] = 'shared/toolkit/kanban/.team-handoff-drafts'

    with patch.object(scan_mod, 'REPO_ROOT', board_root), \
            patch.object(scan_mod, '_team_repo_write_guard', return_value=(False, 'git_dirty_outside_target:CLAUDE.md', {'is_stale': False})):
        result, status = scan_mod.handoff_task_to_team('project/个人调度/source.md', 'Alpha', 'Pat', config=cfg)

    assert status == 200
    assert result['ok'] is True
    assert result['mode'] == 'draft'
    assert result['reason'] == 'git_dirty_outside_target:CLAUDE.md'
    assert (board_root / result['draft_path']).exists()
    assert not list((team_repo / 'project' / 'Alpha').glob('*.md'))
    source = (board_root / 'project' / '个人调度' / 'source.md').read_text(encoding='utf-8')
    assert 'promoted_to:' not in source
    assert 'next_action: handoff-team-draft' in source


def test_team_kanban_sync_skips_quietly_without_credentials(tmp_path):
    cfg = _config()

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
            patch.object(scan_mod, 'STATE_FILE', tmp_path / '.kanban-state.json'), \
            patch.object(scan_mod, 'SCAN_DIRS', ['project']):
        result = scan_mod.sync_team_kanban(config=cfg)

    assert result['ok'] is False
    assert result['skipped'] is True
    assert result['reason'] == 'missing_credentials'
    assert not (tmp_path / 'shared' / 'toolkit' / 'kanban' / '.team-kanban-digest.json').exists()
