#!/usr/bin/env python3
"""Tests for scan_governance.py probe output."""

import importlib.util
import subprocess
from pathlib import Path
import pytest

_GOV = Path(__file__).resolve().parents[1] / 'governance' / 'scan_governance.py'
if not _GOV.is_file():
    pytest.skip("missing optional source path: governance/scan_governance.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location('scan_governance', _GOV)
gov = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gov)


def _workspace_root(tmp_path):
    for name in gov._load_matrix_template()['workspaces']:
        (tmp_path / name).mkdir()
    return tmp_path


def test_probe_schema_and_review_boundaries(tmp_path):
    root = _workspace_root(tmp_path)
    probe = gov.build_probe_matrix(str(root), stale_days=30)
    rules = {rule['key']: rule for rule in probe['rules']}

    assert probe['doc_type'] == 'state'
    assert set(rules) == {'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8'}
    assert {cell['state'] for cell in rules['G1']['cells'].values()} == {'pass'}
    assert {cell['state'] for cell in rules['G5']['cells'].values()} == {'needs_review'}
    assert {cell['state'] for cell in rules['G6']['cells'].values()} == {'needs_review'}
    workspace_states = {
        cell['state']
        for workspace, cell in rules['G8']['cells'].items()
        if workspace in probe['workspaces']
    }
    assert workspace_states == {'pass'}
    assert rules['G8']['cells']['_meta']['state'] == 'warn'
    for key in ('G2', 'G4', 'G7'):
        assert {cell['state'] for cell in rules[key]['cells'].values()} == {'unknown'}


def test_infoops_coverage_probe_warns_on_unregistered_active_manifest(tmp_path):
    root = _workspace_root(tmp_path)
    manifest = root / 'AI-Agent-Hub' / 'automation-control-plane' / 'tasks' / 'new_scan.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"id":"new_scan","status":"ACTIVE"}\n', encoding='utf-8')

    probe = gov.build_probe_matrix(str(root), stale_days=30)
    rules = {rule['key']: rule for rule in probe['rules']}
    g8 = rules['G8']['cells']['AI-Agent-Hub']

    assert g8['state'] == 'warn'
    assert any('new_scan.json' in item and 'active_manifest' in item for item in g8['evidence'])
    assert probe['infoops_coverage']['candidates'] == [{
        'path': 'AI-Agent-Hub/automation-control-plane/tasks/new_scan.json',
        'identity_tags': ['active_manifest'],
    }]


def test_credential_file_classifier_precision():
    # 真凭据类文件 → True
    for p in ('.env', '.env.local', 'a/server.pem', 'b/private.key',
              'config/credentials.json', 'foo/id_rsa', 'x/.npmrc'):
        assert gov._path_is_credential_file(p) is True, p
    # 模板/示例、讨论密钥的 .md 卡、名字含 secret/cookie 的源码 → False（不误报成 warn）
    for p in ('.env.example', 'kanban.env.example', 'x/credentials.template',
              'data/sample.key', 'docs/团队密钥泄露.md', 'notes/secret-plan.md',
              'scripts/xhs/cookies.py'):
        assert gov._path_is_credential_file(p) is False, p


def _git(repo, *args):
    subprocess.run(['git', '-C', str(repo), *args], check=True,
                   capture_output=True, text=True)


def test_g5_warns_on_credential_file_lingering_in_git_history(tmp_path):
    root = _workspace_root(tmp_path)
    repo = root / 'AI-Agent-Hub' / 'demo-repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@example.com')
    _git(repo, 'config', 'user.name', 'tester')
    # 提交一个凭据文件，再从工作树删除并提交 —— 模拟"删了却留在 git 历史"
    secret_value = 'TOPSECRET_VALUE_DO_NOT_LEAK_123'
    (repo / '.env').write_text(f'API_KEY={secret_value}\n', encoding='utf-8')
    (repo / 'README.md').write_text('# demo\n', encoding='utf-8')
    _git(repo, 'add', '.env', 'README.md')
    _git(repo, 'commit', '-q', '-m', 'add env')
    _git(repo, 'rm', '-q', '.env')
    _git(repo, 'commit', '-q', '-m', 'remove env')

    probe = gov.build_probe_matrix(str(root), stale_days=30)
    g5 = {rule['key']: rule for rule in probe['rules']}['G5']
    cell = g5['cells']['AI-Agent-Hub']

    assert cell['state'] == 'warn'
    history = [e for e in cell['evidence'] if 'git history' in e]
    assert history, 'expected a git-history lingering finding'
    # 安全不变量：探针只报脱敏路径 + 计数，绝不回显密钥值
    assert secret_value not in repr(probe)


def test_g5_warns_on_current_tracked_secret_path(tmp_path):
    root = _workspace_root(tmp_path)
    repo = root / 'AI-Agent-Hub' / 'tracked-secret-repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@example.com')
    _git(repo, 'config', 'user.name', 'tester')
    secret_value = 'CURRENT_SECRET_VALUE_DO_NOT_LEAK'
    (repo / '.env').write_text(f'TOKEN={secret_value}\n', encoding='utf-8')
    (repo / '.env.example').write_text('TOKEN=example\n', encoding='utf-8')
    _git(repo, 'add', '.env', '.env.example')
    _git(repo, 'commit', '-q', '-m', 'track env')

    probe = gov.build_probe_matrix(str(root), stale_days=30)
    g5 = {rule['key']: rule for rule in probe['rules']}['G5']
    cell = g5['cells']['AI-Agent-Hub']

    assert cell['state'] == 'warn'
    assert any('.env (currently tracked)' in item for item in cell['evidence'])
    assert '.env.example' not in repr(cell)
    assert secret_value not in repr(probe)


def test_g6_warns_on_deterministic_dirty_or_no_remote_repo(tmp_path):
    root = _workspace_root(tmp_path)
    repo = root / 'AI-Agent-Hub' / 'dirty-repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@example.com')
    _git(repo, 'config', 'user.name', 'tester')
    (repo / 'README.md').write_text('# demo\n', encoding='utf-8')
    _git(repo, 'add', 'README.md')
    _git(repo, 'commit', '-q', '-m', 'init')
    (repo / 'README.md').write_text('# dirty\n', encoding='utf-8')

    probe = gov.build_probe_matrix(str(root), stale_days=30)
    g6 = {rule['key']: rule for rule in probe['rules']}['G6']
    cell = g6['cells']['AI-Agent-Hub']

    assert cell['state'] == 'warn'
    assert any('dirty-repo: dirty=1 no_remote' in item for item in cell['evidence'])


def test_g6_ignores_explicit_local_only_remote_policy(tmp_path):
    root = _workspace_root(tmp_path)
    repo = root / 'AI-Agent-Hub' / 'local-only'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@example.com')
    _git(repo, 'config', 'user.name', 'tester')
    (repo / 'AGENTS.md').write_text('No git remote by design.\n', encoding='utf-8')
    _git(repo, 'add', 'AGENTS.md')
    _git(repo, 'commit', '-q', '-m', 'init')

    probe = gov.build_probe_matrix(str(root), stale_days=30)
    g6 = {rule['key']: rule for rule in probe['rules']}['G6']
    cell = g6['cells']['AI-Agent-Hub']

    assert cell['state'] == 'needs_review'
    assert 'no_remote' not in repr(cell)


def test_generated_markdown_is_not_reported_as_missing_doc_type(tmp_path):
    root = _workspace_root(tmp_path)
    generated = root / 'AI-Agent-Hub' / 'WORKSPACE_STATUS.generated.md'
    generated.write_text('# Generated\n\nno doc type here\n', encoding='utf-8')

    docs = gov.scan_gov_docs(str(root), stale_days=30)

    assert all(not item['path'].endswith('.generated.md') for item in docs)


def test_compat_pointer_and_task_card_index_are_not_untagged_governance_docs(tmp_path):
    root = _workspace_root(tmp_path)
    pointer = root / 'AI-Agent-Hub' / 'demo' / 'CLAUDE.md'
    pointer.parent.mkdir(parents=True)
    pointer.write_text('@AGENTS.md\n', encoding='utf-8')
    task_index = root / 'AI-Agent-Hub' / 'kanban-personal' / 'project' / '个人调度' / 'SKL-5_SKILL_INDEX.md'
    task_index.parent.mkdir(parents=True)
    task_index.write_text('---\ntask_id: SKL-5\n---\n', encoding='utf-8')

    docs = gov.scan_gov_docs(str(root), stale_days=30)
    by_path = {item['path']: item for item in docs}

    assert by_path['AI-Agent-Hub/demo/CLAUDE.md']['doc_type'] == 'pointer'
    assert all(item['path'] != 'AI-Agent-Hub/kanban-personal/project/个人调度/SKL-5_SKILL_INDEX.md' for item in docs)


def test_infoops_rule_docs_without_source_identity_are_not_coverage_candidates(tmp_path):
    root = _workspace_root(tmp_path)
    infoops = root / 'KnowledgeManagement' / 'InfoOps'
    infoops.mkdir(parents=True)
    (infoops / 'AI_OUTPUT_CLOSEOUT_PROTOCOL.md').write_text(
        '> doc_type: rule · status: active\n', encoding='utf-8'
    )
    (infoops / 'ROUTING_MODEL.md').write_text('> doc_type: rule\n', encoding='utf-8')

    coverage = gov.scan_infoops_coverage(str(root))

    assert coverage['candidates'] == []


def test_probe_lists_registered_and_unregistered_top_level_areas(tmp_path):
    root = _workspace_root(tmp_path)
    (root / 'ExtraLocalArea').mkdir()

    probe = gov.build_probe_matrix(str(root), stale_days=30)
    areas = {item['name']: item['registered'] for item in probe['top_level_areas']}

    assert areas['Library'] is True
    assert areas['ExtraLocalArea'] is False
    assert 'summary_metrics' in probe


def test_team_handoff_publish_runtime_is_excluded_from_scan_noise(tmp_path):
    root = _workspace_root(tmp_path)
    checkout = (
        root
        / 'AI-Agent-Hub'
        / 'kanban-personal'
        / 'shared'
        / 'toolkit'
        / 'kanban'
        / '.team-handoff-publish'
        / 'team-workspace'
        / 'run-20260613-212410'
    )
    (checkout / '.git').mkdir(parents=True)
    (checkout / '.claude' / 'skills').mkdir(parents=True)
    (checkout / '.claude' / 'skills' / 'lark-doc').symlink_to('../../.agents/skills/lark-doc')

    rel_broken, abs_broken = gov.find_broken_symlinks(str(root))
    repos = [Path(repo).relative_to(root).as_posix() for repo in gov.find_repos(str(root))]

    assert rel_broken == []
    assert abs_broken == []
    assert all('.team-handoff-publish' not in repo for repo in repos)
