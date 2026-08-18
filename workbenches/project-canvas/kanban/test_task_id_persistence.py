#!/usr/bin/env python3
"""
Tests for task_id persistence: backfill, create, conflict resolution, state recovery.

Run with: CI=true python3 -m pytest shared/toolkit/kanban/test_task_id_persistence.py -v
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module
_HERE = Path(__file__).resolve().parent
import importlib.util
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)

load_state = scan_mod.load_state
save_state = scan_mod.save_state
rebuild_state_from_tasks = scan_mod.rebuild_state_from_tasks
backfill_task_ids = scan_mod.backfill_task_ids
backfill_workdirs = scan_mod.backfill_workdirs
resolve_conflicts = scan_mod.resolve_conflicts
create_document = scan_mod.create_document
scan_all = scan_mod.scan_all
get_project_code_prefix = scan_mod.get_project_code_prefix
infer_execution_profile = scan_mod.infer_execution_profile
infer_task_family = scan_mod.infer_task_family
task_prefix_for = scan_mod.task_prefix_for
build_naming_lint_report = scan_mod.build_naming_lint_report
search_all_files = scan_mod.search_all_files
resolve_workdir = scan_mod.resolve_workdir
update_frontmatter_field = scan_mod.update_frontmatter_field


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repo with sample tasks (no task_id)."""
    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)

    # Task 1: earlier created date
    (proj_dir / "task-a.md").write_text("""---
title: First Task
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: high
status: todo
tags: []
---

Body of first task.
""", encoding='utf-8')

    # Task 2: later created date
    (proj_dir / "task-b.md").write_text("""---
title: Second Task
created: 2026-05-03
updated: 2026-05-03
assignee: Bob
priority: medium
status: in-progress
tags: []
---

Body of second task.
""", encoding='utf-8')

    # Task 3: same project, even later
    (proj_dir / "task-c.md").write_text("""---
title: Third Task
created: 2026-05-05
updated: 2026-05-05
assignee: Alice
priority: low
status: review
tags: [test]
---

Body of third task.
""", encoding='utf-8')

    return tmp_path


@pytest.fixture
def temp_repo_with_codes(tmp_path):
    """Create a temporary repo with tasks that already have task_ids."""
    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)

    (proj_dir / "task-a.md").write_text("""---
title: First Task
task_id: HER-1
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: high
status: todo
tags: []
---

Body A.
""", encoding='utf-8')

    (proj_dir / "task-b.md").write_text("""---
title: Second Task
task_id: HER-2
created: 2026-05-03
updated: 2026-05-03
assignee: Bob
priority: medium
status: in-progress
tags: []
---

Body B.
""", encoding='utf-8')

    return tmp_path


# ── Backfill Tests ────────────────────────────────────────

def test_backfill_assigns_codes(temp_repo):
    """Tasks without task_id get assigned codes after backfill."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        all_docs = scan_all()
        state = {'version': 1, 'counters': {}}
        backfilled = backfill_task_ids(all_docs, state)

    assert backfilled == 3
    # Verify codes assigned in created-date order
    codes = {doc['filename']: doc.get('task_id') for doc in all_docs}
    assert codes['task-a.md'] == 'HER-1'
    assert codes['task-b.md'] == 'HER-2'
    assert codes['task-c.md'] == 'HER-3'


def test_backfill_preserves_existing(temp_repo_with_codes):
    """Tasks that already have task_id are not modified."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo_with_codes):
        all_docs = scan_all()
        state = {'version': 1, 'counters': {}}
        backfilled = backfill_task_ids(all_docs, state)

    assert backfilled == 0
    codes = {doc['filename']: doc.get('task_id') for doc in all_docs}
    assert codes['task-a.md'] == 'HER-1'
    assert codes['task-b.md'] == 'HER-2'


def test_backfill_order_by_created(temp_repo):
    """Backfill assigns codes in created-date order within each project."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        all_docs = scan_all()
        state = {'version': 1, 'counters': {}}
        backfill_task_ids(all_docs, state)

    # Verify the actual file content has task_id written
    for doc in all_docs:
        fpath = temp_repo / doc['path']
        content = fpath.read_text(encoding='utf-8')
        assert f"task_id: {doc['task_id']}" in content


def test_backfill_updates_counter(temp_repo):
    """After backfill, the state counter is updated to the max sequence."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        all_docs = scan_all()
        state = {'version': 1, 'counters': {}}
        backfill_task_ids(all_docs, state)

    assert state['counters']['HER'] == 3


def test_backfill_workdirs_writes_default(temp_repo):
    """Tasks without workdir get backfilled to project/{project}/."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        all_docs = scan_all()
        backfilled = backfill_workdirs(all_docs)

    assert backfilled == 3
    for doc in all_docs:
        assert doc['workdir'] == 'project/Hermes/'
        content = (temp_repo / doc['path']).read_text(encoding='utf-8')
        assert 'workdir: project/Hermes/' in content


# ── Create Document Tests ─────────────────────────────────

def test_create_document_assigns_code(temp_repo):
    """Creating a new task automatically gets a task_id."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', temp_repo / '.kanban-state.json'):
        # First backfill existing tasks
        all_docs = scan_all()
        state = {'version': 1, 'counters': {}}
        backfill_task_ids(all_docs, state)
        save_state(state)

        # Create new task
        ok, path, task_id = create_document('Hermes', 'New Task', 'Alice', 'high')

    assert ok is True
    assert task_id == 'HER-4'  # After HER-1, HER-2, HER-3
    assert path == 'project/Hermes/HER-4_New-Task.md'


def test_create_document_reconciles_lagging_counter_with_disk(temp_repo):
    """A manually added filename advances allocation even when state is stale."""
    project_dir = temp_repo / 'project' / 'Hermes'
    (project_dir / 'HER-12_Manually-added.md').write_text('manual card\n', encoding='utf-8')
    state_file = temp_repo / '.kanban-state.json'

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        save_state({'version': 1, 'counters': {'HER': 3}})
        ok, path, task_id = create_document('Hermes', 'Created by API', 'Alice', 'high')
        state = load_state()

    assert ok is True
    assert task_id == 'HER-13'
    assert path == 'project/Hermes/HER-13_Created-by-API.md'
    assert state['counters']['HER'] == 13


def test_create_document_rejects_empty_title(temp_repo):
    """Creating a task requires a non-empty title."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok, msg, task_id = create_document('Hermes', '   ', 'Alice', 'medium')

    assert ok is False
    assert msg == '标题不能为空'
    assert task_id == ''


def test_create_document_uses_fallback_filename_when_slug_is_empty(temp_repo):
    """Non-empty titles whose slug is empty use a fallback filename."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok, path, task_id = create_document('Hermes', '!!!', 'Alice', 'medium')

    assert ok is True
    assert task_id == 'HER-1'
    assert path == 'project/Hermes/HER-1_task.md'
    assert (temp_repo / path).exists()


def test_create_document_writes_default_workdir(temp_repo):
    """Creating a task writes default workdir based on project name."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok, path, task_id = create_document('Hermes', 'With Workdir', 'Alice', 'high')

    assert ok is True
    content = (temp_repo / path).read_text(encoding='utf-8')
    assert f'task_id: {task_id}' in content
    assert 'workdir: project/Hermes/' in content


def test_create_document_can_write_explicit_real_project_ref(temp_repo):
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok, path, _task_id = create_document(
            '个人调度',
            'Project task',
            'Owner',
            'medium',
            workdir='/tmp/existing-project',
            project_ref='project-alpha',
        )

    assert ok is True
    content = (temp_repo / path).read_text(encoding='utf-8')
    assert 'project_ref: project-alpha' in content


def test_create_personal_dispatch_uses_explicit_task_family(temp_repo):
    """Personal dispatch cards can opt into stable family prefixes."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok, path, task_id = create_document(
            '个人调度',
            '制定个人看板任务卡命名规则',
            'Owner',
            'medium',
            body='命名规则和治理约定',
            workdir='/Users/example/workspace/kanban',
            task_family='governance',
        )

    assert ok is True
    assert task_id == 'GOV-1'
    assert path == 'project/个人调度/GOV-1_制定个人看板任务卡命名规则.md'
    content = (temp_repo / path).read_text(encoding='utf-8')
    assert 'task_family: governance' in content
    assert 'execution_profile: kanban' in content


def test_create_personal_dispatch_infers_skill_family_and_profile(temp_repo):
    """Skill cards in the personal dispatch queue should not become XXX cards."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok, path, task_id = create_document(
            '个人调度',
            'skill治理文档漂移修正',
            'Owner',
            'medium',
            body='修复 skill policy 文档漂移',
            workdir='/Users/example/skills',
        )

    assert ok is True
    assert task_id == 'SKL-1'
    content = (temp_repo / path).read_text(encoding='utf-8')
    assert 'task_family: skill' in content
    assert 'execution_profile: skills' in content


def test_task_family_prefix_only_changes_dispatch_projects():
    assert task_prefix_for('Hermes', title='skill治理文档漂移修正') == 'HER'
    assert task_prefix_for('个人调度', title='skill治理文档漂移修正', workdir='/Users/example/skills') == 'SKL'
    assert infer_task_family('个人调度', title='制定个人看板任务卡命名规则') == 'governance'
    assert infer_task_family('个人调度', title='治理复核', body='run scan_governance', tags=['governance']) == 'governance'
    assert infer_task_family('个人调度', title='会议链/内容链待真实负载验证', tags=['meeting-chain', 'content-chain'], stage='meeting/analyze') == 'chain'
    assert infer_execution_profile('/Users/example/workspace/KnowledgeManagement') == 'knowledge'


def test_lint_naming_reports_missing_task_family_for_active_dispatch(tmp_path):
    proj_dir = tmp_path / 'project' / '个人调度'
    proj_dir.mkdir(parents=True)
    (proj_dir / 'legacy-km.md').write_text("""---
title: 筛选 W24 P1 科研候选
task_id: XXX-4
workdir: /Users/example/workspace/KnowledgeManagement/InfoOps/
created: 2026-06-10
updated: 2026-06-11
assignee: Owner
priority: medium
status: todo
tags: [km, reading, triage]
kind: task
domain: knowledge
stage: infoops/dispatch
---

Body.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/个人调度']):
        report = build_naming_lint_report(scan_all())

    assert report['summary']['missing_task_family'] == 1
    issue = report['issues'][0]
    assert issue['type'] == 'missing_task_family'
    assert issue['task_id'] == 'XXX-4'
    assert issue['suggested_task_family'] == 'knowledge'


def test_lint_naming_reports_prefix_family_mismatch(tmp_path):
    proj_dir = tmp_path / 'project' / '个人调度'
    proj_dir.mkdir(parents=True)
    (proj_dir / 'SEL-6_pointer.md').write_text("""---
title: LLM Wiki 团队证据库构建思路与迭代跟踪
task_id: SEL-6
task_family: kanban
execution_profile: kanban
workdir: project/个人调度/
created: 2026-06-15
updated: 2026-06-15
assignee: Owner
priority: medium
status: todo
tags: []
kind: task
domain: team
source: team-kanban/SEL-6
---

Body.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/个人调度']):
        report = build_naming_lint_report(scan_all())

    assert report['summary']['prefix_family_mismatch'] == 1
    issue = report['issues'][0]
    assert issue['type'] == 'prefix_family_mismatch'
    assert issue['actual_prefix'] == 'SEL'
    assert issue['expected_prefix'] == 'KAN'
    assert issue['severity'] == 'error'


def test_lint_naming_reports_duplicate_task_ids_and_legacy_collision(tmp_path):
    proj_dir = tmp_path / 'project' / '个人调度'
    proj_dir.mkdir(parents=True)
    (proj_dir / 'GOV-100_first.md').write_text("""---
title: First GOV Card
task_id: GOV-100
task_family: governance
execution_profile: kanban
workdir: project/个人调度/
created: 2026-06-18
updated: 2026-06-18
assignee: Owner
priority: medium
status: todo
tags: [governance]
kind: task
domain: governance
---

Body.
""", encoding='utf-8')
    (proj_dir / 'GOV-100_second.md').write_text("""---
title: Second GOV Card
task_id: GOV-100
task_family: governance
execution_profile: kanban
workdir: project/个人调度/
created: 2026-06-18
updated: 2026-06-18
assignee: Owner
priority: medium
status: todo
tags: [governance]
kind: task
domain: governance
---

Body.
""", encoding='utf-8')
    (proj_dir / 'GOV-101_legacy-collision.md').write_text("""---
title: Legacy Collision
task_id: GOV-101
legacy_id: GOV-100
task_family: governance
execution_profile: kanban
workdir: project/个人调度/
created: 2026-06-18
updated: 2026-06-18
assignee: Owner
priority: medium
status: todo
tags: [governance]
kind: task
domain: governance
---

Body.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/个人调度']):
        report = build_naming_lint_report(scan_all())

    assert report['summary']['duplicate_task_id'] == 1
    assert report['summary']['legacy_task_id_collision'] == 1
    duplicate = next(i for i in report['issues'] if i['type'] == 'duplicate_task_id')
    assert duplicate['severity'] == 'error'
    assert duplicate['task_id'] == 'GOV-100'
    assert set(duplicate['paths']) == {
        'project/个人调度/GOV-100_first.md',
        'project/个人调度/GOV-100_second.md',
    }
    legacy = next(i for i in report['issues'] if i['type'] == 'legacy_task_id_collision')
    assert legacy['severity'] == 'warning'
    assert legacy['legacy_id'] == 'GOV-100'

    human = scan_mod.format_naming_lint_report(report)
    assert 'duplicate_task_id GOV-100' in human
    assert 'legacy_task_id_collision GOV-101' in human


def test_lint_naming_warns_empty_execution_result_without_false_positive(tmp_path):
    proj_dir = tmp_path / 'project' / '个人调度'
    proj_dir.mkdir(parents=True)
    (proj_dir / 'GOV-102_placeholder.md').write_text("""---
title: Placeholder Result
task_id: GOV-102
task_family: governance
execution_profile: kanban
workdir: project/个人调度/
created: 2026-06-18
updated: 2026-06-18
assignee: Owner
priority: medium
status: done
tags: [governance]
kind: task
domain: governance
---

## 背景 / 来源
Body.

## 执行结果

（Codex 回填：每个 P 的实现与文件、测试命令与结果、未决项。）
""", encoding='utf-8')
    (proj_dir / 'GOV-103_real-result.md').write_text("""---
title: Real Result
task_id: GOV-103
task_family: governance
execution_profile: kanban
workdir: project/个人调度/
created: 2026-06-18
updated: 2026-06-18
assignee: Owner
priority: medium
status: review
tags: [governance]
kind: task
domain: governance
---

## 背景 / 来源
Body.

## 执行结果

- 已实现 P0/P1 检查。
- 测试通过。
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/个人调度']):
        report = build_naming_lint_report(scan_all())

    empty_issues = [i for i in report['issues'] if i['type'] == 'empty_execution_result']
    assert report['summary']['empty_execution_result'] == 1
    assert len(empty_issues) == 1
    assert empty_issues[0]['severity'] == 'warning'
    assert empty_issues[0]['task_id'] == 'GOV-102'


def test_search_all_files_matches_legacy_id(tmp_path):
    proj_dir = tmp_path / 'project' / '个人调度'
    proj_dir.mkdir(parents=True)
    (proj_dir / 'KAN-2_pointer.md').write_text("""---
title: LLM Wiki 团队证据库构建思路与迭代跟踪
task_id: KAN-2
legacy_id: SEL-6
task_family: kanban
workdir: project/个人调度/
created: 2026-06-15
updated: 2026-06-15
assignee: Owner
priority: medium
status: todo
tags: []
---

Body.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/个人调度']):
        results, total, _, _ = search_all_files(query='SEL-6')

    assert total == 1
    assert results[0]['path'] == 'project/个人调度/KAN-2_pointer.md'
    assert results[0]['is_task'] is True


def test_update_title_renames_file_and_references(tmp_path):
    """Updating title renames the task file and updates [[path]] references."""
    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)
    old_rel = 'project/Hermes/HER-1_Old-Title.md'
    (tmp_path / old_rel).write_text("""---
title: Old Title
task_id: HER-1
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: high
status: todo
tags: []
---

Body.
""", encoding='utf-8')
    ref_file = proj_dir / "HER-2_Ref.md"
    ref_file.write_text(f"""---
title: Ref
task_id: HER-2
created: 2026-05-02
updated: 2026-05-02
assignee: Bob
priority: medium
status: todo
tags: []
---

See [[{old_rel}]].
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        result = update_frontmatter_field(old_rel, 'title', '新 标题')

    assert result == (True, 'OK', 'project/Hermes/HER-1_新-标题.md')
    assert not (tmp_path / old_rel).exists()
    assert (tmp_path / 'project/Hermes/HER-1_新-标题.md').exists()
    assert '[[project/Hermes/HER-1_新-标题.md]]' in ref_file.read_text(encoding='utf-8')


def test_update_title_uses_fallback_filename_when_slug_is_empty(tmp_path):
    """Renaming to a punctuation-only title uses fallback slug in filename."""
    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)
    old_rel = 'project/Hermes/HER-1_Old.md'
    (tmp_path / old_rel).write_text("""---
title: Old
task_id: HER-1
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: high
status: todo
tags: []
---

Body.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        result = update_frontmatter_field(old_rel, 'title', '!!!')

    assert result == (True, 'OK', 'project/Hermes/HER-1_task.md')
    assert not (tmp_path / old_rel).exists()
    assert (tmp_path / 'project/Hermes/HER-1_task.md').exists()
    assert 'title: !!!' in (tmp_path / 'project/Hermes/HER-1_task.md').read_text(encoding='utf-8')


def test_update_title_collision_returns_failure_without_changing_title(tmp_path):
    """Title rename collision is reported as failure and leaves the source file unchanged."""
    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)
    old_rel = 'project/Hermes/HER-1_Old.md'
    source = tmp_path / old_rel
    source.write_text("""---
title: Old
task_id: HER-1
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: high
status: todo
tags: []
---

Body.
""", encoding='utf-8')
    (proj_dir / "HER-1_New.md").write_text("""---
title: Existing
task_id: HER-99
created: 2026-05-01
updated: 2026-05-01
assignee: Alice
priority: high
status: todo
tags: []
---
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        ok, msg = update_frontmatter_field(old_rel, 'title', 'New')

    assert ok is False
    assert '目标文件已存在' in msg
    assert source.exists()
    assert 'title: Old' in source.read_text(encoding='utf-8')


def test_resolve_workdir_supports_relative_absolute_and_tilde(temp_repo):
    """resolve_workdir handles repo-relative, absolute, and tilde paths."""
    home_dir = temp_repo / 'home'
    home_dir.mkdir()

    allowed_roots = {
        'open_allowed_roots': [str(temp_repo), '/tmp', str(home_dir)],
    }
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'load_config', return_value=allowed_roots), \
         patch('os.path.expanduser', side_effect=lambda p: str(home_dir / p[2:]) if p.startswith('~/') else p):
        rel_path, rel_err = resolve_workdir('project/Hermes/', 'project/Hermes/task-a.md')
        abs_path, abs_err = resolve_workdir('/tmp/external-repo', 'project/Hermes/task-a.md')
        tilde_path, tilde_err = resolve_workdir('~/external-repo', 'project/Hermes/task-a.md')

    assert rel_err is None
    assert rel_path == temp_repo / 'project' / 'Hermes'
    assert abs_err is None
    assert abs_path == Path('/tmp/external-repo').resolve()
    assert tilde_err is None
    assert tilde_path == home_dir / 'external-repo'


def test_create_increments_counter(temp_repo):
    """Successive creates increment the counter."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok1, _, code1 = create_document('Hermes', 'First', 'Alice', 'medium')
        ok2, _, code2 = create_document('Hermes', 'Second', 'Bob', 'high')
        ok3, _, code3 = create_document('Hermes', 'Third', 'Alice', 'low')

    assert ok1 and ok2 and ok3
    assert code1 == 'HER-1'
    assert code2 == 'HER-2'
    assert code3 == 'HER-3'


def test_create_multi_project(temp_repo):
    """Creating tasks in different projects uses separate counters."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok1, _, code1 = create_document('Hermes', 'H Task', 'Alice', 'medium')
        ok2, _, code2 = create_document('Sell-What', 'S Task', 'Bob', 'high')
        ok3, _, code3 = create_document('Hermes', 'H Task 2', 'Alice', 'low')

    assert code1 == 'HER-1'
    assert code2 == 'SEL-1'
    assert code3 == 'HER-2'


# ── State Management Tests ────────────────────────────────

def test_state_persists_across_restarts(temp_repo):
    """State file survives and loads correctly."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        save_state({'version': 1, 'counters': {'HER': 5, 'SEL': 3}})
        loaded = load_state()

    assert loaded['counters']['HER'] == 5
    assert loaded['counters']['SEL'] == 3


def test_state_recovery_after_loss(temp_repo):
    """When state file is lost, rebuild_state_from_tasks recovers counters."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        # First backfill to write codes
        all_docs = scan_all()
        state = {'version': 1, 'counters': {}}
        backfill_task_ids(all_docs, state)

        # Now simulate state loss
        recovered = rebuild_state_from_tasks(scan_all())

    assert recovered['counters']['HER'] == 3


def test_load_state_missing_file(temp_repo):
    """load_state returns empty dict when file doesn't exist."""
    state_file = temp_repo / '.kanban-state.json'
    with patch.object(scan_mod, 'STATE_FILE', state_file):
        state = load_state()

    assert state == {'version': 1, 'counters': {}}


def test_load_state_corrupt_file(temp_repo):
    """load_state returns empty dict when file is corrupt JSON."""
    state_file = temp_repo / '.kanban-state.json'
    state_file.write_text("not valid json{{{", encoding='utf-8')
    with patch.object(scan_mod, 'STATE_FILE', state_file):
        state = load_state()

    assert state == {'version': 1, 'counters': {}}


# ── Conflict Resolution Tests ─────────────────────────────

def test_conflict_resolution(temp_repo):
    """When two tasks have the same task_id, the earlier file keeps it."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        # Manually set same code on two tasks
        fpath_a = temp_repo / "project" / "Hermes" / "task-a.md"
        fpath_b = temp_repo / "project" / "Hermes" / "task-b.md"
        content_a = fpath_a.read_text(encoding='utf-8')
        content_b = fpath_b.read_text(encoding='utf-8')
        # Both get HER-1
        fpath_a.write_text(content_a.replace('tags: []', 'task_id: HER-1\ntags: []'), encoding='utf-8')
        fpath_b.write_text(content_b.replace('tags: []', 'task_id: HER-1\ntags: []'), encoding='utf-8')

        all_docs = scan_all()
        state = {'version': 1, 'counters': {'HER': 1}}
        resolved = resolve_conflicts(all_docs, state)

    assert resolved == 1  # One conflict resolved
    # The earlier mtime file should keep HER-1, the other gets HER-2
    codes = sorted(doc.get('task_id', '') for doc in all_docs)
    assert 'HER-1' in codes
    assert 'HER-2' in codes


def test_no_conflict_no_changes(temp_repo):
    """resolve_conflicts returns 0 when there are no conflicts."""
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo):
        # Backfill first to assign unique codes
        all_docs = scan_all()
        state = {'version': 1, 'counters': {}}
        backfill_task_ids(all_docs, state)

        # Resolve should find nothing
        all_docs = scan_all()
        resolved = resolve_conflicts(all_docs, state)

    assert resolved == 0


# ── No Gap Reuse Test ─────────────────────────────────────

def test_no_code_gap_reuse(temp_repo_with_codes):
    """When a task is deleted, its sequence number is not reused."""
    state_file = temp_repo_with_codes / '.kanban-state.json'
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo_with_codes), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        # Save state showing HER counter at 2
        save_state({'version': 1, 'counters': {'HER': 2}})

        # Delete HER-1
        (temp_repo_with_codes / "project" / "Hermes" / "task-a.md").unlink()

        # Create new task — should get HER-3, not HER-1
        ok, _, code = create_document('Hermes', 'New After Delete', 'Alice', 'medium')

    assert code == 'HER-3'
