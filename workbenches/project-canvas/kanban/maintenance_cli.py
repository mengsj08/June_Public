"""维护命令群（maintenance_cli）——单体手术第 1 批搬出（MONOLITH_MAP 领地①）。

纯移动零行为改动：函数体逐字来自 scan-docs.py（2026-07-08，源区 L3013-3135 与 L7509-7842），
唯一改写 = 单体内部依赖显式经 `env` 参数注入（env = 加载后的 scan-docs 模块对象）。
scan-docs 侧保留同名委托桩，CLI/端点/测试的调用面完全不变。

env 依赖清单（只读引用，调用时取现值，与原全局读取语义一致）：
  scan_all, _duplicate_task_id_issues, _legacy_task_id_collision_issues,
  _execution_result_section_text, _is_empty_execution_result_text, _naming_issue_base,
  is_dispatch_project, ACTIVE_TASK_STATUSES, normalize_task_family,
  infer_task_family_for_doc, TASK_FAMILY_PREFIXES, _task_id_prefix, SCAN_DIRS,
  DISPATCH_PROJECT_NAMES, MARKDOWN_WRITE_LOCK, REPO_ROOT, _console_routing_text,
  _PRE_EXEC_GATE_RE, infer_task_domain, extract_frontmatter, update_frontmatter_field,
  create_document, _decision_log_path, _append_decision_log_draft,
  _resolve_active_task_card_path, _is_auto_acceptance_eligible, _record_auto_acceptance
"""
import os
import re
from datetime import datetime, timedelta


# ── 命名治理巡检 ──────────────────────────────────────────────────────────

def build_naming_lint_report(env, all_docs=None, *, active_only=True, include_body=True):
    """Return a read-only naming lint report for personal dispatch cards."""
    docs = list(all_docs) if all_docs is not None else env.scan_all()
    issues = []
    issues.extend(env._duplicate_task_id_issues(docs))
    issues.extend(env._legacy_task_id_collision_issues(docs))
    skipped_inactive = 0
    for doc in docs:
        status = str(doc.get('status') or '').strip().lower()
        if status in {'done', 'review'}:
            execution_text, has_section = env._execution_result_section_text(doc)
            if env._is_empty_execution_result_text(execution_text):
                issue = env._naming_issue_base(doc, 'empty_execution_result', 'warning')
                issue.update({
                    'has_execution_result_section': has_section,
                    'message': '卡已 done/review 但执行结果未回填',
                })
                issues.append(issue)

        if not env.is_dispatch_project(doc.get('project', '')):
            continue
        if active_only and status not in env.ACTIVE_TASK_STATUSES:
            skipped_inactive += 1
            continue

        family = env.normalize_task_family(doc.get('task_family', ''))
        inferred = env.infer_task_family_for_doc(doc, include_body=include_body)
        inferred = '' if inferred == 'legacy' else inferred
        if not family:
            issue = env._naming_issue_base(doc, 'missing_task_family', 'error')
            issue['inferred_task_family'] = inferred
            issue['requires_confirmation'] = not bool(inferred)
            if inferred:
                issue['suggested_task_family'] = inferred
                issue['expected_prefix_after_backfill'] = env.TASK_FAMILY_PREFIXES.get(inferred, '')
            issues.append(issue)
            continue

        if family not in env.TASK_FAMILY_PREFIXES:
            issue = env._naming_issue_base(doc, 'unknown_task_family', 'error')
            issue['raw_task_family'] = doc.get('task_family', '')
            issues.append(issue)
            continue

        task_id = str(doc.get('task_id') or '').strip()
        actual_prefix = env._task_id_prefix(task_id)
        expected_prefix = env.TASK_FAMILY_PREFIXES[family]
        if actual_prefix and actual_prefix != expected_prefix:
            is_legacy_prefix = actual_prefix == env.TASK_FAMILY_PREFIXES['legacy']
            issue_type = 'legacy_prefix_migratable' if is_legacy_prefix else 'prefix_family_mismatch'
            issue = env._naming_issue_base(doc, issue_type, 'warning' if is_legacy_prefix else 'error')
            issue.update({
                'expected_prefix': expected_prefix,
                'actual_prefix': actual_prefix,
                'migration_kind': issue_type if is_legacy_prefix else 'wrong_prefix',
                'migratable': True,
            })
            issues.append(issue)

    summary = {
        'issues': len(issues),
        'errors': sum(1 for issue in issues if issue.get('severity') == 'error'),
        'warnings': sum(1 for issue in issues if issue.get('severity') == 'warning'),
        'duplicate_task_id': sum(1 for issue in issues if issue.get('type') == 'duplicate_task_id'),
        'legacy_task_id_collision': sum(1 for issue in issues if issue.get('type') == 'legacy_task_id_collision'),
        'empty_execution_result': sum(1 for issue in issues if issue.get('type') == 'empty_execution_result'),
        'missing_task_family': sum(1 for issue in issues if issue.get('type') == 'missing_task_family'),
        'prefix_family_mismatch': sum(1 for issue in issues if issue.get('type') == 'prefix_family_mismatch'),
        'legacy_prefix_migratable': sum(1 for issue in issues if issue.get('type') == 'legacy_prefix_migratable'),
        'unknown_task_family': sum(1 for issue in issues if issue.get('type') == 'unknown_task_family'),
        'skipped_inactive_dispatch_cards': skipped_inactive,
    }
    return {
        'ok': not issues,
        'scope': {
            'scan_dirs': list(env.SCAN_DIRS),
            'dispatch_projects': sorted(env.DISPATCH_PROJECT_NAMES),
            'active_only': active_only,
            'active_statuses': sorted(env.ACTIVE_TASK_STATUSES),
        },
        'summary': summary,
        'issues': issues,
    }


def format_naming_lint_report(env, report):
    summary = report.get('summary') or {}
    lines = [
        (
            f"命名 lint: {summary.get('issues', 0)} 个问题 "
            f"({summary.get('errors', 0)} error, {summary.get('warnings', 0)} warning)"
        )
    ]
    if not report.get('issues'):
        lines.append("未发现活跃 dispatch 卡命名问题。")
        return '\n'.join(lines)
    for issue in report['issues']:
        marker = 'ERROR' if issue.get('severity') == 'error' else 'WARN'
        task = issue.get('task_id') or '(no task_id)'
        path = issue.get('path') or ''
        if issue.get('type') == 'duplicate_task_id':
            paths = ', '.join(issue.get('paths') or [])
            lines.append(f"- [{marker}] duplicate_task_id {task}: {paths}")
        elif issue.get('type') == 'legacy_task_id_collision':
            legacy_id = issue.get('legacy_id') or ''
            paths = ', '.join(issue.get('colliding_task_id_paths') or [])
            lines.append(f"- [{marker}] legacy_task_id_collision {task} {path}: legacy_id {legacy_id} -> {paths}")
        elif issue.get('type') == 'empty_execution_result':
            lines.append(f"- [{marker}] empty_execution_result {task} {path}: 卡已 {issue.get('status')} 但执行结果未回填")
        elif issue.get('type') == 'missing_task_family':
            suggestion = issue.get('suggested_task_family') or '需人工确认'
            lines.append(f"- [{marker}] missing_task_family {task} {path} -> {suggestion}")
        elif issue.get('type') in ('prefix_family_mismatch', 'legacy_prefix_migratable'):
            expected = issue.get('expected_prefix') or '?'
            actual = issue.get('actual_prefix') or '?'
            kind = issue.get('migration_kind') or 'wrong_prefix'
            lines.append(f"- [{marker}] {issue.get('type')} {task} {path}: {actual} != {expected} ({kind})")
        elif issue.get('type') == 'unknown_task_family':
            lines.append(f"- [{marker}] unknown_task_family {task} {path}: {issue.get('raw_task_family')}")
        else:
            lines.append(f"- [{marker}] {issue.get('type')} {task} {path}")
    return '\n'.join(lines)


# ── 归档维护 ─────────────────────────────────────────────────────────────

def archive_done_tasks(env, days=7):
    """维护命令：把 done 超过 N 天的任务卡移入所在项目的 .archive/ 子目录。

    扫描器跳过 `.` 开头目录，所以归档卡从面板消失但完整保留在 git 里。
    这是 feeder 约定的回流闭环：面板上只保留活水，历史可追溯。
    幂等：目标已存在则跳过；时间戳取 updated（缺省 created），无法解析则不动。
    """
    cutoff = datetime.now() - timedelta(days=days)
    moved = []
    with env.MARKDOWN_WRITE_LOCK:
        for doc in env.scan_all():
            if str(doc.get('status') or '').strip() != 'done':
                continue
            stamp = str(doc.get('updated') or doc.get('created') or '').strip()[:10]
            try:
                when = datetime.strptime(stamp, '%Y-%m-%d')
            except ValueError:
                continue
            if when > cutoff:
                continue
            src = env.REPO_ROOT / doc['path']
            if not src.exists():
                continue
            archive_dir = src.parent / '.archive'
            archive_dir.mkdir(exist_ok=True)
            dest = archive_dir / src.name
            if dest.exists():
                continue
            os.replace(src, dest)
            env.invalidate_scan_cache(src)
            env.invalidate_scan_cache(dest)
            moved.append((doc['path'], str(dest.relative_to(env.REPO_ROOT))))
    return moved


# ── 标签推断（决策 2026-06-17「AI 推断草稿 + Owner 追认」）──────────────────
# 保守：只对高/中置信正向打标，拿不准留空给 Owner（不臆造）。dry-run 预览即追认闸。
_EXTERNAL_AUTH_RE = re.compile(
    r'晋升|promote|发布|publish|对外|团队|handoff|交接|客户|customer|凭据|secret|密钥|'
    r'\bkey\b|canonical|\bmerge\b|合并|删除|\bdelete\b|轮换|\bpush\b|飞书|feishu',
    re.IGNORECASE,
)
_RUNTIME_SIGNAL_RE = re.compile(
    r'账本|ledger|lint|扫描|scan|巡检|预筛|去重|dedup|草稿|draft|核对|计数|counter|'
    r'元数据|metadata|归档|archive|体检|health',
    re.IGNORECASE,
)
# 决策动词护栏——标题/正文含 Owner 的判断动词时，绝不推成 ai-owned（防"选篇/分发授权"被误自动通过）。
_DECISION_VERB_RE = re.compile(
    r'判断|筛选|选篇|审核|拍板|决定|确认|评审|定夺|取舍|批准|授权|梳理|链路设计',
    re.IGNORECASE,
)


def _infer_card_labels(env, fm, *, project='', path=''):
    """推断单卡 (responsibility, safety, 置信, 理由)。responsibility=='' 表示留空给 Owner。"""
    text = env._console_routing_text(fm) + ' ' + str(fm.get('workdir') or '')
    if _EXTERNAL_AUTH_RE.search(text):
        return ('pi-gated', '', 'high', '对外/授权信号')
    if env._PRE_EXEC_GATE_RE.search(text):
        return ('pi-gated', '', 'high', '执行前 gate')
    domain = ''
    try:
        domain = env.infer_task_domain(fm, project=project, path=path)
    except Exception:
        domain = ''
    if domain in ('ops', 'documents'):
        result = ('ai-owned', 'reversible', 'high', f'运行层域({domain})')
    elif domain in ('chain', 'scenario', 'research', 'skill'):
        result = ('pi-gated', '', 'medium', f'对外/决策域({domain})')
    elif domain in ('governance', 'knowledge'):
        if _RUNTIME_SIGNAL_RE.search(text):
            result = ('ai-owned', 'reversible', 'medium', f'{domain}运行层信号')
        else:
            result = ('', '', 'low', f'{domain}域需人判，留空')
    else:
        result = ('', '', 'low', '默认留给 Owner')
    # 护栏：含决策动词的卡绝不 ai-owned → 降级留给 Owner（防误自动通过）
    if result[0] == 'ai-owned' and _DECISION_VERB_RE.search(text):
        return ('', '', 'low', '含决策动词，留人判（护栏）')
    return result


def infer_responsibility_labels(env, dry_run=True):
    """给缺 responsibility 的活动卡推断标签草稿。
    dry_run 只报不写；apply 仅写高/中置信且 responsibility 非空者，且不覆盖已有字段。
    返回 [(path, responsibility, safety, 置信, 理由, 是否已写)]。"""
    results = []
    for doc in env.scan_all():
        path = doc.get('path')
        if not path:
            continue
        fpath = env.REPO_ROOT / path
        if not fpath.exists():
            continue
        try:
            fm, _ = env.extract_frontmatter(fpath.read_text(encoding='utf-8'))
        except OSError:
            continue
        if str(fm.get('responsibility') or '').strip():
            continue  # 已有标签不动
        resp, safety, conf, reason = _infer_card_labels(
            env, fm, project=doc.get('project', ''), path=path)
        wrote = False
        if not dry_run and resp and conf in ('high', 'medium'):
            if env.update_frontmatter_field(path, 'responsibility', resp)[0]:
                if safety and not str(fm.get('safety') or '').strip():
                    env.update_frontmatter_field(path, 'safety', safety)
                wrote = True
        results.append((path, resp, safety, conf, reason, wrote))
    return results


# ── 前沿对标 feeder（决策 2026-06-17「轻量 feeder + prompt 模板」）──────────
# 卡标 novel_build: true 即自动产一张「前沿对标」卡，正文填好参数化的 deep-research
# prompt，进收件箱待 Owner 分流。触发反射化（trigger-model-judge：别靠人记得做前沿对标）。

def _is_novel_build(fm):
    if str(fm.get('novel_build') or '').strip().lower() in ('true', 'yes', '1', '是'):
        return True
    tags = fm.get('tags')
    tag_text = ' '.join(tags) if isinstance(tags, list) else str(tags or '')
    return 'novel-build' in tag_text.lower()


def _build_prior_art_prompt(fm):
    """用源卡上下文参数化 deep-research prompt，作为对标卡正文。"""
    title = str(fm.get('title') or '').strip()
    task_id = str(fm.get('task_id') or '').strip()
    workdir = str(fm.get('workdir') or '').strip()
    return f"""## 背景 / 来源
对标对象：**{title}**（源卡 {task_id}，workdir `{workdir}`）。
下面是给 ChatGPT Deep Research 的 prompt 草稿——发之前把「What I built」一节按本次实际补全。

## 要做什么
把下面整段贴进 ChatGPT 的 Deep Research，扫现有工具/框架/论文，判断「自建 vs 采用 vs 采用并扩展」。

## Deep Research Prompt（可直接复制）
```
# Deep Research: prior art for "{title}"

## Context — what I built (FILL IN specifics before sending)
{title}. {{用 1–3 句补全：它做了什么、解决什么痛点、关键机制是规则/学习/LLM}}

## What I want
Find existing tools, products, frameworks, and academic work that already implement
part — or ideally the combination — of the above. Tell me whether to adopt/extend
something vs keep building my own.

## Probe these areas (not limited to)
- domain-specific SaaS / OSS tools that do this;
- agentic frameworks with human-in-the-loop / gated execution;
- relevant HCI / ML / systems research and its standard terminology;
- local-first / self-hostable analogues.

## For each relevant find, report
- name, link, OSS/self-hostable?, maturity, local-first?;
- which capabilities it covers and which it does NOT;
- whether its logic is rule-based, learned, or LLM-judged;
- how close it is to the full combination I described.

## Deliverable
1. comparison table of the closest 8–15 matches vs my capabilities;
2. the 3 closest "could I just use this?" candidates, with honest gaps;
3. capabilities that appear genuinely unaddressed (white space);
4. key academic terms to search further;
5. verdict: build vs adopt vs adopt-and-extend, with reasoning.
Prioritize precision over breadth; separate truly-comparable from merely-adjacent.
```

## 完成标准
- [ ] prompt 的「What I built」已按本次补全
- [ ] ChatGPT Deep Research 结论已贴回本卡
- [ ] 给出 build / adopt / adopt-and-extend 结论
"""


def spawn_prior_art_cards(env, dry_run=False, project='个人调度'):
    """扫活动卡，对标 novel_build 的卡自动产「前沿对标」卡（幂等：source=prior-art-scan/<task_id>）。
    返回 [(源task_id, 新卡路径或'(dry-run)')]。"""
    existing_sources = set()
    triggers = []
    for doc in env.scan_all():
        path = doc.get('path')
        if not path:
            continue
        fpath = env.REPO_ROOT / path
        if not fpath.exists():
            continue
        try:
            fm, _ = env.extract_frontmatter(fpath.read_text(encoding='utf-8'))
        except OSError:
            continue
        src = str(fm.get('source') or '').strip()
        if src.startswith('prior-art-scan/'):
            existing_sources.add(src)  # 已是对标卡，不再触发
            continue
        if _is_novel_build(fm):
            triggers.append(fm)
    spawned = []
    for fm in triggers:
        task_id = str(fm.get('task_id') or fm.get('legacy_id') or '').strip()
        if not task_id:
            continue
        source_key = f"prior-art-scan/{task_id}"
        if source_key in existing_sources:
            continue  # 幂等：已产过
        if dry_run:
            spawned.append((task_id, '(dry-run)'))
            continue
        title = f"前沿对标: {str(fm.get('title') or task_id)}"
        ok, newpath, _ = env.create_document(project, title, '', '中', body=_build_prior_art_prompt(fm))
        if ok:
            env.update_frontmatter_field(newpath, 'source', source_key)
            existing_sources.add(source_key)
            spawned.append((task_id, newpath))
    return spawned


def spawn_prior_art_for_card(env, path):
    """看板按钮入口：为指定卡产一张「前沿对标」卡（幂等）。返回 (result, status)。
    与 feeder 同一产物，只是按需单发而非扫全量，且不要求 novel_build 标记（按钮即显式触发）。"""
    candidate, rel_path, err, status = env._resolve_active_task_card_path(path)
    if err:
        return {'ok': False, 'error': err}, status
    try:
        fm, _ = env.extract_frontmatter(candidate.read_text(encoding='utf-8'))
    except OSError as exc:
        return {'ok': False, 'error': str(exc)}, 500
    task_id = str(fm.get('task_id') or fm.get('legacy_id') or '').strip()
    if not task_id:
        return {'ok': False, 'error': '源卡缺 task_id，无法建幂等键'}, 400
    source_key = f"prior-art-scan/{task_id}"
    for doc in env.scan_all():  # 幂等：已产过就返回旧卡
        dpath = doc.get('path')
        if not dpath:
            continue
        try:
            dfm, _ = env.extract_frontmatter((env.REPO_ROOT / dpath).read_text(encoding='utf-8'))
        except OSError:
            continue
        if str(dfm.get('source') or '').strip() == source_key:
            return {'ok': True, 'already': True, 'path': dpath, 'task_id': task_id}, 200
    title = f"前沿对标: {str(fm.get('title') or task_id)}"
    ok, newpath, new_id = env.create_document('个人调度', title, '', '中', body=_build_prior_art_prompt(fm))
    if not ok:
        return {'ok': False, 'error': newpath}, 500
    env.update_frontmatter_field(newpath, 'source', source_key)
    return {'ok': True, 'already': False, 'path': newpath, 'task_id': new_id}, 200


# ── 压缩触发器（边界递减闭环最后一环）────────────────────────────────────
# 数 DECISION_LOG 里 Owner 的同类决策，≥N 条冒泡"以后这类我自决?"。
# 排除机器决策(验收机决)与已压缩/已冒泡过的类(幂等)。
_COMPRESSION_EXCLUDE_CLASSES = {'验收机决', '边界递减', '行为追踪'}
_DECISION_LINE_RE = re.compile(r'^-\s*(\d{4}-\d{2}-\d{2})\s*·\s*class:([^\s·]+)')
_UNDO_COST_RE = re.compile(r'撤销[:：]\s*([^\s·]+)')


def detect_compression_candidates(env, min_count=3, dry_run=True):
    """扫 DECISION_LOG，返回 [(class, 计数)]，≥min_count 且未被压缩/冒泡过。
    非 dry_run 时把新候选写进「待追认」区（幂等：已有同类候选/已压缩则不写）。
    class 是"同向"的代理——真同向需 Owner 判，候选只提示"去看看这类够不够同向"。
    护栏（v3「无界下行不赌」）：任何 class 只要有一条决策标 `撤销:无界`，整类永不进压缩候选
    ——只对可逆决策授权自决，绝不建议把不可收回的动作(写客户/发布/动钱/删)交给 agent。"""
    log_path = env._decision_log_path()
    if not log_path.exists():
        return []
    text = log_path.read_text(encoding='utf-8')
    # Drafts and machine receipts are not Owner decisions and must not train
    # future delegation. Only the formal decision section is evidence.
    confirmed_text = text.split('## 决策行（倒序）', 1)[1] if '## 决策行（倒序）' in text else ''
    lines = confirmed_text.splitlines()
    # 已压缩/已冒泡过的类（出现在 边界递减 meta 行或 压缩候选 行里的）→ 不再重复冒泡
    handled_blob = '\n'.join(
        ln for ln in lines if 'class:边界递减' in ln or 'class:压缩候选-' in ln)
    counts = {}
    unbounded_classes = set()
    for ln in lines:
        m = _DECISION_LINE_RE.match(ln.strip())
        if not m:
            continue
        cls = m.group(2)
        if cls.startswith('auto-'):
            cls = cls[len('auto-'):]           # auto-验收 与 验收 合并计数（都是 Owner 验收决策）
        if cls.startswith('压缩候选-') or cls in _COMPRESSION_EXCLUDE_CLASSES:
            continue
        um = _UNDO_COST_RE.search(ln)
        if um and um.group(1).strip() == '无界':
            unbounded_classes.add(cls)         # 护栏：此类含无界动作，整类禁止冒泡自决
        counts[cls] = counts.get(cls, 0) + 1
    candidates = [
        (cls, n) for cls, n in counts.items()
        if n >= min_count and cls not in handled_blob and cls not in unbounded_classes
    ]
    candidates.sort(key=lambda x: -x[1])
    if not dry_run:
        appended = text
        for cls, n in candidates:
            marker = f"压缩候选-{cls}"
            if marker in appended:
                continue                       # 幂等
            today = datetime.now().strftime('%Y-%m-%d')
            line = (
                f"- {today} · class:{marker} · [待追认] 压缩候选: «{cls}» 已累计 {n} 条同类决策，"
                f"核对是否同向 → 以后这类我自决? · 撤销:中 · 来源:压缩触发器"
            )
            env._append_decision_log_draft(line)
            appended += '\n' + line             # 防同一次运行内重复写
    return candidates


# ── 存量 review 回扫 ─────────────────────────────────────────────────────

def sweep_auto_accept_reviews(env, dry_run=False):
    """一次性回扫：把存量已躺在 review 且符合自动通过资格的卡推进到 done + 机决落账。
    资格同 _is_auto_acceptance_eligible（ai-owned + read-only/reversible，非执行前 gate）；
    缺 responsibility/safety 字段的卡一律不动（保守，留给 Owner）。dry_run 只报不改。
    不跨循环持 MARKDOWN_WRITE_LOCK——update_frontmatter_field 内部自锁且 Lock 非重入。"""
    swept = []
    for doc in env.scan_all():
        if str(doc.get('status') or '').strip().lower() != 'review':
            continue
        path = doc.get('path')
        if not path:
            continue
        fpath = env.REPO_ROOT / path
        if not fpath.exists():
            continue
        try:
            fm, _ = env.extract_frontmatter(fpath.read_text(encoding='utf-8'))
        except OSError:
            continue
        if not env._is_auto_acceptance_eligible(fm):
            continue
        if dry_run:
            swept.append(path)
            continue
        if env.update_frontmatter_field(path, 'status', 'done', _suppress_decision_log=True)[0]:
            env._record_auto_acceptance(fm)
            swept.append(path)
    return swept
