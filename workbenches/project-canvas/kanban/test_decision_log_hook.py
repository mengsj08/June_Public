"""DECISION_LOG 自动喂养钩子（keystone）功能测试。

覆盖：
- 过 gate 的状态流转 → 机器动作区留下状态观察，class/撤销代价正确
- 不过 gate 的流转（如 todo→in-progress）→ 不写账
- 钩子永不阻断状态更新，且 DECISION_LOG 缺失时静默跳过（保护真账本）
"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


DECISION_LOG_SEED = """# Kanban 治理决策日志

> doc_type: decision-log · owner: Owner

## 自动草稿（待 Owner 追认）

> 钩子自动产，Owner 追认后移入下方正式「决策行」并去掉前缀。

_（暂无草稿）_

## 决策行（倒序）

### 2026-06-17
- 2026-06-17 · class:工作区骨架 · 既有行 · 撤销:中 · 来源:种子
"""


def _make_repo(tmp_path, *, fm_extra='', status='review'):
    """造一个最小临时仓：governance/DECISION_LOG.md + 一张任务卡。"""
    gov = tmp_path / 'shared' / 'toolkit' / 'governance'
    gov.mkdir(parents=True)
    (gov / 'DECISION_LOG.md').write_text(DECISION_LOG_SEED, encoding='utf-8')

    proj = tmp_path / 'project' / '个人调度'
    proj.mkdir(parents=True)
    card = proj / 'KAN-1_sample.md'
    card.write_text(
        "---\n"
        "title: 示例卡\n"
        "task_id: KAN-1\n"
        f"status: {status}\n"
        "updated: 2026-06-01\n"
        f"{fm_extra}"
        "---\n\n## 完成标准\n- 做完\n",
        encoding='utf-8',
    )
    return tmp_path, 'project/个人调度/KAN-1_sample.md'


def _log_text(tmp_path):
    return (tmp_path / 'shared' / 'toolkit' / 'governance' / 'DECISION_LOG.md').read_text(encoding='utf-8')


def test_review_to_done_writes_machine_observation(tmp_path):
    repo, relpath = _make_repo(tmp_path, fm_extra='responsibility: ai-owned\nsafety: reversible\n')
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        ok, _ = scan_mod.update_frontmatter_field(relpath, 'status', 'done')
    assert ok
    text = _log_text(repo)
    assert 'class:auto-验收' in text
    assert '验收通过 KAN-1' in text
    # ai-owned + reversible → 撤销:低
    assert '撤销:低' in text.split('## 决策行')[0]
    # 状态不是 Owner 决策；只进机器审计区，不污染待追认或正式决策。
    draft_zone, machine_tail = text.split('## 机器动作（审计，不占 Owner 待批）', 1)
    machine_zone, _, formal_zone = machine_tail.partition('## 决策行')
    assert 'auto-验收' not in draft_zone
    assert 'auto-验收' in machine_zone and 'auto-验收' not in formal_zone
    assert '[状态观察]' in machine_zone


def test_review_to_todo_writes_reject_draft(tmp_path):
    repo, relpath = _make_repo(tmp_path, fm_extra='responsibility: pi-gated\n')
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'todo')
    text = _log_text(repo)
    assert '验收打回 KAN-1' in text
    # pi-gated → 撤销:高
    assert '撤销:高' in text.split('## 决策行')[0]


def test_non_gate_transition_does_not_log(tmp_path):
    repo, relpath = _make_repo(tmp_path, status='todo')
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'in-progress')
    text = _log_text(repo)
    assert 'class:auto-' not in text  # todo→in-progress 不过 gate


def test_missing_decision_log_does_not_break_status_update(tmp_path):
    repo, relpath = _make_repo(tmp_path)
    # 删掉账本，模拟测试根/未初始化环境
    (repo / 'shared' / 'toolkit' / 'governance' / 'DECISION_LOG.md').unlink()
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        ok, _ = scan_mod.update_frontmatter_field(relpath, 'status', 'done')
    assert ok  # 钩子静默跳过，状态更新照常成功
    card_text = (repo / relpath).read_text(encoding='utf-8')
    assert 'status: done' in card_text


def test_external_safety_marks_unbounded_undo(tmp_path):
    repo, relpath = _make_repo(tmp_path, fm_extra='responsibility: pi-gated\nsafety: external\n')
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'done')
    assert '撤销:无界' in _log_text(repo).split('## 决策行')[0]


# ---- 验收自动通过（决策 2026-06-17「按 responsibility 切」）----

def _card_status(repo, relpath):
    text = (repo / relpath).read_text(encoding='utf-8')
    for line in text.splitlines():
        if line.startswith('status:'):
            return line.split(':', 1)[1].strip()
    return ''


def test_eligible_review_auto_passes_to_done(tmp_path):
    repo, relpath = _make_repo(
        tmp_path, status='in-progress',
        fm_extra='responsibility: ai-owned\nsafety: reversible\n',
    )
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'review')
    # ai-owned+reversible → 自动推进到 done，不停在 review 占 Owner 注意力
    assert _card_status(repo, relpath) == 'done'
    text = _log_text(repo)
    pending_zone = text.split('## 自动草稿（待 Owner 追认）', 1)[1].split('## 机器动作（审计，不占 Owner 待批）', 1)[0]
    machine_zone = text.split('## 机器动作（审计，不占 Owner 待批）', 1)[1].split('## 决策行', 1)[0]
    assert 'class:auto-验收机决' in machine_zone
    assert 'class:auto-验收机决' not in pending_zone


def test_pre_execution_gate_does_not_auto_pass(tmp_path):
    # 即便 ai-owned+reversible，next_action 命中执行前 gate 文本 → 必须留给 Owner 拍板
    repo, relpath = _make_repo(
        tmp_path, status='in-progress',
        fm_extra='responsibility: ai-owned\nsafety: reversible\n'
                 'next_action: 方案通过后派 Codex 执行\n',
    )
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'review')
    assert _card_status(repo, relpath) == 'review'        # 仍阻塞
    assert 'class:auto-验收机决' not in _log_text(repo)


def test_pi_gated_review_does_not_auto_pass(tmp_path):
    repo, relpath = _make_repo(
        tmp_path, status='in-progress',
        fm_extra='responsibility: pi-gated\nsafety: reversible\n',
    )
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'review')
    assert _card_status(repo, relpath) == 'review'


def test_missing_responsibility_does_not_auto_pass(tmp_path):
    # 缺字段保守：宁可上呈给 Owner，不误自决
    repo, relpath = _make_repo(tmp_path, status='in-progress', fm_extra='safety: reversible\n')
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'review')
    assert _card_status(repo, relpath) == 'review'


def test_mutating_safety_review_does_not_auto_pass(tmp_path):
    repo, relpath = _make_repo(
        tmp_path, status='in-progress',
        fm_extra='responsibility: ai-owned\nsafety: mutating\n',
    )
    with patch.object(scan_mod, 'REPO_ROOT', repo):
        scan_mod.update_frontmatter_field(relpath, 'status', 'review')
    assert _card_status(repo, relpath) == 'review'


# ---- 存量 review 回扫 sweep ----

def _seed_log(repo):
    gov = repo / 'shared' / 'toolkit' / 'governance'
    gov.mkdir(parents=True, exist_ok=True)
    (gov / 'DECISION_LOG.md').write_text(DECISION_LOG_SEED, encoding='utf-8')


def _write_review_card(repo, name, *, responsibility='', safety='', next_action=''):
    proj = repo / 'project' / '个人调度'
    proj.mkdir(parents=True, exist_ok=True)
    extra = ''
    if responsibility:
        extra += f'responsibility: {responsibility}\n'
    if safety:
        extra += f'safety: {safety}\n'
    if next_action:
        extra += f'next_action: {next_action}\n'
    (proj / name).write_text(
        f"---\ntitle: {name}\ntask_id: {name[:-3]}\nstatus: review\nupdated: 2026-06-01\n{extra}---\n\nBody.\n",
        encoding='utf-8',
    )


def _status_named(repo, name):
    text = (repo / 'project' / '个人调度' / name).read_text(encoding='utf-8')
    for line in text.splitlines():
        if line.startswith('status:'):
            return line.split(':', 1)[1].strip()
    return ''


def _sweep_setup(repo):
    _seed_log(repo)
    _write_review_card(repo, 'KAN-1.md', responsibility='ai-owned', safety='reversible')   # 资格命中
    _write_review_card(repo, 'KAN-2.md', responsibility='pi-gated', safety='reversible')   # pi-gated
    _write_review_card(repo, 'KAN-3.md', responsibility='ai-owned', safety='mutating')     # mutating
    _write_review_card(repo, 'KAN-4.md', responsibility='ai-owned', safety='reversible',
                       next_action='方案通过后派 Codex 执行')                              # 执行前 gate
    _write_review_card(repo, 'KAN-5.md')                                                   # 缺字段


def test_sweep_auto_accepts_only_eligible(tmp_path):
    _sweep_setup(tmp_path)
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        swept = scan_mod.sweep_auto_accept_reviews()
    assert [p.split('/')[-1] for p in swept] == ['KAN-1.md']
    assert _status_named(tmp_path, 'KAN-1.md') == 'done'
    for name in ('KAN-2.md', 'KAN-3.md', 'KAN-4.md', 'KAN-5.md'):
        assert _status_named(tmp_path, name) == 'review'      # 其余原样留给 Owner
    assert 'class:auto-验收机决' in _log_text(tmp_path)


def test_sweep_dry_run_changes_nothing(tmp_path):
    _sweep_setup(tmp_path)
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        swept = scan_mod.sweep_auto_accept_reviews(dry_run=True)
    assert [p.split('/')[-1] for p in swept] == ['KAN-1.md']
    assert _status_named(tmp_path, 'KAN-1.md') == 'review'     # dry-run 不改
    assert 'class:auto-验收机决' not in _log_text(tmp_path)


# ---- 标签推断（AI 推断草稿 + Owner 追认）----

def test_infer_external_signal_is_pi_gated():
    resp, safety, conf, _ = scan_mod._infer_card_labels({'next_action': '晋升场景到 brainloop 并发布'})
    assert resp == 'pi-gated' and conf == 'high'


def test_infer_pre_exec_gate_is_pi_gated():
    resp, _, conf, _ = scan_mod._infer_card_labels({'title': '方案通过后派 Codex 执行'})
    assert resp == 'pi-gated' and conf == 'high'


def test_infer_runtime_domain_is_ai_owned():
    resp, safety, conf, _ = scan_mod._infer_card_labels({'domain': 'ops', 'title': '清理运行态'})
    assert resp == 'ai-owned' and safety == 'reversible'


def test_infer_decision_domain_is_pi_gated():
    resp, _, conf, _ = scan_mod._infer_card_labels({'domain': 'research', 'title': '某分析'})
    assert resp == 'pi-gated'


def test_infer_decision_verb_guard_blocks_ai_owned():
    # 运行层域 + 决策动词 → 护栏降级为留空（防"选篇/分发授权"被误自动通过）
    resp, _, conf, reason = scan_mod._infer_card_labels(
        {'domain': 'ops', 'title': '判断会议材料分发范围'})
    assert resp == '' and '护栏' in reason


def test_infer_uncertain_left_blank():
    # knowledge 域但无运行层关键词、无对外信号 → 留空给 Owner
    resp, _, conf, reason = scan_mod._infer_card_labels({'domain': 'knowledge', 'title': '判断选篇'})
    assert resp == '' and conf == 'low'


def test_infer_apply_writes_high_med_skips_blank_and_labeled(tmp_path):
    _seed_log(tmp_path)
    proj = tmp_path / 'project' / '个人调度'
    proj.mkdir(parents=True, exist_ok=True)
    # 运行层 → 会写 ai-owned
    (proj / 'OPS-1.md').write_text(
        "---\ntitle: 清理运行态\ntask_id: OPS-1\nstatus: todo\ndomain: ops\nupdated: 2026-06-01\n---\n\nx\n",
        encoding='utf-8')
    # 已有标签 → 不动
    (proj / 'KAN-9.md').write_text(
        "---\ntitle: 已标\ntask_id: KAN-9\nstatus: todo\ndomain: ops\nresponsibility: pi-gated\nupdated: 2026-06-01\n---\n\nx\n",
        encoding='utf-8')

    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        rows = scan_mod.infer_responsibility_labels(dry_run=False)

    ops_fm = (proj / 'OPS-1.md').read_text(encoding='utf-8')
    assert 'responsibility: ai-owned' in ops_fm and 'safety: reversible' in ops_fm
    # 已标卡不被覆盖
    assert (proj / 'KAN-9.md').read_text(encoding='utf-8').count('responsibility:') == 1
    assert 'pi-gated' in (proj / 'KAN-9.md').read_text(encoding='utf-8')
    # 返回里 OPS-1 标记已写
    assert any(r[0].endswith('OPS-1.md') and r[5] for r in rows)


# ---- 压缩触发器 ----

def _write_log(repo, body_lines):
    gov = repo / 'shared' / 'toolkit' / 'governance'
    gov.mkdir(parents=True, exist_ok=True)
    (gov / 'DECISION_LOG.md').write_text(
        "# log\n\n## 自动草稿（待 Owner 追认）\n\n_（空）_\n\n## 决策行（倒序）\n\n"
        + '\n'.join(body_lines) + '\n',
        encoding='utf-8')


def test_compression_flags_class_at_threshold(tmp_path):
    _write_log(tmp_path, [
        "- 2026-06-17 · class:验收 · 通过A · 撤销:低 · 来源:x",
        "- 2026-06-16 · class:auto-验收 · 通过B · 撤销:低 · 来源:x",   # auto- 合并计数
        "- 2026-06-15 · class:验收 · 通过C · 撤销:低 · 来源:x",
        "- 2026-06-14 · class:接入取舍 · 单条 · 撤销:中 · 来源:x",     # <3 不冒泡
    ])
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        cands = dict(scan_mod.detect_compression_candidates())
    assert cands.get('验收') == 3
    assert '接入取舍' not in cands


def test_compression_excludes_machine_and_handled(tmp_path):
    _write_log(tmp_path, [
        "- 2026-06-17 · class:auto-验收机决 · 自动A · 撤销:低 · 来源:x",  # 机器,排除
        "- 2026-06-17 · class:auto-验收机决 · 自动B · 撤销:低 · 来源:x",
        "- 2026-06-17 · class:auto-验收机决 · 自动C · 撤销:低 · 来源:x",
        "- 2026-06-16 · class:边界递减 · [META] 委托 链路设计-canonical收敛 · 撤销:中 · 来源:y",
        "- 2026-06-12 · class:链路设计 · a · 撤销:中 · 来源:y",          # 已被上面 meta 压缩
        "- 2026-06-12 · class:链路设计 · b · 撤销:中 · 来源:y",
        "- 2026-06-12 · class:链路设计 · c · 撤销:中 · 来源:y",
    ])
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        cands = dict(scan_mod.detect_compression_candidates())
    assert '验收机决' not in cands            # 机器决策不算 Owner 的同向
    assert '链路设计' not in cands            # 已压缩过,不重复冒泡


def test_compression_excludes_unbounded_class(tmp_path):
    # 护栏:某类够 3 条,但其中一条 撤销:无界 → 整类不冒泡(无界下行不赌)
    _write_log(tmp_path, [
        "- 2026-06-17 · class:外发批准 · 发A · 撤销:无界 · 来源:x",
        "- 2026-06-16 · class:外发批准 · 发B · 撤销:中 · 来源:x",
        "- 2026-06-15 · class:外发批准 · 发C · 撤销:中 · 来源:x",
    ])
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        cands = dict(scan_mod.detect_compression_candidates())
    assert '外发批准' not in cands   # 含无界 → 排除


def test_compression_writes_idempotent_draft(tmp_path):
    _write_log(tmp_path, [
        "- 2026-06-17 · class:执行批准 · A · 撤销:中 · 来源:x",
        "- 2026-06-16 · class:执行批准 · B · 撤销:中 · 来源:x",
        "- 2026-06-15 · class:执行批准 · C · 撤销:中 · 来源:x",
    ])
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
        scan_mod.detect_compression_candidates(dry_run=False)
        scan_mod.detect_compression_candidates(dry_run=False)  # 再跑一次
    text = _log_text(tmp_path)
    assert text.count('压缩候选-执行批准') == 1   # 幂等:只写一次
    assert '[待追认] 压缩候选' in text


# ---- 前沿对标 feeder ----

def _write_plain_card(repo, name, extra=''):
    proj = repo / 'project' / '个人调度'
    proj.mkdir(parents=True, exist_ok=True)
    (proj / name).write_text(
        f"---\ntitle: {name[:-3]}\ntask_id: {name[:-3]}\nstatus: todo\nupdated: 2026-06-01\n{extra}---\n\nbody\n",
        encoding='utf-8')


def test_is_novel_build_field_and_tag():
    assert scan_mod._is_novel_build({'novel_build': 'true'})
    assert scan_mod._is_novel_build({'tags': ['novel-build', 'x']})
    assert not scan_mod._is_novel_build({'tags': ['x']})


def test_feeder_spawns_card_with_source_and_prompt(tmp_path):
    _write_plain_card(tmp_path, 'KAN-7.md', extra='novel_build: true\n')
    _write_plain_card(tmp_path, 'KAN-8.md')  # 非 novel
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        spawned = scan_mod.spawn_prior_art_cards()
    assert [s[0] for s in spawned] == ['KAN-7']
    content = (tmp_path / spawned[0][1]).read_text(encoding='utf-8')
    assert 'source: prior-art-scan/KAN-7' in content
    assert 'Deep Research' in content and '前沿对标' in content


def test_feeder_is_idempotent(tmp_path):
    _write_plain_card(tmp_path, 'KAN-7.md', extra='novel_build: true\n')
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        first = scan_mod.spawn_prior_art_cards()
        second = scan_mod.spawn_prior_art_cards()
    assert len(first) == 1 and second == []


def test_spawn_for_card_creates_and_is_idempotent(tmp_path):
    _write_plain_card(tmp_path, 'KAN-7.md')  # 按钮即显式触发，不要求 novel_build
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        res1, st1 = scan_mod.spawn_prior_art_for_card('project/个人调度/KAN-7.md')
        res2, st2 = scan_mod.spawn_prior_art_for_card('project/个人调度/KAN-7.md')
    assert st1 == 200 and res1['ok'] and not res1['already']
    content = (tmp_path / res1['path']).read_text(encoding='utf-8')
    assert 'source: prior-art-scan/KAN-7' in content and 'Deep Research' in content
    # 第二次点同一张卡 → 返回旧卡，不重复创建
    assert res2['ok'] and res2['already'] and res2['path'] == res1['path']


def test_spawn_for_card_rejects_bad_path(tmp_path):
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        res, st = scan_mod.spawn_prior_art_for_card('project/个人调度/不存在.md')
    assert not res['ok'] and st in (400, 403, 404)


def test_feeder_dry_run_creates_nothing(tmp_path):
    _write_plain_card(tmp_path, 'KAN-7.md', extra='novel_build: true\n')
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        spawned = scan_mod.spawn_prior_art_cards(dry_run=True)
    assert spawned == [('KAN-7', '(dry-run)')]
    # 只有原始 1 张卡，没有新建
    assert len(list((tmp_path / 'project' / '个人调度').glob('*.md'))) == 1


def test_infer_dry_run_writes_nothing(tmp_path):
    _seed_log(tmp_path)
    proj = tmp_path / 'project' / '个人调度'
    proj.mkdir(parents=True, exist_ok=True)
    (proj / 'OPS-1.md').write_text(
        "---\ntitle: 清理\ntask_id: OPS-1\nstatus: todo\ndomain: ops\nupdated: 2026-06-01\n---\n\nx\n",
        encoding='utf-8')
    with patch.object(scan_mod, 'REPO_ROOT', tmp_path), \
         patch.object(scan_mod, 'SCAN_DIRS', ['project']), \
         patch.object(scan_mod, 'load_config', return_value={}):
        scan_mod.infer_responsibility_labels(dry_run=True)
    assert 'responsibility:' not in (proj / 'OPS-1.md').read_text(encoding='utf-8')
