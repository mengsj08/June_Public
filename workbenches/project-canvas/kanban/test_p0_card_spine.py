#!/usr/bin/env python3
"""
Tests for P0-C card spine defaults and compatibility.

Run with: CI=true python3 -m pytest shared/toolkit/kanban/test_p0_card_spine.py -v
"""

from pathlib import Path
import threading
from unittest.mock import patch

import importlib.util

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def _frontmatter_keys(content):
    fm_block = content.split('---', 2)[1]
    return [line.split(':', 1)[0] for line in fm_block.splitlines() if ':' in line]


def test_p0_card_spine_frontmatter_insert_order(tmp_path):
    task_dir = tmp_path / 'project' / 'Hermes'
    task_dir.mkdir(parents=True)
    task_path = task_dir / 'sample.md'
    task_path.write_text("""---
title: Sample
created: 2026-06-01
updated: 2026-06-01
assignee: Alice
priority: medium
status: todo
tags: []
---

Body.
""", encoding='utf-8')

    rel_path = 'project/Hermes/sample.md'
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        for field, value in [
            ('next_action', 'ship it'),
            ('promoted_from', 'old-card'),
            ('scenario_slug', 'sample-scenario'),
            ('kind', 'task'),
            ('domain', 'scenario'),
            ('promoted_to', 'scenario/sample-scenario'),
        ]:
            ok, msg = scan_mod.update_frontmatter_field(rel_path, field, value)
            assert ok, msg

    keys = _frontmatter_keys(task_path.read_text(encoding='utf-8'))
    assert keys.index('tags') < keys.index('kind')
    assert keys.index('kind') < keys.index('scenario_slug')
    assert keys.index('kind') < keys.index('domain')
    assert keys.index('domain') < keys.index('scenario_slug')
    assert keys.index('scenario_slug') < keys.index('promoted_to')
    assert keys.index('promoted_to') < keys.index('promoted_from')
    assert keys.index('promoted_from') < keys.index('next_action')


def test_update_frontmatter_field_only_rewrites_opening_frontmatter(tmp_path):
    task_dir = tmp_path / 'project' / 'Hermes'
    task_dir.mkdir(parents=True)
    fm_block = """---
title: Sample
created: 2026-06-01
updated: 2026-06-01
assignee: Alice
priority: medium
status: todo
tags: []
---"""
    task_path = task_dir / 'sample.md'
    task_path.write_text(f"""{fm_block}

Body before.

```yaml
{fm_block}
```

Body after.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        ok, msg = scan_mod.update_frontmatter_field('project/Hermes/sample.md', 'status', 'done')

    assert ok, msg
    content = task_path.read_text(encoding='utf-8')
    assert content.startswith('---\ntitle: Sample')
    assert 'status: done' in content.split('---', 2)[1]
    assert f'```yaml\n{fm_block}\n```' in content


def test_markdown_write_lock_keeps_frontmatter_and_body_updates_self_consistent(tmp_path):
    task_dir = tmp_path / 'project' / 'Hermes'
    task_dir.mkdir(parents=True)
    task_path = task_dir / 'sample.md'
    task_path.write_text("""---
title: Sample
created: 2026-06-01
updated: 2026-06-01
assignee: Alice
priority: medium
status: todo
tags: []
---

Old body.
""", encoding='utf-8')

    assert scan_mod.MARKDOWN_WRITE_LOCK is not None

    def update_status():
        ok, msg = scan_mod.update_frontmatter_field('project/Hermes/sample.md', 'status', 'in-progress')
        assert ok, msg

    def update_body():
        ok, msg = scan_mod.update_task_body('project/Hermes/sample.md', 'New body.')
        assert ok, msg

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        t1 = threading.Thread(target=update_status)
        t2 = threading.Thread(target=update_body)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    content = task_path.read_text(encoding='utf-8')
    assert 'status: in-progress' in content
    assert content.rstrip().endswith('New body.')
    assert content.count('---') == 2


def test_p0_card_spine_old_card_without_kind_defaults_to_task(tmp_path):
    task_dir = tmp_path / 'project' / 'Hermes'
    task_dir.mkdir(parents=True)
    (task_dir / 'old-card.md').write_text("""---
title: Old Card
task_id: HER-1
workdir: project/Hermes/
created: 2026-06-01
updated: 2026-06-01
assignee: Alice
priority: medium
status: todo
tags: []
scenario_slug: old-card
---

## 完成标准
- [ ] Still readable.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        result, status = scan_mod.get_task_detail(path='project/Hermes/old-card.md')

    assert status == 200
    assert result['ok'] is True
    task = result['task']
    assert task['kind'] == 'task'
    assert task['scenario_slug'] == 'old-card'
    assert task['promoted_to'] == ''
    assert task['promoted_from'] == ''
    assert task['next_action'] == ''
    assert '## 完成标准' in task['body']


def test_p0_card_spine_create_document_empty_body_writes_template_and_kind(tmp_path):
    state_file = tmp_path / '.kanban-state.json'

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'STATE_FILE', state_file):
        ok, rel_path, task_id = scan_mod.create_document('Hermes', 'New Task', 'Alice', 'high', body='')

    assert ok is True
    assert task_id == 'HER-1'
    content = (tmp_path / rel_path).read_text(encoding='utf-8')
    assert 'status: todo\nkind: task\n' in content
    assert 'kind: task\n\n' not in content
    assert '## 背景 / 来源\n- 来源：\n- 为什么现在做：' in content
    assert '## 要做什么\n（一句话目标 + 明确动作）' in content
    assert '## 输入与材料\n- workdir:\n- 入口文件 / 链接:\n- 约束 / 不要碰:' in content
    assert '## 完成标准\n- [ ] 输出物明确\n- [ ] 验证方式明确' in content
    assert '## 执行结果\n待回填。' in content


def test_task_domain_is_inferred_from_workspace_context(tmp_path):
    task_dir = tmp_path / 'project' / '个人调度'
    task_dir.mkdir(parents=True)
    (task_dir / 'km.md').write_text("""---
title: KM refresh
task_id: PER-1
workdir: /Users/example/workspace/KnowledgeManagement
created: 2026-06-10
updated: 2026-06-10
assignee: Owner
priority: high
status: todo
tags: [freshness]
---

Body.
""", encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project/个人调度']):
        docs = scan_mod.scan_all()
        detail, status = scan_mod.get_task_detail(path='project/个人调度/km.md')

    assert docs[0]['domain'] == 'knowledge'
    assert status == 200
    assert detail['task']['domain'] == 'knowledge'
