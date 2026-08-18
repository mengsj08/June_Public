"""晋升流（promote_flow）——单体手术第 2 批搬出（MONOLITH_MAP 领地②）。

纯移动零行为改动：函数体逐字来自 scan-docs.py（2026-07-08，源区 L2454-2713），
唯一改写 = 单体内部依赖显式经 `env` 注入（env = 单体 globals() 活代理）。
scan-docs 侧保留委托桩（公开三函数 + 测试/单体引用的私有名 + 常量别名）。

env 依赖：_DEFAULTS, REPO_ROOT, _single_line_scalar, SCENARIO_SKELETON_SECTIONS,
PROMOTE_SLUG_RE, _read_task_file, load_config, update_frontmatter_field,
extract_frontmatter, _path_is_relative_to, _llm_chat
"""
import os
import re
from datetime import datetime
from pathlib import Path


def _resolve_brainloop_scenarios_dir(env, config):
    configured = config.get('brainloop_scenarios_dir') or env._DEFAULTS['brainloop_scenarios_dir']
    if not str(configured or '').strip():
        return None
    expanded = Path(os.path.expanduser(str(configured)))
    if expanded.is_absolute():
        target_dir = expanded
    else:
        target_dir = env.REPO_ROOT / expanded
    return target_dir.resolve()

def _build_scenario_draft(env, slug, source_fm):
    today = datetime.now().strftime('%Y-%m-%d')
    title = env._single_line_scalar(source_fm.get('title', ''))
    task_id = env._single_line_scalar(source_fm.get('task_id', ''))
    workdir = env._single_line_scalar(source_fm.get('workdir', ''))
    source_path = env._single_line_scalar(source_fm.get('source_path') or source_fm.get('workdir', ''))
    frontmatter = [
        '---',
        'kind: scenario',
        f'slug: {slug}',
        f'title: {title}',
        'short_title:',
        'cover_image:',
        'status: draft',
        'maturity: Co-create',
        f'updated: {today}',
        'visibility: team',
        'part_type:',
        'industry:',
        'department:',
        'process_stage:',
        'target_roles: []',
        'related_skills: []',
        '# 待填写：按 Skill Board 真实登记做强匹配；无强匹配时保持空。',
        'tags: []',
        f'source_path: {source_path}',
        f'promoted_from: {task_id}',
        'workdir:',
        f'kanban_task_id: {task_id}',
        '---',
    ]
    body = []
    for section in env.SCENARIO_SKELETON_SECTIONS:
        body.append(f'## {section}')
        body.append('')
        body.append('待填写。')
        body.append('')
    return '\n'.join(frontmatter) + '\n\n' + '\n'.join(body).rstrip() + '\n'

def _validate_promote_source_fields(env, source_fm):
    source = env._single_line_scalar(source_fm.get('source') or '')
    if source.startswith('meeting-chain/') and not env._single_line_scalar(source_fm.get('source_path') or ''):
        return '会议链候选卡晋升前必须填写 source_path'
    return ''

def promote_task_to_scenario(env, path, slug):
    """Create a draft scenario in brainloop-lite, then backfill the source task.

    This intentionally writes across repository boundaries: the scenario file lives
    in the sibling brainloop-lite git repository. It does not update brainloop DB
    state and does not publish the scenario.
    """
    if not slug or not env.PROMOTE_SLUG_RE.fullmatch(str(slug)):
        return {'ok': False, 'error': 'slug 必须是英文 kebab-case'}, 400
    if '..' in path or path.startswith('/'):
        return {'ok': False, 'error': '非法路径'}, 400
    task_file, err = env._read_task_file(path)
    if not task_file:
        return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400
    source_err = _validate_promote_source_fields(env, task_file['frontmatter'])
    if source_err:
        return {'ok': False, 'error': source_err}, 400

    scenarios_dir = _resolve_brainloop_scenarios_dir(env, env.load_config())
    if scenarios_dir is None:
        return {'ok': False, 'error': '场景库集成未配置'}, 404
    try:
        scenarios_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {'ok': False, 'error': f'创建场景目录失败: {e}'}, 500
    scenario_path = (scenarios_dir / f'{slug}.md').resolve()
    try:
        scenario_path.relative_to(scenarios_dir)
    except ValueError:
        return {'ok': False, 'error': '非法场景路径'}, 400
    if scenario_path.exists():
        return {'ok': False, 'error': f'场景已存在: {slug}'}, 200

    try:
        with open(scenario_path, 'x', encoding='utf-8') as f:
            f.write(_build_scenario_draft(env, slug, task_file['frontmatter']))
    except FileExistsError:
        return {'ok': False, 'error': f'场景已存在: {slug}'}, 200
    except OSError as e:
        return {'ok': False, 'error': f'写入场景草稿失败: {e}'}, 500

    ok, msg = env.update_frontmatter_field(path, 'promoted_to', slug)[:2]
    if not ok:
        return {'ok': False, 'error': f'回填 promoted_to 失败: {msg}'}, 500
    ok, msg = env.update_frontmatter_field(path, 'scenario_slug', slug)[:2]
    if not ok:
        return {'ok': False, 'error': f'回填 scenario_slug 失败: {msg}'}, 500

    return {'ok': True, 'slug': slug, 'scenario_path': str(scenario_path)}, 200

def _scenario_slug_from_task_fm(env, fm):
    return env._single_line_scalar(fm.get('scenario_slug') or fm.get('promoted_to') or '')

def _resolve_scenario_path(env, slug, config=None):
    if not slug or not env.PROMOTE_SLUG_RE.fullmatch(str(slug)):
        return None, '缺少有效场景 slug', 400
    scenarios_dir = _resolve_brainloop_scenarios_dir(env, config or env.load_config())
    if scenarios_dir is None:
        return None, '场景库集成未配置', 404
    scenario_path = (scenarios_dir / f'{slug}.md').resolve()
    if not env._path_is_relative_to(scenario_path, scenarios_dir):
        return None, '非法场景路径', 400
    return scenario_path, None, 200

def _normalize_scenario_sections(env, text):
    raw = str(text or '').strip()
    stripped = raw.lstrip()
    fm, fm_block = env.extract_frontmatter(stripped)
    if fm_block and fm:
        raw = stripped[len(fm_block):].strip()
    first_heading = raw.find('## ')
    if first_heading > 0:
        raw = raw[first_heading:].strip()

    normalized = []
    for index, section in enumerate(env.SCENARIO_SKELETON_SECTIONS):
        pattern = re.compile(
            r'(?:^|\n)##\s+' + re.escape(section) + r'\s*\n([\s\S]*?)(?=\n##\s+|$)'
        )
        match = pattern.search(raw)
        content = match.group(1).strip() if match else '待填写。'
        normalized.append(f'## {section}\n\n{content}')
    return '\n\n'.join(normalized).rstrip() + '\n'

PROMOTE_FILL_BODY_MAX_CHARS = 4000
PROMOTE_FILL_ALLOWED_SECTIONS = ('背景 / 来源', '要做什么', '输入与材料', '完成标准')

def _redact_prompt_local_paths(text):
    redacted = re.sub(r'(?<!\w)/Users/[^\s`，。；、)）\]\n]+', '[本机路径已省略]', str(text or ''))
    redacted = re.sub(r'(?<!\w)~/[^\s`，。；、)）\]\n]+', '[本机路径已省略]', redacted)
    redacted = re.sub(r'[A-Za-z]:\\[^\s`，。；、)）\]\n]+', '[本机路径已省略]', redacted)
    return redacted

def _promote_fill_task_brief(body):
    raw = str(body or '')
    sections = []
    for heading in PROMOTE_FILL_ALLOWED_SECTIONS:
        pattern = re.compile(
            r'(?:^|\n)##\s+' + re.escape(heading) + r'\s*\n([\s\S]*?)(?=\n##\s+|$)'
        )
        match = pattern.search(raw)
        if match:
            content = match.group(1).strip()
            if content:
                sections.append(f'## {heading}\n{content}')
    if sections:
        brief = '\n\n'.join(sections)
    else:
        brief = re.split(r'(?:^|\n)##\s+执行结果\s*\n', raw, maxsplit=1)[0].strip()
    brief = _redact_prompt_local_paths(brief)
    if len(brief) > PROMOTE_FILL_BODY_MAX_CHARS:
        brief = brief[:PROMOTE_FILL_BODY_MAX_CHARS].rstrip() + '\n\n[已截断，避免发送过长或过细的卡片正文]'
    return brief

def _build_promote_fill_messages(env, slug, task_file):
    fm = task_file['frontmatter']
    title = env._single_line_scalar(fm.get('title', ''))
    task_id = env._single_line_scalar(fm.get('task_id', ''))
    body = _promote_fill_task_brief(task_file['body'])
    headings = '\n'.join(f'- ## {section}' for section in env.SCENARIO_SKELETON_SECTIONS)
    system_prompt = (
        '你是客户层场景库草稿助手。只输出 Markdown 正文，不输出 frontmatter。'
        '必须严格包含并仅包含指定的 8 个二级标题，标题顺序不可变。'
        '内容只写客户可见的业务层描述，不写内部实现细节、涉密信息、客户转录原文、私有路径或本机路径。'
        '不要提及 API key、配置文件、个人目录、仓库路径。status 必须保持 draft，因此不要输出 status 字段。'
    )
    user_prompt = f"""请基于下面任务卡，填充场景草稿正文。

场景 slug: {slug}
任务标题: {title}
任务 ID: {task_id}

必须输出这些 8 小节:
{headings}

任务 brief（已剔除执行结果并脱敏本机路径；信息不足时保持待补，不要编造）:
{body}
"""
    return [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]

PROMOTE_FILL_NON_DRAFT_ERROR = '场景非 draft，拒绝 AI 填充（避免覆盖已发布/评审中的场景）'

def _read_draft_scenario_file(env, scenario_path):
    try:
        raw = scenario_path.read_text(encoding='utf-8')
    except OSError as e:
        return None, None, f'读取场景草稿失败: {e}', 500
    fm, fm_block = env.extract_frontmatter(raw)
    if not fm_block:
        return None, None, '场景草稿缺少 frontmatter', 400
    if str(fm.get('status') or '').strip() != 'draft':
        return None, None, PROMOTE_FILL_NON_DRAFT_ERROR, 409
    return raw, fm_block, None, 200

def promote_fill_preview(env, path):
    if '..' in path or path.startswith('/'):
        return {'ok': False, 'error': '非法路径'}, 400
    task_file, err = env._read_task_file(path)
    if not task_file:
        return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400

    slug = _scenario_slug_from_task_fm(env, task_file['frontmatter'])
    scenario_path, path_err, path_status = _resolve_scenario_path(env, slug)
    if path_err:
        return {'ok': False, 'error': path_err}, path_status
    if not scenario_path.exists():
        return {'ok': False, 'error': f'场景草稿不存在: {slug}'}, 404
    _, _, scenario_err, scenario_status = _read_draft_scenario_file(env, scenario_path)
    if scenario_err:
        return {'ok': False, 'error': scenario_err}, scenario_status

    messages = _build_promote_fill_messages(env, slug, task_file)
    ok, content = env._llm_chat('deepseek', messages, max_tokens=1800, temperature=0.4)
    if not ok:
        return {'ok': False, 'error': content}, 400
    preview = _normalize_scenario_sections(env, content)
    return {'ok': True, 'slug': slug, 'scenario_path': str(scenario_path), 'preview': preview}, 200

def write_promote_fill(env, path, preview):
    if '..' in path or path.startswith('/'):
        return {'ok': False, 'error': '非法路径'}, 400
    task_file, err = env._read_task_file(path)
    if not task_file:
        return {'ok': False, 'error': err}, 404 if err == '文件不存在' else 400

    slug = _scenario_slug_from_task_fm(env, task_file['frontmatter'])
    scenario_path, path_err, path_status = _resolve_scenario_path(env, slug)
    if path_err:
        return {'ok': False, 'error': path_err}, path_status
    if not scenario_path.exists():
        return {'ok': False, 'error': f'场景草稿不存在: {slug}'}, 404

    raw, fm_block, scenario_err, scenario_status = _read_draft_scenario_file(env, scenario_path)
    if scenario_err:
        return {'ok': False, 'error': scenario_err}, scenario_status

    body_prefix = raw[len(fm_block):]
    body_prefix = body_prefix[:len(body_prefix) - len(body_prefix.lstrip('\r\n'))] or '\n\n'
    normalized = _normalize_scenario_sections(env, preview)
    tmp = scenario_path.with_suffix('.tmp')
    try:
        tmp.write_text(fm_block + body_prefix + normalized, encoding='utf-8')
        os.replace(str(tmp), str(scenario_path))
    except OSError as e:
        return {'ok': False, 'error': f'写入场景草稿失败: {e}'}, 500
    return {'ok': True, 'slug': slug, 'scenario_path': str(scenario_path)}, 200
