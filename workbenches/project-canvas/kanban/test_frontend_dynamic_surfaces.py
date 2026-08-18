#!/usr/bin/env python3
"""Frontend surface routing tests for dynamic board providers."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_KANBAN_HTML = _HERE / 'kanban.html'
_MAIN_JS = _HERE / 'static' / 'kanban' / 'main.js'
_AUTH = _HERE / 'static' / 'kanban' / 'modules' / 'auth.js'
_API_JS = _HERE / 'static' / 'kanban' / 'modules' / 'api.js'
_RENDER_BOARD = _HERE / 'static' / 'kanban' / 'modules' / 'render-board.js'
_RENDER_BOARD_CORE = _HERE / 'static' / 'kanban' / 'modules' / 'render-board-core.js'
_RENDER_BOARD_DUTY = _HERE / 'static' / 'kanban' / 'modules' / 'render-board-duty.js'
_RENDER_BOARD_CONSOLE_CARDS = _HERE / 'static' / 'kanban' / 'modules' / 'render-board-console-cards.js'
_RENDER_BOARD_CONSOLE_RUNTIME = _HERE / 'static' / 'kanban' / 'modules' / 'render-board-console-runtime.js'
_RENDER_BOARD_CONSOLE = _HERE / 'static' / 'kanban' / 'modules' / 'render-board-console.js'
_RENDER_BOARD_MODULES = (
    _RENDER_BOARD,
    _RENDER_BOARD_CORE,
    _RENDER_BOARD_DUTY,
    _RENDER_BOARD_CONSOLE_CARDS,
    _RENDER_BOARD_CONSOLE_RUNTIME,
    _RENDER_BOARD_CONSOLE,
)
_RENDER_GOVERNANCE = _HERE.parents[2] / '_archive' / 'ui-surfaces-2026-07' / 'render-governance.js'
_RENDER_DETAIL = _HERE / 'static' / 'kanban' / 'modules' / 'render-detail.js'
_RENDER_DETAIL_MODULES = (
    _RENDER_DETAIL,
    _HERE / 'static' / 'kanban' / 'modules' / 'render-detail-actions.js',
    _HERE / 'static' / 'kanban' / 'modules' / 'render-detail-view.js',
)
_CONSOLE_RUNTIME_HARNESS = _HERE / 'test_console_runtime_harness.mjs'


def _render_board_source():
    """Read the KAN-1600 split modules in their main.js mount order."""
    return '\n'.join(path.read_text(encoding='utf-8') for path in _RENDER_BOARD_MODULES)


def _render_detail_source():
    """Read the KAN-1671 split modules in their main.js mount order."""
    return '\n'.join(path.read_text(encoding='utf-8') for path in _RENDER_DETAIL_MODULES)


def _load_scan_docs_module():
    spec = importlib.util.spec_from_file_location('kanban_scan_docs_for_frontend_test', _HERE / 'scan-docs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_console_bootstrap_data():
    scan_docs = _load_scan_docs_module()
    config = scan_docs.load_config()
    scan_docs.SCAN_DIRS = config.get('scan_dirs', scan_docs._DEFAULTS['scan_dirs'])
    scan_docs.ALL_MEMBERS = config.get('members', scan_docs._DEFAULTS['members'])
    scan_docs.LOGIN_MEMBERS = ['Owner'] if 'Owner' in scan_docs.ALL_MEMBERS else (
        scan_docs.ALL_MEMBERS[:1] if scan_docs.ALL_MEMBERS else []
    )
    scan_docs.CURRENT_MEMBER = 'Owner' if 'Owner' in scan_docs.ALL_MEMBERS else (
        scan_docs.ALL_MEMBERS[0] if scan_docs.ALL_MEMBERS else ''
    )
    scan_docs.CLI_COMMANDS = {
        name: scan_docs.parse_command_string(cfg['command'])
        for name, cfg in config.get('tools', scan_docs._DEFAULTS['tools']).items()
        if isinstance(cfg, dict) and cfg.get('command')
    }
    data = scan_docs.get_data()
    data['auth'] = {'authenticated': True, 'user': scan_docs.CURRENT_MEMBER or 'Owner'}
    return data


def test_dynamic_provider_surface_matching():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ dynamicProviderMatchesSurface }} from {str(_RENDER_BOARD.as_uri())!r};
      const checks = [
        [dynamicProviderMatchesSurface({{ surfaces: [] }}, 'console'), true, 'empty surfaces stay on console'],
        [dynamicProviderMatchesSurface({{}}, 'console'), true, 'missing surfaces stay on console'],
        [dynamicProviderMatchesSurface({{ surfaces: [] }}, 'governance'), false, 'empty surfaces do not fan out'],
        [dynamicProviderMatchesSurface({{ surfaces: ['console'] }}, 'console'), true, 'explicit console visible'],
        [dynamicProviderMatchesSurface({{ surfaces: ['governance'] }}, 'console'), false, 'governance hidden from console'],
        [dynamicProviderMatchesSurface({{ surfaces: ['governance'] }}, 'governance'), true, 'governance visible in matrix'],
      ];
      for (const [actual, expected, label] of checks) {{
        if (actual !== expected) throw new Error(`${{label}}: expected ${{expected}}, got ${{actual}}`);
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_project_canvas_is_default_and_dispatch_has_no_active_entry():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ BOARD_VIEWS, BOARD_TAB_VIEWS, BOARD_VIEW_LABELS, consoleProjectRailModel, isConsoleGlobalDispatchTask, projectPostureModel }} from {str(_RENDER_BOARD.as_uri())!r};
      // Project Canvas 是默认工作面；调度台代码只保留为可召回归档面。
      if (BOARD_VIEWS.join(',') !== 'projects,console,governance') {{
        throw new Error(`unexpected board views: ${{BOARD_VIEWS.join(',')}}`);
      }}
      if (BOARD_TAB_VIEWS.join(',') !== '') {{
        throw new Error(`unexpected active tabs: ${{BOARD_TAB_VIEWS.join(',')}}`);
      }}
      if (BOARD_VIEW_LABELS.projects !== '项目画布') throw new Error('Project Canvas label drifted');
      if (BOARD_VIEW_LABELS.console !== '调度台') throw new Error('console label drifted');
      if (BOARD_VIEW_LABELS.governance !== '治理') throw new Error('governance label drifted');
      const posture = projectPostureModel({{ok:true, counts:{{total:3, needs_owner:1, quiet_active:1, paused:0, completed:1, pending_changes:2}}, attention:[{{project_ref:'p'}}], projects:[]}});
      if (!posture.ok || posture.counts.needsOwner !== 1 || posture.counts.quietActive !== 1 || posture.counts.completed !== 1) throw new Error('project posture normalization drifted');
      const projects = [
        {{project_ref:'quiet', title:'Quiet', lifecycle:'active', primary_action:{{type:'no_action'}}, tasks:{{active_count:0}}}},
        {{project_ref:'decision', title:'Decision', lifecycle:'active', primary_action:{{type:'needs_decision'}}, tasks:{{active_count:2}}}},
        {{project_ref:'done', title:'Done', lifecycle:'completed', primary_action:{{type:'no_action'}}, tasks:{{active_count:0}}}},
      ];
      const rail = consoleProjectRailModel({{ok:true, projects, attention:[projects[1]]}});
      if (rail.map((item) => item.projectRef).join(',') !== 'decision,quiet,done') throw new Error('project rail order drifted');
      if (rail[0].label !== '需决策' || rail[0].activeTasks !== 2) throw new Error('project rail metadata drifted');
      const linkedTodo = {{project_ref:'p', status:'todo'}};
      const linkedRunning = {{project_ref:'p', status:'in_progress'}};
      if (isConsoleGlobalDispatchTask(linkedTodo, 'ai-work')) throw new Error('project-local queued work must stay in Project Canvas');
      if (!isConsoleGlobalDispatchTask(linkedRunning, 'ai-work')) throw new Error('running Agent work must remain globally observable');
      if (!isConsoleGlobalDispatchTask({{project_ref:'p', status:'review'}}, 'review')) throw new Error('project human gate must stay in global dispatch');
      if (!isConsoleGlobalDispatchTask({{status:'todo'}}, 'today')) throw new Error('unassigned work must stay globally routable');
      if (isConsoleGlobalDispatchTask({{project_ref:'p', status:'todo'}}, 'today')) throw new Error('project-local routine work must not duplicate in dispatch');
      if (!isConsoleGlobalDispatchTask({{project_ref:'p', status:'todo'}}, 'today', {{dueNow:true}})) throw new Error('due project work must surface as an exception');
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)
    main_source = _MAIN_JS.read_text(encoding='utf-8')
    if "activeView: 'projects'" not in main_source:
        raise AssertionError('必须默认进入 Project Canvas，不再回退调度台')


def test_sync_indicator_distinguishes_safety_pause_from_runtime_error():
    source = _MAIN_JS.read_text(encoding='utf-8')
    for needle in (
        "state === 'error') label.textContent = '同步异常'",
        "rawState === 'paused_manual_git') label.textContent = '待人工发布'",
        "rawState.startsWith('paused')) label.textContent = '同步待处理'",
        "rawState === 'pending') label.textContent = '等待同步'",
        '本地超前 ${activeStatus.ahead || 0}',
        '落后远端 ${activeStatus.behind || 0}',
    ):
        if needle not in source:
            raise AssertionError(f'同步状态缺少清晰区分: {needle}')
    css = (_HERE / 'static' / 'kanban' / 'kanban.css').read_text(encoding='utf-8')
    if '.sync-indicator.state-warning .sync-dot' not in css:
        raise AssertionError('安全暂停应使用黄色 warning 状态，而不是错误色')



def test_private_surfaces_and_local_tools_are_absent_from_overflow_menu():
    source = _render_board_source()
    html_source = _KANBAN_HTML.read_text(encoding='utf-8')
    main_source = _MAIN_JS.read_text(encoding='utf-8')
    for name in ('renderWorkbench', 'renderTasks', 'renderChains', 'renderDomainView'):
        if f'function {name}()' in source:
            raise AssertionError(f'{name} should not remain as a dead board view renderer')
    console_start = source.index('function renderConsole()')
    render_all_start = source.index('function renderAll()')
    console_body = source[console_start:render_all_start]
    if 'CONSOLE_AUDIENCE_OWNER' not in console_body:
        raise AssertionError('调度台渲染缺少 audience 标记')
    # 退役调度台清空底部工具块；公开菜单不再注入个人二级面或本地动作。
    for retired_call in ('makeConsoleBridges()', 'makeProjectPanoramaBlock()', 'makeChainFlowDetailBlock()'):
        if retired_call in console_body:
            raise AssertionError(f'调度台不应再直接渲染已退役抽屉部件: {retired_call}')
    # KAN-998：治理自治块已升为顶层「治理」视图，调度台桥接抽屉不再调用 makeGovernanceBurdenBlock。
    if 'makeGovernanceBurdenBlock()' in console_body:
        raise AssertionError('治理自治块应从调度台桥接抽屉移除（已升为顶层视图）')
    for removed in ('function makeConsoleStatusColumn()', 'console-utilities', '晨启 · 场景库 · Skill Board'):
        if removed in source:
            raise AssertionError(f'调度台仍残留本地工具块: {removed}')
    for removed in (
        '更多入口', '本地工具', '运行中心', '项目索引', 'data-board-view=',
        'data-local-tool=', '__KANBAN_OPTIONAL_VIEW_ITEMS__', '__KANBAN_OPTIONAL_LOCAL_TOOL_ITEMS__',
    ):
        if removed in html_source:
            raise AssertionError(f'公开汉堡菜单仍残留私有入口: {removed}')
    for removed in ('runMorningBatch', "querySelectorAll('[data-local-tool]')", "querySelectorAll('[data-board-view]')"):
        if removed in main_source:
            raise AssertionError(f'前端仍装配已删除菜单动作: {removed}')


def test_console_rail_omits_retired_project_map_block():
    # 2026-07-06 owner-confirmed（截图批注驱动）：右栏「项目图」面板已下架。
    source = _render_board_source()
    console_start = source.index('function renderConsole()')
    render_all_start = source.index('function renderAll()')
    console_body = source[console_start:render_all_start]
    if 'makeProjectMapsBlock()' in console_body:
        raise AssertionError('右栏不应再渲染已下架的项目图面板')
    if 'function makeProjectMapsBlock()' in source:
        raise AssertionError('已下架的项目图面板函数不应留存')


def test_header_canvas_entry_is_soft_unbound_and_sync_switches_stay_collapsed():
    source = _KANBAN_HTML.read_text(encoding='utf-8')
    header_right = source[source.index('<div class="hdr-r">'):source.index('<div class="hdr-overflow-menu"')]
    overflow_menu = source[source.index('<div class="hdr-overflow-menu"'):source.index('<div class="stats"', source.index('<div class="hdr-overflow-menu"'))]
    if 'id="btn-studio"' in header_right:
        raise AssertionError('Studio 不应继续占用 header 第一屏，应降级到溢出菜单')
    if 'id="btn-search"' not in header_right:
        raise AssertionError('搜索按钮必须保留在 header 第一屏')
    if 'id="overflow-btn-studio"' in overflow_menu or '画布工作台' in overflow_menu:
        raise AssertionError('Canvas Studio 已软解绑，不应继续出现在溢出菜单')
    if 'id="btn-audience"' in header_right or '人闸视角' in header_right:
        raise AssertionError('人闸视角开关不能继续占用 header 图标组')
    if 'id="overflow-btn-audience"' in overflow_menu or '人闸视角' in overflow_menu:
        raise AssertionError('极简调度台不再暴露第二套视角开关')
    if 'data-board-view=' in overflow_menu or '__KANBAN_OPTIONAL_VIEW_ITEMS__' in overflow_menu:
        raise AssertionError('公开菜单不得保留二级视图或动态视图注入位')
    if 'id="sw-sync-git"' in header_right or 'id="sw-sync-claude"' in header_right:
        raise AssertionError('Git/Claude sync 开关不能继续占用 header 第一屏')
    if 'id="overflow-sw-sync-git"' not in source:
        raise AssertionError('溢出菜单内的 Git sync 开关必须保留')
    # 2026-07-06 owner-confirmed（截图批注驱动）：Claude 自动同步菜单入口已下架（后端能力保留）。
    if 'id="overflow-sw-sync-claude"' in source:
        raise AssertionError('Claude 自动同步菜单入口已下架，不应再出现')


def test_header_project_canvas_brand_and_top_level_actions_collapsed():
    # KAN-1455：调度台退役后顶栏 brand 指向 Project Canvas；退出/设置仍收进汉堡菜单。
    source = _KANBAN_HTML.read_text(encoding='utf-8')
    header = source[source.index('<div class="hdr">'):source.index('<div class="stats"')]
    brand = header[header.index('<div class="hdr-brand">'):header.index('<div class="hdr-r">')]
    if '<strong>Project Canvas</strong>' not in brand:
        raise AssertionError('顶栏 brand 主标题必须是 Project Canvas')
    if 'id="hdr-audience-label"' not in brand:
        raise AssertionError('顶栏 brand 必须有视角副题标识 (hdr-audience-label)')
    header_before_overflow = header[:header.index('<div class="hdr-overflow-menu"')]
    if 'id="btn-logout"' in header_before_overflow:
        raise AssertionError('退出按钮必须收进汉堡菜单，不留在顶栏第一屏')
    if 'id="btn-settings"' in header_before_overflow:
        raise AssertionError('设置按钮必须收进汉堡菜单，不留在顶栏第一屏')
    if 'id="overflow-logout"' not in header or 'id="overflow-settings"' not in header:
        raise AssertionError('退出/设置必须仍在汉堡菜单内可达')
    if 'id="btn-automations"' in source or 'id="automation-sidebar"' in source:
        raise AssertionError('重复的手动运行按钮/侧栏必须退出活动页面')


def test_canvas_system_alert_deep_link_can_recall_dispatch_console():
    source = (_HERE / 'static' / 'kanban' / 'main.js').read_text(encoding='utf-8')
    if "get('view')" not in source or "requestedView === 'console'" not in source:
        raise AssertionError('Canvas 系统异常浮层的调度台链接必须能直接召回退役调度台')


def test_render_stats_drops_header_count_pills():
    # KAN-203：顶栏删除「任务/项目/活跃」三个计数 pill；renderStats 只清空 hdr-summary，不再逐项渲染。
    source = _render_board_source()
    stats_fn = source[source.index('function renderStats()'):source.index('function createCardEl(')]
    for banned in ("stats.total_tasks", "hdr-summary-item", "'任务'", "'项目'", "'活跃'"):
        if banned in stats_fn:
            raise AssertionError(f'renderStats 不应再渲染计数 pill 片段: {banned}')


def test_console_companion_facilities_are_folded_below_the_action_flow():
    # KAN-1744：三项本地启动动作迁入汉堡菜单，调度台底部彻底清空。
    source = _render_board_source()
    console_start = source.index('function renderConsole()')
    render_all_start = source.index('function renderAll()')
    console_body = source[console_start:render_all_start]
    for removed in ("utilities.className = 'console-utilities'", 'makeConsoleStatusColumn()', '本地工具', '晨启', 'Skill Board'):
        if removed in console_body:
            raise AssertionError(f'调度台底部本地工具残留未清: {removed}')
    for retired in ('appendIfNode(app, makeProjectPostureStrip())', 'ctx.renderRuntime?.makeConsoleStrip?.()', "rail.className = 'console-rail'"):
        if retired in console_body:
            raise AssertionError(f'常驻首页部件尚未软解绑: {retired}')
    if "makeConsoleDrawer('console-drawer-bridges'" in console_body:
        raise AssertionError('「桥接与入口」抽屉应保持退役')
    if 'function makeConsoleStatusColumn(' in source:
        raise AssertionError('本地工具唯一消费者迁走后，旧状态列函数必须退役')
    if 'function makeProjectHealthBlock(' in source:
        raise AssertionError('项目健康块唯一消费者已归档，render-board.js 不应继续保留')
    for fn in ('makeProjectPanoramaBlock', 'makeGovernanceBurdenBlock', 'makeConsoleBridges', 'makeDynamicBoardsBlock'):
        if f'function {fn}(' in source:
            raise AssertionError(f'零调用展示死代码应退役: {fn}')


def test_console_backstage_separates_execution_alerts_and_reference_indexes():
    source = _render_board_source()
    console_body = source[source.index('function renderConsole()'):source.index('function renderAll()')]
    for label in (
        "makeBackstageCluster('Agent 协作'",
        "makeBackstageCluster('后台异常'",
        "makeBackstageCluster('索引与回看'",
        "'稍后 / 停放'",
        "'路由异常'",
        "'画布标记'",
    ):
        if label not in console_body:
            raise AssertionError(f'后台区缺少分层语义: {label}')
    for retired_label in ("'画布试用'", "'未归类 · 待确认'", "'团队对接要点'"):
        if retired_label in console_body:
            raise AssertionError(f'后台区不应继续使用旧泳道文案: {retired_label}')


def test_console_audience_split_helpers_and_persistence():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{
        BOARD_VIEWS,
        CONSOLE_AUDIENCE_OWNER,
        CONSOLE_AUDIENCE_ATTENTION_GATE,
        consoleAudienceAllows,
        consoleInboxAudience,
        isConsoleOwnerDecisionTask,
        normalizeConsoleAudienceMode,
        visibleBoardViewsForAudience,
      }} from {str(_RENDER_BOARD.as_uri())!r};

      const fail = (msg) => {{ throw new Error(msg); }};
      if (normalizeConsoleAudienceMode(undefined) !== CONSOLE_AUDIENCE_OWNER) fail('默认必须是 Owner 视角');
      if (visibleBoardViewsForAudience('owner', BOARD_VIEWS).join(',') !== 'projects,console,governance') fail('Owner 视角必须保留公开可召回视图');
      if (visibleBoardViewsForAudience('attention_gate', BOARD_VIEWS).join(',') !== 'projects,console,governance') fail('人闸视角必须保留公开可召回视图');
      if (consoleAudienceAllows('owner', CONSOLE_AUDIENCE_ATTENTION_GATE)) fail('Owner 视角不能渲染 attention_gate 块');
      if (!consoleAudienceAllows('attention_gate', CONSOLE_AUDIENCE_ATTENTION_GATE)) fail('人闸视角必须渲染 attention_gate 块');
      if (!consoleAudienceAllows('attention_gate', CONSOLE_AUDIENCE_OWNER)) fail('人闸视角必须保留 Owner 块');

      const opsInbox = {{ status: 'todo', source: 'infoops/source-radar', title: 'SIH 自动抓取待分流', tags: [] }};
      if (consoleInboxAudience(opsInbox, 'Owner') !== CONSOLE_AUDIENCE_ATTENTION_GATE) fail('纯运营 feeder 应归人闸视角');

      const decisionDigest = {{ status: 'todo', source: 'skill/digest', title: 'SKL-8 决策 digest：需要 Owner 拍板', tags: [], responsibility: 'pi-gated', human_gate: true, attention_scope: 'owner' }};
      if (consoleInboxAudience(decisionDigest, 'Owner') !== CONSOLE_AUDIENCE_OWNER) fail('决策 digest feeder 必须留在 Owner 视角');

      const assignedOwner = {{ status: 'todo', source: 'manual/intake', assignee: 'Owner', title: '普通待分流' }};
      if (consoleInboxAudience(assignedOwner, 'Owner') !== CONSOLE_AUDIENCE_OWNER) fail('assignee=Owner 的 feeder 不得被藏');

      const reviewGov = {{ status: 'review', domain: 'governance', title: '治理验收', tags: ['governance'], responsibility: 'pi-gated', human_gate: true, attention_scope: 'owner' }};
      if (isConsoleOwnerDecisionTask(reviewGov, 'Owner')) fail('普通验收卡应进入验收泳道，不得重复计入拍板');
      console.log('console audience split ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'console audience split ok' in result.stdout

    main_source = _MAIN_JS.read_text(encoding='utf-8')
    if "audienceMode: 'owner'" not in main_source:
        raise AssertionError('极简调度台必须固定使用 Owner 主视角')
    html_source = _KANBAN_HTML.read_text(encoding='utf-8')
    if 'overflow-btn-audience' in html_source or '人闸视角' in html_source:
        raise AssertionError('极简调度台不得暴露视角切换入口')


def test_console_audience_split_gates_attention_gate_rendering_blocks():
    source = _render_board_source()
    console_start = source.index('function renderConsole()')
    render_all_start = source.index('function renderAll()')
    console_body = source[console_start:render_all_start]
    # KAN-199：AI 工作 / 等待中 / 收件箱改为盘面条抽屉，两视角都可见（不需要 Owner 动作故收进折叠区），
    # 因此不再由 attention_gateMode 门控；unrouted / recentDone / 分流账仍是人闸专属。
    # KAN-998：治理自治块已从桥接抽屉搬到顶层「治理」视图（render-governance.js），此处不再门控它。
    for needle in (
        "const routingLane = (task) => consoleTaskRoutingLane(task, person, aiMembers)",
        'const decisionDigest = attention_gateMode ? inbox : decisions',
        "routingLane(task) === 'waiting'",
        'aiWork.length || waiting.length',
        'attention_gateMode && unrouted.length',
        'attention_gateMode && !uiState.filters.hideDone && recentHistory.length',
        'attention_gateMode && (divertedGov || recordCount || pointerCount)',
    ):
        if needle not in console_body:
            raise AssertionError(f'调度台缺少人闸块显隐断言片段: {needle}')
    # KAN-998：桥接抽屉不得再挂治理自治块（已升为顶层视图）。
    if 'appendIfNode(bridgesContent, makeGovernanceBurdenBlock())' in console_body:
        raise AssertionError('治理自治块应从桥接抽屉移除（已升为顶层「治理」视图）')
    # KAN-1001：值守面板搬进治理页「人闸值守」段，调度台主列不再直接调用。
    if 'main.appendChild(makeAttentionGateDutyPanel())' in console_body:
        raise AssertionError('调度台主列不应再渲染值守面板（已并入治理页人闸值守段）')
    if "async function attention_gateDuty()" not in _API_JS.read_text(encoding='utf-8'):
        raise AssertionError('值守区必须通过 ctx.api.attention_gateDuty 读取，不得跨模块 import/fetch 散落')
    assert 'sih-sources' not in source
    assert 'renderSihSources' not in source


def test_owner_audience_runtime_renders_console_shell():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      class FakeClassList {{
        constructor(owner) {{ this.owner = owner; this.values = new Set(); }}
        sync(value) {{
          this.values = new Set(String(value || '').split(/\\s+/).filter(Boolean));
        }}
        write() {{ this.owner._className = Array.from(this.values).join(' '); }}
        add(...names) {{ names.filter(Boolean).forEach((name) => this.values.add(name)); this.write(); }}
        remove(...names) {{ names.forEach((name) => this.values.delete(name)); this.write(); }}
        contains(name) {{ return this.values.has(name); }}
        toggle(name, force) {{
          const next = force === undefined ? !this.values.has(name) : Boolean(force);
          if (next) this.values.add(name); else this.values.delete(name);
          this.write();
          return next;
        }}
      }}

      class FakeElement {{
        constructor(tagName, doc) {{
          this.tagName = String(tagName || 'div').toUpperCase();
          this.ownerDocument = doc;
          this.children = [];
          this.parentElement = null;
          this.dataset = {{}};
          this.style = {{}};
          this.attributes = {{}};
          this.hidden = false;
          this._text = '';
          this._className = '';
          this.classList = new FakeClassList(this);
        }}
        set className(value) {{ this._className = String(value || ''); this.classList.sync(this._className); }}
        get className() {{ return this._className; }}
        set textContent(value) {{ this._text = String(value ?? ''); this.children = []; }}
        get textContent() {{ return this._text + this.children.map((child) => child.textContent).join(''); }}
        set innerHTML(value) {{ this._text = String(value || ''); this.children = []; }}
        get innerHTML() {{ return this._text; }}
        get childElementCount() {{ return this.children.length; }}
        appendChild(child) {{
          if (!child) throw new Error('appendChild(null)');
          child.parentElement = this;
          this.children.push(child);
          return child;
        }}
        insertBefore(child, before) {{
          if (!child) throw new Error('insertBefore(null)');
          child.parentElement = this;
          const index = this.children.indexOf(before);
          if (index < 0) this.children.push(child);
          else this.children.splice(index, 0, child);
          return child;
        }}
        setAttribute(name, value) {{ this.attributes[name] = String(value); if (name === 'id') this.id = String(value); }}
        getAttribute(name) {{ return this.attributes[name]; }}
        addEventListener() {{}}
        focus() {{}}
        select() {{}}
        contains(target) {{
          return target === this || this.children.some((child) => child.contains && child.contains(target));
        }}
        matches(selector) {{
          if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
          if (selector.startsWith('#')) return this.id === selector.slice(1);
          if (selector === '[data-audience]') return Boolean(this.dataset && this.dataset.audience);
          return this.tagName.toLowerCase() === selector.toLowerCase();
        }}
        querySelectorAll(selector) {{
          const results = [];
          const visit = (node) => {{
            node.children.forEach((child) => {{
              if (child.matches && child.matches(selector)) results.push(child);
              visit(child);
            }});
          }};
          visit(this);
          return results;
        }}
        querySelector(selector) {{ return this.querySelectorAll(selector)[0] || null; }}
      }}

      class FakeDocument {{
        constructor() {{ this.body = new FakeElement('body', this); }}
        createElement(tagName) {{ return new FakeElement(tagName, this); }}
        getElementById(id) {{
          const find = (node) => {{
            if (node.id === id) return node;
            for (const child of node.children) {{
              const found = find(child);
              if (found) return found;
            }}
            return null;
          }};
          return find(this.body);
        }}
        querySelector(selector) {{ return this.body.querySelector(selector); }}
        querySelectorAll(selector) {{ return this.body.querySelectorAll(selector); }}
      }}

      const document = new FakeDocument();
      globalThis.document = document;
      globalThis.window = {{
        location: {{ href: 'http://localhost:8890/' }},
        open() {{}},
        setTimeout: (fn) => {{ fn(); return 0; }},
        matchMedia: () => ({{ matches: false, addEventListener() {{}} }}),
      }};
      Object.defineProperty(globalThis, 'navigator', {{ value: {{}}, configurable: true }});

      const mount = (id) => {{
        const el = document.createElement('div');
        el.id = id;
        document.body.appendChild(el);
        return el;
      }};
      const dom = {{
        tabs: mount('tabs'),
        views: mount('views'),
        time: mount('time'),
        overflowClock: mount('overflow-clock'),
        hdrSummary: mount('hdr-summary'),
        stats: mount('stats'),
        hdrUsername: mount('hdr-username'),
        btnLogout: mount('btn-logout'),
      }};
      const makeBadge = (text) => {{
        const el = document.createElement('span');
        el.className = 'b b-who';
        el.textContent = text || '未分配';
        return el;
      }};
      const ui = {{
        dom,
        STATUS: ['todo', 'in-progress', 'review', 'done'],
        SL: {{ todo: '待办', 'in-progress': '进行中', review: '评审中', done: '已完成' }},
        PL: {{ high: '高', medium: '中', low: '低' }},
        isMobile: () => false,
        dueDateText: () => null,
        makeDd: (_items, current) => makeBadge(current),
        makeMemberDd: (current) => makeBadge(current),
        toast() {{}},
        esc: (value) => String(value || ''),
      }};
      const dataState = {{
        generated_at: '2026-07-06 10:00',
        stats: {{ total_tasks: 3, projects: 1, active_projects: 1 }},
        auth: {{ authenticated: true, user: 'Owner' }},
        login_members: ['Owner'],
        members: ['Owner'],
        all_members: ['Owner', 'Codex'],
        ai_members: ['Codex'],
        project_names: ['个人调度'],
        research_boards: [],
        chains: [],
        project_posture: {{
          ok: true,
          schema: 'kanban-project-posture/v1',
          counts: {{total: 3, needs_owner: 0, quiet_active: 2, paused: 0, completed: 1, pending_changes: 0}},
          attention: [],
          projects: [],
        }},
        tasks: [
          {{ task_id: 'KAN-1', path: 'project/个人调度/KAN-1.md', project: '个人调度', title: '待验收卡', status: 'review', assignee: 'Owner', priority: 'high', task_family: 'kanban', responsibility: 'pi-gated', human_gate: true, attention_scope: 'owner' }},
          {{ task_id: 'KAN-2', path: 'project/个人调度/KAN-2.md', project: '个人调度', title: '今天必做卡', status: 'todo', assignee: 'Owner', priority: 'medium', task_family: 'kanban' }},
          {{ task_id: 'SKL-8', path: 'project/个人调度/SKL-8.md', project: '个人调度', title: '决策 digest 待拍板', status: 'todo', source: 'skill/digest', priority: 'high', task_family: 'skill', responsibility: 'pi-gated', human_gate: true, attention_scope: 'owner' }},
        ],
      }};
      const ctx = {{
        dataState,
        uiState: {{
          auth: {{ currentUser: '', sessionValid: false }},
          filters: {{ hideDone: false, mine: false }},
          board: {{ activeView: 'console', audienceMode: 'owner' }},
          queue: {{}},
        }},
        ui,
        hasApi: false,
        api: {{ openInEditor() {{}} }},
        renderDetail: {{ openTaskDetail() {{}} }},
      }};

      const {{ setupAuth }} = await import({str(_AUTH.as_uri())!r});
      const {{ setupRenderBoard }} = await import({str(_RENDER_BOARD.as_uri())!r});
      const {{ setupRenderBoardCore }} = await import({str(_RENDER_BOARD_CORE.as_uri())!r});
      const {{ setupRenderBoardDuty }} = await import({str(_RENDER_BOARD_DUTY.as_uri())!r});
      const {{ setupRenderBoardConsoleCards }} = await import({str(_RENDER_BOARD_CONSOLE_CARDS.as_uri())!r});
      const {{ setupRenderBoardConsoleRuntime }} = await import({str(_RENDER_BOARD_CONSOLE_RUNTIME.as_uri())!r});
      const {{ setupRenderBoardConsole }} = await import({str(_RENDER_BOARD_CONSOLE.as_uri())!r});
      setupAuth(ctx);
      setupRenderBoard(ctx);
      setupRenderBoardCore(ctx);
      setupRenderBoardDuty(ctx);
      setupRenderBoardConsoleCards(ctx);
      setupRenderBoardConsoleRuntime(ctx);
      setupRenderBoardConsole(ctx);
      ctx.auth.init();
      ctx.renderBoard.renderAll();
      const consoleView = document.getElementById('vw-console');
      const text = consoleView ? consoleView.textContent : '';
      const audienceCount = document.querySelectorAll('[data-audience]').length;
      if (dom.hdrUsername.textContent !== 'Owner') throw new Error('auth 初始化后用户名未同步为 Owner: ' + dom.hdrUsername.textContent);
      if (!consoleView || consoleView.childElementCount === 0) throw new Error('Owner 视角 console 空白');
      // 极简首页只保留四个动作入口；本地工具已迁入全局汉堡菜单。
      for (const label of ['待分流', '我现在做', 'Agent 执行', '等我验收', '+ 派活']) {{
        if (!text.includes(label)) throw new Error('Owner 视角缺少块: ' + label + '\\n' + text);
      }}
      for (const banned of ['项目态势', '今日 SIH', '今日值得读', 'SIH 更多 →']) {{
        if (text.includes(banned)) throw new Error('极简首页仍残留常驻块: ' + banned);
      }}
      if (text.includes('Canvas Studio') || text.includes('项目图 ↗') || text.includes('对话图 ↗')) throw new Error('Canvas Studio 已软解绑，不应继续出现在调度台');
      if (consoleView.querySelector('.console-rail')) throw new Error('极简首页不得保留常驻右栏');
      if (consoleView.querySelector('.console-utilities') || consoleView.querySelector('.console-status-col')) throw new Error('调度台底部工具块必须清零');
      if (consoleView.querySelector('#console-drawer-bridges')) throw new Error('「桥接与入口」抽屉应已退役');
      if (audienceCount <= 0) throw new Error('Owner 视角未渲染 data-audience 元素');
      // KAN-203：顶栏删除「任务/项目/活跃」三个计数 pill，renderStats 后 hdr-summary 必须为空。
      if (dom.hdrSummary && dom.hdrSummary.childElementCount !== 0) throw new Error('顶栏计数 pill 未清除 (hdr-summary 应为空)');
      const tabs = Array.from(dom.tabs.querySelectorAll('.tab'));
      if (tabs.length !== 0) throw new Error('调度台退役后不得保留一级导航 tab');
      console.log('owner audience runtime console ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'owner audience runtime console ok' in result.stdout


def test_owner_audience_runtime_renders_current_real_bootstrap_data(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    data = _real_console_bootstrap_data()
    if not data.get('tasks'):
        pytest.skip('real kanban bootstrap has no tasks to exercise console rendering')
    real_domain_tasks = [
        task for task in data['tasks']
        if (
            task.get('domain') and task.get('domain') != 'personal'
        ) or (
            task.get('project') == '场景库运营'
            or task.get('scenario_slug')
            or task.get('task_family') in {'KMO', 'SKL', 'SCN', 'RSH', 'GOV', 'CHN'}
        )
    ]
    if not real_domain_tasks:
        pytest.skip('real kanban bootstrap has no non-personal domain task for console badge regression')

    bootstrap_path = tmp_path / 'kanban-real-bootstrap.json'
    bootstrap_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    script = f"""
      import fs from 'node:fs';
      import {{ renderConsoleWithData }} from {str(_CONSOLE_RUNTIME_HARNESS.as_uri())!r};

      const dataState = JSON.parse(fs.readFileSync({str(bootstrap_path)!r}, 'utf8'));
      const {{ document, dom, consoleView }} = await renderConsoleWithData(dataState, {{ audienceMode: 'owner' }});
      const text = consoleView ? consoleView.textContent : '';
      const main = consoleView ? consoleView.querySelector('.console-main') : null;
      const audienceCount = document.querySelectorAll('[data-audience]').length;
      if (dom.hdrUsername.textContent !== 'Owner') throw new Error('auth 初始化后用户名未同步为 Owner: ' + dom.hdrUsername.textContent);
      if (!consoleView || consoleView.childElementCount === 0) throw new Error('真实数据 Owner 视角 console 空白');
      if (!main || main.childElementCount === 0) throw new Error('真实数据 Owner 视角 console-main 空白');
      for (const label of ['待分流', '我现在做', 'Agent 执行', '等我验收', '+ 派活']) {{
        if (!text.includes(label)) throw new Error('真实数据 Owner 视角缺少块: ' + label + '\\n' + text);
      }}
      for (const banned of ['项目态势', '今日 SIH', '今日值得读', 'SIH 更多 →']) {{
        if (text.includes(banned)) throw new Error('真实数据极简首页仍残留常驻块: ' + banned);
      }}
      if (text.includes('Canvas Studio') || text.includes('项目图 ↗') || text.includes('对话图 ↗')) throw new Error('Canvas Studio 已软解绑，不应继续出现在真实数据调度台');
      // KAN-199：盘面条（cursor 条）是 Owner 视角新主结构，必须渲染。
      const cursorBar = consoleView ? consoleView.querySelector('.console-cursor-bar') : null;
      if (!cursorBar) throw new Error('真实数据 Owner 视角缺少盘面条 (.console-cursor-bar)');
      if (consoleView.querySelector('.console-project-posture')) throw new Error('项目态势不得常驻极简首页');
      if (consoleView.querySelector('.console-rail')) throw new Error('极简首页不得保留常驻右栏');
      if (consoleView.querySelector('.console-utilities') || consoleView.querySelector('.console-status-col')) throw new Error('真实数据调度台底部工具块必须清零');
      if (consoleView.querySelector('#console-drawer-bridges')) {{
        throw new Error('「桥接与入口」抽屉应已退役（KAN-1002 内容上移右栏）');
      }}
      // KAN-203：+派活 描边小按钮并入盘面条右侧。
      if (!cursorBar.querySelector('.console-dispatch-btn')) throw new Error('盘面条右侧必须有「+派活」描边小按钮');
      // 路由异常仍是人闸专属块，Owner 视角不得出现。
      // AI 在办 / 收件箱 / 团队对接要点改为盘面条抽屉，两视角都可出现（不需要 Owner 动作故折叠），不再是禁项。
      // 按块元素判定，不用 textContent 子串匹配——卡标题里可能含「未归类」等字样（如 KAN-9），子串匹配会误报。
      if (consoleView.querySelector('#console-drawer-unrouted') || consoleView.querySelector('#console-drawer-governance')) {{
        throw new Error('Owner 视角不应渲染人闸专属块(路由异常/治理负担)');
      }}
      // KAN-1001：值守面板已搬进治理页人闸值守段，调度台主列不得再渲染。
      if (consoleView.querySelector('#console-attention_gate-duty')) {{
        throw new Error('调度台不应再渲染值守面板（已并入治理页）');
      }}
      if (audienceCount <= 0) throw new Error('真实数据 Owner 视角未渲染 data-audience 元素');
      const runtimeTab = Array.from(dom.tabs.querySelectorAll('.tab')).find((tab) => tab.dataset.v === 'runtime');
      if (runtimeTab) throw new Error('运行中心不得继续占用一级导航');
      const projectsTab = Array.from(dom.tabs.querySelectorAll('.tab')).find((tab) => tab.dataset.v === 'projects');
      if (projectsTab) throw new Error('真实项目不得继续占用一级导航');
      const tabs = Array.from(dom.tabs.querySelectorAll('.tab'));
      if (tabs.length !== 0) throw new Error('真实数据不得保留已退役调度台 tab');
      console.log('real bootstrap owner console ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'real bootstrap owner console ok' in result.stdout


def test_governance_view_is_recallable_but_not_active_wiring():
    if not _RENDER_GOVERNANCE.is_file():
        pytest.skip('missing optional source path: _archive/ui-surfaces-2026-07/render-governance.js')
    # 治理实现保留为归档源码，但不再由 main 装配或出现在日常导航。
    gov_source = _RENDER_GOVERNANCE.read_text(encoding='utf-8')
    if 'export function setupRenderGovernance(ctx)' not in gov_source:
        raise AssertionError('render-governance.js 必须导出 setupRenderGovernance(ctx)')
    if "from './render-board.js'" in gov_source or 'import ' in gov_source.split('export function setupRenderGovernance')[0]:
        raise AssertionError('render-governance.js 不得跨模块 import（能力经 ctx 取）')
    # KAN-999：顶段改名「等 Owner 动作的」（一本账 = ownerActionNeeded，与链健康行同源）。
    for needle in ('等 Owner 动作的', '自治运行的', '基建维护台账', '/api/governance/maintenance', 'ctx.renderBoard.governance', 'ownerActionTasks'):
        if needle not in gov_source:
            raise AssertionError(f'治理视图缺少决策流/端点接线: {needle}')
    board_source = _render_board_source()
    if 'function makeProjectHealthBlock(' in board_source:
        raise AssertionError('项目健康块已随治理页归档，不应继续在 render-board.js 中活动保留')
    main_source = _MAIN_JS.read_text(encoding='utf-8')
    if 'setupRenderGovernance' in main_source:
        raise AssertionError('main.js 不应继续装配已归档的治理页')
    board_source = _render_board_source()
    if 'export const BOARD_TAB_VIEWS = []' not in board_source:
        raise AssertionError('调度台退役后日常导航不得暴露旧一级 tab')


def test_runtime_center_is_removed_and_old_hash_returns_home():
    removed_files = (
        _HERE / 'static' / 'kanban' / 'modules' / 'render-runtime.js',
        _HERE / 'static' / 'kanban' / 'modules' / 'automation-schedule.js',
        _HERE / 'static' / 'kanban' / 'ai-runtime.css',
    )
    assert all(not path.exists() for path in removed_files)
    combined = '\n'.join((
        _MAIN_JS.read_text(encoding='utf-8'),
        _API_JS.read_text(encoding='utf-8'),
        _render_board_source(),
        _KANBAN_HTML.read_text(encoding='utf-8'),
    ))
    for removed in ('setupRenderRuntime', "view === 'runtime'", 'ctx.renderRuntime', '/api/automations/'):
        assert removed not in combined
    detail_view = (_HERE / 'static' / 'kanban' / 'modules' / 'render-detail-view.js').read_text(encoding='utf-8')
    assert "if (hash === 'runtime')" in detail_view
    assert "history.replaceState(null, '', window.location.pathname + window.location.search)" in detail_view


def test_governance_view_renders_decision_stream_sections(tmp_path):
    pytest.skip('KAN-1446: render-governance.js 已归档，当前回归只验证召回源码与主线脱线')
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ renderConsoleWithData }} from {str(_CONSOLE_RUNTIME_HARNESS.as_uri())!r};
      import {{ setupRenderGovernance }} from {str(_RENDER_GOVERNANCE.as_uri())!r};

      const dataState = {{
        generated_at: '2026-07-11 10:00',
        stats: {{ total_tasks: 2, projects: 1, active_projects: 1 }},
        auth: {{ authenticated: true, user: 'Owner' }},
        login_members: ['Owner'],
        members: ['Owner'],
        all_members: ['Owner', 'Codex'],
        ai_members: ['Codex'],
        project_names: ['个人调度'],
        research_boards: [],
        chains: [],
        tasks: [
          {{ task_id: 'GOV-1', path: 'project/个人调度/GOV-1.md', project: '个人调度', title: '治理拍板卡', status: 'todo', domain: 'governance', task_family: 'governance', responsibility: 'pi-gated', priority: 'high', assignee: 'Owner' }},
          {{ task_id: 'GOV-2', path: 'project/个人调度/GOV-2.md', project: '个人调度', title: '自治理卡', status: 'todo', domain: 'governance', task_family: 'governance', responsibility: 'ai-owned', safety: 'reversible', priority: 'medium', assignee: 'Codex' }},
        ],
      }};

      const {{ ctx, document }} = await renderConsoleWithData(dataState, {{ audienceMode: 'attention_gate' }});
      setupRenderGovernance(ctx);
      if (!ctx.renderGovernance || typeof ctx.renderGovernance.render !== 'function') throw new Error('setupRenderGovernance 未挂 render');
      ctx.renderBoard.switchView('governance');

      const view = document.getElementById('vw-governance');
      if (!view || view.childElementCount === 0) throw new Error('治理视图未渲染内容');
      const text = view.textContent || '';
      // 分组轴 = 决策流四段，绝不按卡片类型分组。KAN-999：顶段 =「等 Owner 动作的」一本账；
      // KAN-1001：第二段「人闸值守」（静态模式亦渲染段壳+降级文案）。
      for (const label of ['等 Owner 动作的', '人闸值守', '自治运行的', '基建维护台账']) {{
        if (!text.includes(label)) throw new Error('治理视图缺少决策流段: ' + label);
      }}
      for (const typeLabel of ['看板治理', 'Skill治理', '规则/账本']) {{
        if (text.includes(typeLabel)) throw new Error('治理视图不得按卡片类型分组: ' + typeLabel);
      }}
      // 顶段列出等 Owner 动作的治理卡（pi-gated∧todo/review）；ai-owned 卡不入顶段列表。
      if (!text.includes('治理拍板卡')) throw new Error('顶段应列出等 Owner 动作的治理卡');
      if (!text.includes('等你动作 1')) throw new Error('顶段陈述应为「等你动作 1」（GOV-1 todo·pi-gated）');
      const actions = view.querySelectorAll('.console-gov-action');
      if (actions.length !== 4) throw new Error('自治运行段应有 矩阵/体检/自检/决策账 四个动作');
      // KAN-998（Owner 0711 追加）：项目健康（链路健康一览）搬进治理页自治运行段。
      if (!view.querySelector('.console-project-health')) throw new Error('自治运行段必须承载项目健康链路一览');
      // 静态模式维护面板优雅降级（无 API）。
      if (!text.includes('静态模式不读取维护台账')) throw new Error('维护面板缺少静态降级文案');
      console.log('governance view decision stream ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'governance view decision stream ok' in result.stdout


def test_chain_health_rows_render_assertions_not_scores():
    pytest.skip('KAN-1446: 治理页项目健康块已归档；链路底层函数保留但不再经治理页运行时测试')
    # KAN-1000（Owner 拍板「分数降低成断言」）：链行零合成分数/零进度条/零 tier 配色，
    # 断言数字与 chainHealthScore signals 精确一致，hover title 带 refs 卡号。
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ renderConsoleWithData }} from {str(_CONSOLE_RUNTIME_HARNESS.as_uri())!r};
      import {{ setupRenderGovernance }} from {str(_RENDER_GOVERNANCE.as_uri())!r};
      import {{ chainHealthScore, normalizeFrontendChains }} from {str(_RENDER_BOARD.as_uri())!r};

      const tasks = [
        {{ task_id: 'GOV-801', path: 'project/个人调度/GOV-801_拍板卡.md', project: '个人调度', title: '治理拍板卡', status: 'todo', task_family: 'governance', responsibility: 'pi-gated', assignee: 'Owner', priority: 'high' }},
        {{ task_id: 'GOV-802', path: 'project/个人调度/GOV-802_验收卡.md', project: '个人调度', title: '治理验收卡', status: 'review', task_family: 'governance', responsibility: 'pi-gated', assignee: 'Owner', priority: 'high' }},
        {{ task_id: 'SKL-801', path: 'project/个人调度/SKL-801_代收卡.md', project: '个人调度', title: 'skill 代收卡', status: 'review', task_family: 'skill', responsibility: 'ai-owned', assignee: 'Codex', priority: 'medium' }},
        {{ task_id: 'GOV-803', path: 'project/个人调度/GOV-803_停滞卡.md', project: '个人调度', title: '治理停滞卡', status: 'in-progress', task_family: 'governance', responsibility: 'ai-owned', assignee: 'Codex', priority: 'medium', status_changed_at: '2026-06-01' }},
      ];
      const chainsConfig = [{{ key: 'gov', title: '治理链', mark: 'GOV', stages: [
        {{ key: 'gov/triage', title: '判断' }}, {{ key: 'gov/accept', title: '验收' }},
      ] }}];

      const dataState = {{
        generated_at: '2026-07-11 12:00',
        stats: {{ total_tasks: 4, projects: 1, active_projects: 1 }},
        auth: {{ authenticated: true, user: 'Owner' }},
        login_members: ['Owner'], members: ['Owner'], all_members: ['Owner', 'Codex'], ai_members: ['Codex'],
        project_names: ['个人调度'], research_boards: [], chains: chainsConfig,
        tasks,
      }};

      const {{ ctx, document }} = await renderConsoleWithData(dataState, {{ audienceMode: 'owner' }});
      setupRenderGovernance(ctx);
      ctx.renderBoard.switchView('governance');
      const view = document.getElementById('vw-governance');
      if (!view) throw new Error('治理视图未渲染');

      // 零合成分数 / 零进度条 / 零 tier 配色。
      if (view.querySelector('.console-project-score')) throw new Error('链行不得再渲染合成分数 span');
      if (view.querySelector('.console-project-bar')) throw new Error('链行不得再渲染进度条');
      const text = view.textContent || '';
      if (/\\d+\\s*分/.test(text)) throw new Error('治理页不得出现「N分」字样');

      // 断言数字与 chainHealthScore signals 精确一致。
      const gov = normalizeFrontendChains(chainsConfig)[0];
      const health = chainHealthScore(gov, tasks, Date.now(), 'Owner');
      if (health.signals.waitingDecision !== 2) throw new Error(`fixture 预期等你动作 2, got ${{health.signals.waitingDecision}}`);
      const row = view.querySelector('.console-project-row');
      if (!row) throw new Error('治理链应有活跃卡行');
      const rowText = row.textContent || '';
      if (!rowText.includes('等你动作 ' + health.signals.waitingDecision)) {{
        throw new Error(`主断言应为 等你动作 ${{health.signals.waitingDecision}}: ${{rowText}}`);
      }}
      if (!rowText.includes('AI 代收中 ' + health.signals.aiProxyReview)) {{
        throw new Error(`次要断言应含 AI 代收中 ${{health.signals.aiProxyReview}}: ${{rowText}}`);
      }}
      if (!rowText.includes('真停滞 ' + health.signals.stalled)) {{
        throw new Error(`次要断言应含 真停滞 ${{health.signals.stalled}}: ${{rowText}}`);
      }}
      // 主断言 accent 规则：仅等你动作>0（.is-waiting）一处，次要断言行纯灰阶。
      const accented = Array.from(row.querySelectorAll('.console-project-meta')).filter((el) => el.classList.contains('is-waiting'));
      if (accented.length !== 1) throw new Error(`只允许主断言一处 accent, got ${{accented.length}}`);
      if (!accented[0].textContent.startsWith('等你动作')) throw new Error('accent 只能落在等你动作断言上');

      // hover title 带 refs 卡号（哪几张卡）。
      const title = String(row.title || '');
      for (const id of ['GOV-801', 'GOV-802']) {{
        if (!title.includes(id)) throw new Error(`hover title 应含等你动作卡号 ${{id}}: ${{title}}`);
      }}
      if (!title.includes('AI 代收中: SKL-801')) throw new Error('hover title 应含代收卡号: ' + title);
      if (!title.includes('真停滞: GOV-803')) throw new Error('hover title 应含停滞卡号: ' + title);
      console.log('chain health assertion rows ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'chain health assertion rows ok' in result.stdout


def test_governance_inline_flow_expands_on_chain_row_click():
    pytest.skip('KAN-1446: render-governance.js 已归档，治理页内联 Flow 不再是活动 surface')
    # KAN-1002：Flow 详情迁治理页——链行点击=页内展开，不再切回调度台（KAN-998 跨视图跳转尾巴已治）。
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ renderConsoleWithData }} from {str(_CONSOLE_RUNTIME_HARNESS.as_uri())!r};
      import {{ setupRenderGovernance }} from {str(_RENDER_GOVERNANCE.as_uri())!r};

      const dataState = {{
        generated_at: '2026-07-11 14:00',
        stats: {{ total_tasks: 1, projects: 1, active_projects: 1 }},
        auth: {{ authenticated: true, user: 'Owner' }},
        login_members: ['Owner'], members: ['Owner'], all_members: ['Owner', 'Codex'], ai_members: ['Codex'],
        project_names: ['个人调度'], research_boards: [],
        chains: [{{ key: 'gov', title: '治理链', mark: 'GOV', stages: [
          {{ key: 'gov/triage', title: '判断' }}, {{ key: 'gov/accept', title: '验收' }},
        ] }}],
        tasks: [
          {{ task_id: 'GOV-901', path: 'project/个人调度/GOV-901_卡.md', project: '个人调度', title: '治理卡', status: 'todo', task_family: 'governance', responsibility: 'pi-gated', assignee: 'Owner', priority: 'high' }},
        ],
      }};

      const {{ ctx, document }} = await renderConsoleWithData(dataState, {{ audienceMode: 'owner' }});
      setupRenderGovernance(ctx);
      ctx.uiState.board.chainFlowExpanded = false;
      ctx.renderBoard.switchView('governance');
      const view = () => document.getElementById('vw-governance');
      if (view().querySelector('#chain-flow-detail')) throw new Error('Flow 详情默认必须折叠');

      // 链行点击 → openChainFlow → 治理页内展开，不切回调度台。
      const row = view().querySelector('.console-project-row');
      if (!row) throw new Error('治理页应有链行');
      row.onclick();
      if (ctx.uiState.board.activeView !== 'governance') throw new Error('链行点击不得切回调度台, got ' + ctx.uiState.board.activeView);
      const flow = view().querySelector('#chain-flow-detail');
      if (!flow) throw new Error('链行点击后 Flow 详情必须页内展开');
      if (!flow.classList.contains('gov-view-flow')) throw new Error('Flow 详情必须挂在治理页自治运行段（gov-view-flow）');
      // gov 链展开不内嵌矩阵（治理页已单独渲染矩阵 mount）。
      if (view().querySelector('#chains-governance-matrix')) throw new Error('治理页内联 Flow 不得重复内嵌治理矩阵');
      if (!view().querySelector('#governance-view-matrix')) throw new Error('治理页自有矩阵 mount 必须仍在');
      console.log('governance inline flow ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'governance inline flow ok' in result.stdout


def test_governance_duty_section_summary_and_pending_line():
    pytest.skip('KAN-1446: render-governance.js 已归档，值守段运行时契约不再阻断当前回归')
    # KAN-1001：治理页「人闸值守」段 = 3-6 行可证伪断言（白话+源指针，唯一 accent 给
    # weekly-action-required）+ 折叠明细；「等 Owner 动作的」段尾 = 待追认决策草稿 accent 行。
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ renderConsoleWithData }} from {str(_CONSOLE_RUNTIME_HARNESS.as_uri())!r};
      import {{ setupRenderGovernance }} from {str(_RENDER_GOVERNANCE.as_uri())!r};

      const dataState = {{
        generated_at: '2026-07-11 13:00',
        stats: {{ total_tasks: 0, projects: 1, active_projects: 1 }},
        auth: {{ authenticated: true, user: 'Owner' }},
        login_members: ['Owner'], members: ['Owner'], all_members: ['Owner', 'Codex'], ai_members: ['Codex'],
        project_names: ['个人调度'], research_boards: [], chains: [], tasks: [],
      }};
      const dutyData = {{
        ok: true,
        weekly_review: {{
          exists: true,
          week: '2026-07-06..2026-07-12',
          generated_at: '2026-07-10T22:25:35+08:00',
          content: [
            '# 人闸周五复盘周报',
            '',
            '- ASSERT weekly-action-required: yes；触发器=北极星显式关联卡未闭环(8)/DISPATCH未审超阈(true)。',
            '- ASSERT decision-log-count: 本周 `DECISION_LOG.md` 决策行 30 条；数据源: `shared/toolkit/governance/DECISION_LOG.md`。',
            '- ASSERT decision-log-class-counts: {{"链路设计": 7, "人闸演进": 4, "展示面边界": 3, "北极星": 2}}；数据源: `shared/toolkit/governance/DECISION_LOG.md`。',
          ].join('\\n'),
          source_ref: {{ path: 'shared/toolkit/governance/weekly_review/2026-07-10.generated.md', exists: true }},
        }},
        autogrant_receipt: {{
          week_start: '2026-07-06', week_end: '2026-07-12', count: 0, recent_entries: [],
          empty_state: '本周无代批',
          source_ref: {{ path: 'shared/toolkit/governance/DECISION_LOG.md', exists: true }},
        }},
        outbound_ledger: {{
          count: 9,
          entries: [
            {{ ts: '2026-07-05T01:00:00+00:00', channel: 'general', verdict: 'hit', target: 'a', source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', line: 8, exists: true }} }},
            {{ ts: '2026-07-06T19:35:32+00:00', channel: 'review-packet', verdict: 'pass', target: 'clean', source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', line: 9, exists: true }} }},
          ],
          source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', exists: true }},
        }},
        active_decisions: {{
          count: 3,
          entries: [
            {{ label: '停止线', status: 'owner-confirmed 0707', body: '既往投入已封账。', source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', line: 6, exists: true }} }},
            {{ label: '北极星', status: 'ai-draft 待追认', body: '30天唯一问题。', source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', line: 7, exists: true }} }},
            {{ label: '线后清单', status: 'unknown', body: '暂空。', source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', line: 8, exists: true }} }},
          ],
          source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', exists: true }},
        }},
        pending_decisions: {{
          ok: true, count: 7, entries: [],
          empty_state: '无待追认的决策草稿',
          source_ref: {{ path: 'shared/toolkit/governance/DECISION_LOG.md', label: 'DECISION_LOG.md 自动草稿区', exists: true }},
        }},
      }};

      const {{ ctx, document }} = await renderConsoleWithData(dataState, {{
        audienceMode: 'owner',
        attention_gateDuty: {{ data: dutyData, loadedAt: Date.parse('2026-07-11T12:00:00Z') }},
      }});
      setupRenderGovernance(ctx);
      ctx.renderBoard.switchView('governance');
      const view = document.getElementById('vw-governance');
      const text = view.textContent || '';

      // 段序 = 决策流：等 Owner 动作的 → 人闸值守 → 自治运行的 → 台账。
      const order = ['等 Owner 动作的', '人闸值守', '自治运行的', '基建维护台账'].map((label) => text.indexOf(label));
      if (order.some((idx) => idx < 0)) throw new Error('治理页缺段: ' + JSON.stringify(order));
      if (!(order[0] < order[1] && order[1] < order[2] && order[2] < order[3])) throw new Error('段序必须是决策流档位: ' + JSON.stringify(order));

      // 值守段主干 = 3-6 行断言，每行带源指针按钮。
      const lines = view.querySelectorAll('.gov-duty-lines')[0];
      if (!lines) throw new Error('值守段缺断言主干');
      const rows = lines.querySelectorAll('.gov-duty-line');
      if (rows.length < 3 || rows.length > 6) throw new Error('值守主干应为 3-6 行断言, got ' + rows.length);
      for (const row of rows) {{
        if (!row.querySelector('.console-duty-source')) throw new Error('断言行必须带源指针: ' + row.textContent);
      }}

      // 断言内容与 fixture 可对账。
      for (const phrase of [
        '本周周报有需要你动作的触发器：北极星显式关联卡未闭环(8)/DISPATCH未审超阈(true)',
        '本周决策入账 30 条 · 最多的三类：链路设计 7、人闸演进 4、展示面边界 3',
        '本周无代批',
        '外发台账最近 2 条 · 最后 2026-07-06 pass',
        '活跃决策条 3 条 · 1 条 owner-confirmed · 1 条待追认 · 1 条待定血统',
      ]) {{
        if (!text.includes(phrase)) throw new Error('值守断言缺失: ' + phrase);
      }}

      // accent：值守段唯一 accent = action-required 行；待追认行 accent 在「等 Owner 动作的」段。
      const dutyAccents = Array.from(lines.querySelectorAll('.gov-duty-line-text')).filter((el) => el.classList.contains('is-waiting'));
      if (dutyAccents.length !== 1) throw new Error('值守段 accent 必须恰一处, got ' + dutyAccents.length);
      if (!dutyAccents[0].textContent.includes('需要你动作的触发器')) throw new Error('值守段 accent 必须落在 action-required 行');

      // 待追认线：数字 + accent + 源指针。
      if (!text.includes('待你追认的决策草稿 7 条')) throw new Error('「等 Owner 动作的」段应显示待追认草稿 7 条');
      const allAccentLines = Array.from(view.querySelectorAll('.gov-duty-line-text')).filter((el) => el.classList.contains('is-waiting'));
      if (allAccentLines.length !== 2) throw new Error('全页 gov-duty-line accent 应为 2 处（action-required + 待追认）, got ' + allAccentLines.length);
      const pendingLine = allAccentLines.find((el) => el.textContent.includes('待你追认'));
      if (!pendingLine) throw new Error('待追认行必须 accent');
      if (!pendingLine.parentElement.querySelector('.console-duty-source')) throw new Error('待追认行必须带源指针');

      // 折叠明细复用原四块，默认收起。
      const fold = view.querySelector('.gov-duty-fold');
      if (!fold) throw new Error('值守段必须有折叠明细区');
      if (fold.getAttribute && fold.getAttribute('open')) throw new Error('折叠明细必须默认收起');
      const panel = fold.querySelector('#console-attention_gate-duty');
      if (!panel) throw new Error('折叠明细必须整体复用值守面板');
      if (panel.querySelectorAll('.console-duty-block').length !== 4) throw new Error('折叠明细必须保留原四块');
      console.log('governance duty section ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'governance duty section ok' in result.stdout


def test_owner_audience_runtime_renders_duty_panel_plain_assertions():
    pytest.skip('KAN-1446: render-governance.js 已归档，治理页值守运行时不再是活动 surface')
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ renderConsoleWithData }} from {str(_CONSOLE_RUNTIME_HARNESS.as_uri())!r};
      import {{ setupRenderGovernance }} from {str(_RENDER_GOVERNANCE.as_uri())!r};

      const dataState = {{
        generated_at: '2026-07-07 10:00',
        stats: {{ total_tasks: 1, projects: 1, active_projects: 1 }},
        auth: {{ authenticated: true, user: 'Owner' }},
        login_members: ['Owner'],
        members: ['Owner'],
        all_members: ['Owner', 'Codex'],
        ai_members: ['Codex'],
        project_names: ['个人调度'],
        research_boards: [],
        chains: [],
        tasks: [
          {{ task_id: 'KAN-1', path: 'project/个人调度/KAN-1.md', project: '个人调度', title: '待验收卡', status: 'review', assignee: 'Owner', priority: 'high', task_family: 'kanban' }},
        ],
      }};
      const dutyData = {{
        ok: true,
        weekly_review: {{
          exists: true,
          week: '2026-07-06..2026-07-12',
          generated_at: '2026-07-07T20:24:40+08:00',
          content: [
            '# 周报',
            '',
            '- ASSERT decision-log-count: 本周 `DECISION_LOG.md` 决策行 4 条；数据源: `shared/toolkit/governance/DECISION_LOG.md`。',
            '- ASSERT outbound-count: 本周 `OUTBOUND_LEDGER.jsonl` 外发闸记录 3 条；数据源: `shared/toolkit/governance/OUTBOUND_LEDGER.jsonl`。',
            '- ASSERT outbound-entry: 2026-07-06T01:00:00 target=`a` verdict=pass；source `shared/toolkit/governance/OUTBOUND_LEDGER.jsonl:1`。',
            '- ASSERT outbound-entry: 2026-07-06T02:00:00 target=`b` verdict=hit；source `shared/toolkit/governance/OUTBOUND_LEDGER.jsonl:2`。',
            '- ASSERT outbound-entry: 2026-07-06T03:00:00 target=`c` verdict=hit；source `shared/toolkit/governance/OUTBOUND_LEDGER.jsonl:3`。',
            '- ASSERT new-card-count: 本周新建看板卡 5 张；判定字段=`created`；数据源: `project/*/*.md` frontmatter。',
            '- ASSERT north-star-explicit-scope-count: 本周显式声明北极星关联的卡 5 张；判定字段=`north_star_relation`。',
            '- ASSERT north-star-unanswered-count: 本周新卡中未出现可机检答案形状（如 `推进第一单吗: 是/否`）的卡 2 张；未出现即按未答计。',
            '- ASSERT fs-new-project-shaped-count: 本周新出现项目形状目录 3 个；first_seen 来源为本机 `stat` birthtime/ctime；只读扫描。',
            '- ASSERT fs-new-project-shaped-dir: path=`/tmp/a` first_seen=2026-07-06 reason=marker kanban_card=no card_answered_north_star=n/a；verify command `stat /tmp/a`。',
            '- ASSERT fs-new-project-shaped-dir: path=`/tmp/b` first_seen=2026-07-06 reason=marker kanban_card=KAN-1(project/个人调度/KAN-1.md:7) card_answered_north_star=KAN-1:no；verify command `stat /tmp/b`。',
            '- ASSERT fs-new-project-shaped-dir: path=`/tmp/c` first_seen=2026-07-06 reason=marker kanban_card=no card_answered_north_star=n/a；verify command `stat /tmp/c`。',
          ].join('\\n'),
          source_ref: {{ path: 'shared/toolkit/governance/weekly_review/2026-07-07.generated.md', exists: true }},
        }},
        autogrant_receipt: {{
          week_start: '2026-07-06',
          week_end: '2026-07-12',
          count: 0,
          recent_entries: [],
          empty_state: '本周无代批',
          command: 'python3 shared/toolkit/governance/attention_gate_autogrant.py --weekly-receipt',
          source_ref: {{ path: 'shared/toolkit/governance/DECISION_LOG.md', exists: true }},
        }},
        outbound_ledger: {{
          count: 2,
          entries: [
            {{ ts: '2026-07-06T01:00:00+00:00', channel: 'general', verdict: 'hit', target: 'baseline', source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', line: 1, exists: true }} }},
            {{ ts: '2026-07-06T02:00:00+00:00', channel: 'review-packet', verdict: 'pass', target: 'clean', source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', line: 2, exists: true }} }},
          ],
          source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', exists: true }},
        }},
        active_decisions: {{
          count: 2,
          entries: [
            {{ label: '停止线', status: 'owner-confirmed 0707', body: '既往投入已封账。', source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', line: 6, exists: true }} }},
            {{ label: '北极星', status: 'ai-draft 待追认', body: '30天唯一问题。', source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', line: 7, exists: true }} }},
          ],
          source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', exists: true }},
        }},
      }};

      // KAN-1001：值守面板搬进治理页人闸值守段的折叠明细，改在治理视图内取用。
      const {{ ctx, document, consoleView }} = await renderConsoleWithData(dataState, {{
        audienceMode: 'owner',
        attention_gateDuty: {{ data: dutyData, loadedAt: Date.parse('2026-07-07T12:00:00Z') }},
      }});
      if (consoleView.querySelector('#console-attention_gate-duty')) throw new Error('调度台不应再渲染值守面板');
      setupRenderGovernance(ctx);
      ctx.renderBoard.switchView('governance');
      const govView = document.getElementById('vw-governance');
      const panel = govView.querySelector('#console-attention_gate-duty');
      if (!panel) throw new Error('治理页折叠明细必须复用值守面板');
      if (panel.dataset.audience !== 'owner') throw new Error('Owner 值守区必须走 owner audience');
      if (panel.querySelector('.console-duty-markdown')) throw new Error('Owner 面不得直接渲染 ASSERT Markdown 原文');
      const text = panel.textContent;
      for (const phrase of [
        '本周决策账新增 4 条；外发闸记录 3 条（pass 1、hit 2）。',
        '本周有 5 张卡明确关联北极星，其中 2 张还没拿到「是否推进第一单」的回答。',
        '本周新出现项目形状目录 3 个，其中 2 个还没挂卡。',
        '本周人闸代批 0 件。',
        '外发台账当前可读 2 条，值守页展示最近 2 条',
        '已确认的活跃边界有 1 条：停止线。',
        '待你追认的活跃草案有 1 条：北极星。',
        '去核对',
      ]) {{
        if (!text.includes(phrase)) throw new Error('Owner 值守断言缺少: ' + phrase + '\\n' + text);
      }}
      const blocks = panel.querySelectorAll('.console-duty-block');
      if (blocks.length !== 4) throw new Error('值守区必须仍是四块，实际 ' + blocks.length);
      for (const block of blocks) {{
        const statements = block.querySelectorAll('.console-duty-owner-statement');
        if (statements.length < 1 || statements.length > 3) throw new Error('每块必须有 1-3 句白话断言');
      }}
      if (panel.querySelectorAll('.console-duty-owner-check').length !== panel.querySelectorAll('.console-duty-owner-statement').length) {{
        throw new Error('每句白话断言都必须有「去核对」');
      }}
      if (panel.querySelectorAll('[data-source-path]').length < 8) throw new Error('Owner 面证据必须保留 data-bound 源指针');
      console.log('owner duty panel assertions ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'owner duty panel assertions ok' in result.stdout


def test_attention_gate_audience_runtime_renders_duty_panel_with_source_refs():
    pytest.skip('KAN-1446: render-governance.js 已归档，治理页值守运行时不再是活动 surface')
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ renderConsoleWithData }} from {str(_CONSOLE_RUNTIME_HARNESS.as_uri())!r};
      import {{ setupRenderGovernance }} from {str(_RENDER_GOVERNANCE.as_uri())!r};

      const dataState = {{
        generated_at: '2026-07-07 10:00',
        stats: {{ total_tasks: 1, projects: 1, active_projects: 1 }},
        auth: {{ authenticated: true, user: 'Owner' }},
        login_members: ['Owner'],
        members: ['Owner'],
        all_members: ['Owner', 'Codex'],
        ai_members: ['Codex'],
        project_names: ['个人调度'],
        research_boards: [],
        chains: [],
        tasks: [
          {{ task_id: 'KAN-1', path: 'project/个人调度/KAN-1.md', project: '个人调度', title: '待验收卡', status: 'review', assignee: 'Owner', priority: 'high', task_family: 'kanban' }},
        ],
      }};
      const dutyData = {{
        ok: true,
        weekly_review: {{
          exists: true,
          week: '2026-07-06..2026-07-12',
          generated_at: '2026-07-07T20:24:40+08:00',
          content: '# 周报\\n\\n- ASSERT live-read: 周报正文原样直读；数据源: `shared/toolkit/governance/weekly_review/2026-07-07.generated.md`。',
          source_ref: {{ path: 'shared/toolkit/governance/weekly_review/2026-07-07.generated.md', exists: true }},
        }},
        autogrant_receipt: {{
          week_start: '2026-07-06',
          week_end: '2026-07-12',
          count: 0,
          recent_entries: [],
          empty_state: '本周无代批',
          source_ref: {{ path: 'shared/toolkit/governance/DECISION_LOG.md', exists: true }},
        }},
        outbound_ledger: {{
          count: 1,
          entries: [{{ ts: '2026-07-06T19:35:32+00:00', channel: 'review-packet', verdict: 'pass', target: 'clean', source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', line: 5, exists: true }} }}],
          source_ref: {{ path: 'shared/toolkit/governance/OUTBOUND_LEDGER.jsonl', exists: true }},
        }},
        active_decisions: {{
          count: 1,
          entries: [{{ label: '停止线', status: 'owner-confirmed 0707', body: '既往投入已封账。', source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', line: 6, exists: true }} }}],
          source_ref: {{ path: 'shared/toolkit/governance/ATTENTION_GATE_ACTIVE.md', exists: true }},
        }},
      }};

      // KAN-1001：值守面板搬进治理页人闸值守段的折叠明细，改在治理视图内取用。
      const {{ ctx, document, consoleView }} = await renderConsoleWithData(dataState, {{
        audienceMode: 'attention_gate',
        attention_gateDuty: {{ data: dutyData, loadedAt: Date.parse('2026-07-07T12:00:00Z') }},
      }});
      if (consoleView.querySelector('#console-attention_gate-duty')) throw new Error('调度台不应再渲染值守面板');
      setupRenderGovernance(ctx);
      ctx.renderBoard.switchView('governance');
      const govView = document.getElementById('vw-governance');
      const panel = govView.querySelector('#console-attention_gate-duty');
      if (!panel) throw new Error('治理页折叠明细必须复用值守面板（人闸视角）');
      const text = panel.textContent;
      for (const label of ['值守', '本周周报', '代批回执', '外发台账尾巴', '活跃决策条', '本周无代批']) {{
        if (!text.includes(label)) throw new Error('值守区缺少文案: ' + label + '\\n' + text);
      }}
      const assertEl = panel.querySelector('.console-duty-assert');
      if (!assertEl) throw new Error('人闸视角必须渲染周报 ASSERT 条目');
      const assertText = assertEl.textContent;
      if (!assertText.includes('live-read') || !assertText.includes('周报正文原样直读')) {{
        throw new Error('人闸视角必须保留周报 ASSERT 原文（key+断言正文逐字）\\n' + assertText);
      }}
      if (panel.querySelector('.console-duty-owner-statement')) throw new Error('人闸视角不得混入 Owner 白话断言组件');
      if (text.includes('content_sha256') || text.includes('secret-hash')) throw new Error('外发台账不得显示 hash 细节');
      const blocks = panel.querySelectorAll('.console-duty-block');
      if (blocks.length !== 4) throw new Error('值守区必须是四块，实际 ' + blocks.length);
      for (const block of blocks) {{
        if (!block.dataset.sourcePath) throw new Error('每个值守块必须有 data-source-path');
      }}
      if (panel.querySelectorAll('.console-duty-source').length !== 4) throw new Error('每块必须有源文件按钮');
      if (panel.querySelectorAll('[data-source-path]').length < 8) throw new Error('展示元素必须带 data-bound 源指针');
      console.log('attention_gate duty panel runtime ok');
    """
    result = subprocess.run([node, '--input-type=module', '-e', script], capture_output=True, text=True, check=True)
    assert 'attention_gate duty panel runtime ok' in result.stdout


def test_console_bridge_subtraction_keeps_network_doctor_without_local_tool_menu():
    source = _render_board_source()
    html_source = _KANBAN_HTML.read_text(encoding='utf-8')
    main_source = _MAIN_JS.read_text(encoding='utf-8')
    # KAN-1445：退役桥接盒定义，只保留右栏活桥接与网络医生。
    bridges = source[source.index('function makeNetworkStatusBlock()'):source.index('// ── 调度台 Flow')]
    if "'claude-fleet'" in bridges or 'Claude Fleet' in bridges:
        raise AssertionError('Claude Fleet 不能继续作为调度台固定桥接按钮渲染')
    if "'business-threads-board'" in source or '商业线索板' in source:
        raise AssertionError('不存在的 business-threads-board launcher 不应继续渲染')
    if '未发现面板（约定：项目目录下 *_Panel.html 或 PANEL.md）' in bridges:
        raise AssertionError('研究项目 0 面板时不能渲染空态文案')
    if '__KANBAN_OPTIONAL_LOCAL_TOOL_ITEMS__' in html_source or 'data-local-tool=' in html_source:
        raise AssertionError('汉堡菜单不得保留本地工具注入位')
    if 'dataState.local_integrations' in main_source:
        raise AssertionError('前端不应继续装配本地工具菜单目标')
    network_fn = bridges
    if '!ctx.hasApi && dataState.clash_configured' not in network_fn or 'return null' not in network_fn:
        raise AssertionError('live API 模式必须显示网络医生；静态未配置时才隐藏')
    for needle in ("'检查网络', 'diagnose'", "'一键修复', 'fix'", "'断网急救', 'emergency'"):
        if needle not in network_fn:
            raise AssertionError(f'网络医生缺少固定动作: {needle}')


def test_console_project_map_links_normalize_and_filter_task_family():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ normalizeProjectMapFamily }} from {str(_RENDER_BOARD.as_uri())!r};
      if (normalizeProjectMapFamily('SKL') !== 'skill') throw new Error('SKL should normalize to skill');
      if (normalizeProjectMapFamily('unknown-family') !== '') throw new Error('unknown family should be filtered');
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_detail_canvas_default_action_is_soft_unbound():
    source = _render_detail_source()
    for retired in ('function appendCanvasStatus(', 'appendCanvasStatus(task)', '打开任务工作台', 'detail-canvas-status-card'):
        if retired in source:
            raise AssertionError(f'详情页 Canvas 默认动作应软解绑，仍发现: {retired}')


def test_chain_flow_detail_is_click_opened_from_project_health():
    source = _render_board_source()
    flow_fn = source[source.index('function makeChainFlowDetailBlock(options = {})'):source.index('function makeGovernanceBurdenMetric')]
    open_fn = source[source.index('function openChainFlow('):source.index('function flowStageTone')]
    if 'if (!uiState.board.chainFlowExpanded) return null;' not in flow_fn:
        raise AssertionError('Flow 详情不能默认展开（链行点击才展开）')
    if 'uiState.board.chainFlowExpanded = true;' not in open_fn:
        raise AssertionError('点击项目健康链路时必须展开 Flow 详情')
    # KAN-1002：Flow 详情迁治理页——openChainFlow 必须切治理视图，不再切回调度台。
    if "switchView('governance')" not in open_fn:
        raise AssertionError('openChainFlow 必须页内展开于治理页（switchView governance）')
    if "switchView('console')" in open_fn:
        raise AssertionError('openChainFlow 不得再切回调度台（KAN-998 跨视图跳转尾巴已治）')
    if 'function makeProjectHealthBlock(' in source or 'console-project-health-head' in source:
        raise AssertionError('项目健康入口已随 render-governance 归档，活动 render-board 不应保留')


def test_bridge_launch_feedback_distinguishes_starting_from_ready():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ bridgeLaunchFeedback }} from {str(_RENDER_BOARD.as_uri())!r};
      const starting = bridgeLaunchFeedback('starting');
      if (starting.state !== 'pending' || starting.poll !== true) {{
        throw new Error('starting bridge launches should stay pending and poll');
      }}
      if (starting.toastLabel.includes('已启动') || starting.metaLabel.includes('已启动')) {{
        throw new Error('starting bridge launches must not be reported as already started');
      }}
      const started = bridgeLaunchFeedback('started');
      if (started.state !== 'ready' || started.poll !== false || !started.metaLabel.includes('已就绪')) {{
        throw new Error('started bridge launches should render as ready');
      }}
      const running = bridgeLaunchFeedback('already_running');
      if (running.state !== 'ready' || !running.metaLabel.includes('已在运行')) {{
        throw new Error('already_running bridge launches should render as running');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_team_digest_stale_or_empty_collapses_to_still_line():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ consoleTeamDigestEntries, teamDigestStillText }} from {str(_RENDER_BOARD.as_uri())!r};
      const stale = {{
        ok: true,
        is_stale: true,
        generated_at: '2026-07-01T10:00:00+08:00',
        entries: [
          {{ title: 'old card', timestamp: '2026-07-02T09:00:00+08:00' }},
        ],
      }};
      if (consoleTeamDigestEntries(stale, 8).length !== 0) {{
        throw new Error('stale digest entries should not render as card summaries');
      }}
      if (teamDigestStillText(stale) !== '团队数据源静止（最近 2026-07-02）') {{
        throw new Error(`unexpected stale digest text: ${{teamDigestStillText(stale)}}`);
      }}
      const emptyFresh = {{ ok: true, generated_at: '2999-01-01T00:00:00+08:00', entries: [] }};
      if (consoleTeamDigestEntries(emptyFresh, 8).length !== 0) {{
        throw new Error('empty digest should stay empty');
      }}
      if (!teamDigestStillText(emptyFresh).includes('2999-01-01')) {{
        throw new Error('empty digest still line should carry the latest digest date');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_automation_result_summary_and_links_expose_report_paths():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ automationResultLinks, automationResultSummary }} from {str(_RENDER_BOARD.as_uri())!r};
      const task = {{
        id: 'fm96_minutes_sync',
        health: '正常',
        reason: 'commands completed',
        last_checked: '2026-06-28T21:07:38',
        last_run_md: '/tmp/last_run.md',
        last_run_json: '/tmp/last_run.json',
      }};
      const live = {{
        ok: true,
        status: 'completed',
        health: '正常',
        reason: 'commands completed',
        finished_at: '2026-06-28T21:07:38',
        last_run_md: '/tmp/last_run.md',
        last_run_json: '/tmp/last_run.json',
        outputs: [
          {{
            label: 'sync_fm96_minutes',
            returncode: 0,
            stdout_tail: '{{"sync_result_json":"/tmp/result.json","queue_jsonl":"/tmp/source_queue.jsonl","output_dir":"/tmp/out"}}',
          }},
        ],
        output_links: [{{ label: '摘要', path: '/tmp/review.md', kind: 'report' }}],
      }};
      const summary = automationResultSummary(task, live);
      if (summary.tone !== 'ok' || summary.label !== '正常') {{
        throw new Error(`unexpected summary: ${{JSON.stringify(summary)}}`);
      }}
      if (!summary.meta.includes('06-28 21:07') || !summary.commands.includes('sync_fm96_minutes=0')) {{
        throw new Error('summary should include timestamp and command return code');
      }}
      const links = automationResultLinks(task, live);
      const byLabel = new Map(links.map((link) => [link.label + ':' + link.path, link]));
      for (const key of ['报告:/tmp/last_run.md', 'JSON:/tmp/last_run.json', '摘要:/tmp/review.md', '结果:/tmp/result.json', '队列:/tmp/source_queue.jsonl', '目录:/tmp/out']) {{
        if (!byLabel.has(key)) throw new Error(`missing result link ${{key}} in ${{JSON.stringify(links)}}`);
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_landing_page_task_index_prioritizes_stale_pages():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ landingPageTasks, landingPageDriftState }} from {str(_RENDER_BOARD.as_uri())!r};
      const tasks = [
        {{ task_id: 'XXX-1', title: 'fresh', landing_page: 'landing/fresh.html', landing_updated: '2026-06-14', updated: '2026-06-14' }},
        {{ task_id: 'XXX-2', title: 'stale', landing_page: 'landing/stale.html', landing_updated: '2026-06-13', updated: '2026-06-14' }},
        {{ task_id: 'XXX-3', title: 'no landing', updated: '2026-06-14' }},
        {{ task_id: 'XXX-4', title: 'missing date', landing_page: 'landing/missing.html', updated: '2026-06-12' }},
      ];
      const indexed = landingPageTasks(tasks);
      if (indexed.map((task) => task.task_id).join(',') !== 'XXX-2,XXX-4,XXX-1') {{
        throw new Error(`unexpected landing index order: ${{indexed.map((task) => task.task_id).join(',')}}`);
      }}
      if (!landingPageDriftState(tasks[1]).stale) throw new Error('outdated landing should be stale');
      if (!landingPageDriftState(tasks[3]).stale) throw new Error('missing landing_updated should be stale when task has updated date');
      if (landingPageDriftState(tasks[0]).stale) throw new Error('same-day landing should be fresh');
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_governance_burden_model_keeps_human_gate_small():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{
        buildGovernanceBurdenModel,
        isGovernanceBurdenTask,
        isGovernanceConsoleHiddenTask,
      }} from {str(_RENDER_BOARD.as_uri())!r};
      const tasks = [
        {{
          task_id: 'GOV-11',
          task_family: 'governance',
          title: 'G2-G7 机器判定探针',
          status: 'todo',
          responsibility: 'ai-owned',
          safety: 'read-only',
          updated: '2026-06-18',
        }},
        {{
          // 2026-07-03 语义更新:review 卡无条件豁免治理分流(进「等我验收」),
          // 故本 fixture 改用 todo+pi-gated 表达「治理人闸卡」,保持 burden 模型算术不变。
          task_id: 'DOC-1',
          task_family: 'documents',
          title: 'Documents 治理收口',
          status: 'todo',
          assignee: 'Owner',
          responsibility: 'pi-gated',
          safety: 'mutating',
          updated: '2026-06-17',
        }},
        {{
          task_id: 'SKL-2',
          task_family: 'skill',
          title: 'skill 注册表治理',
          status: 'todo',
          assignee: 'Codex',
          updated: '2026-06-16',
        }},
        {{
          // 2026-07-03 语义更新:kanban 家族卡的治理身份必须显式声明(domain/tags/stage),
          // 标题关键词不再触发分流(旧行为曾把产品卡误扫出调度台)。
          task_id: 'KAN-9',
          task_family: 'kanban',
          title: '看板治理按钮显化',
          domain: 'governance',
          status: 'todo',
          safety: 'read-only',
          updated: '2026-06-15',
        }},
        {{
          task_id: 'KAN-5',
          task_family: 'kanban',
          title: '产品构思总页',
          status: 'todo',
        }},
        {{
          task_id: 'GOV-0',
          task_family: 'governance',
          title: '已完成治理旧卡',
          status: 'done',
        }},
        {{
          task_id: 'KMO-12',
          task_family: 'knowledge',
          domain: 'team',
          title: '团队策展层：能力×场景矩阵',
          next_action: '需要 Owner 终校能力清单',
          responsibility: 'pi-gated',
          status: 'todo',
        }},
        {{
          task_id: 'RSH-2',
          task_family: 'research',
          domain: 'research',
          title: '复盘研究方法咨询任务管理流程',
          next_action: '决定是否需要归档规则',
          responsibility: 'pi-gated',
          status: 'todo',
        }},
      ];
      if (isGovernanceBurdenTask(tasks[4])) throw new Error('plain KAN product cards should not count as governance burden');
      if (isGovernanceBurdenTask(tasks[5])) throw new Error('done governance cards should not count as active burden');
      if (!isGovernanceConsoleHiddenTask(tasks[5])) throw new Error('done governance cards should still be hidden from primary console lanes');
      if (isGovernanceBurdenTask(tasks[6])) throw new Error('knowledge matrix/gate cards should not be mistaken for governance burden');
      if (isGovernanceBurdenTask(tasks[7])) throw new Error('research workflow/rule cards should not be mistaken for governance burden');
      const model = buildGovernanceBurdenModel(tasks, ['Codex'], 'Owner');
      if (model.total !== 4) throw new Error(`expected 4 active governance items, got ${{model.total}}`);
      if (model.needsDecision !== 1) throw new Error(`expected one human gate, got ${{model.needsDecision}}`);
      if (model.aiReducible !== 3) throw new Error(`expected three reducible items, got ${{model.aiReducible}}`);
      if (model.machineCheckable !== 1) throw new Error(`expected one machine-checkable probe, got ${{model.machineCheckable}}`);
      const buckets = Object.fromEntries(model.buckets.map((bucket) => [bucket.key, bucket.count]));
      if (buckets.kanban !== 1 || buckets.skills !== 1 || buckets.rules !== 2) {{
        throw new Error(`unexpected governance buckets: ${{JSON.stringify(buckets)}}`);
      }}
      const kanbanBucket = model.buckets.find((bucket) => bucket.key === 'kanban');
      if (!kanbanBucket || kanbanBucket.tasks.length !== 1 || kanbanBucket.tasks[0].task_id !== 'KAN-9') {{
        throw new Error('governance bucket should expose every concrete task, not only a representative card');
      }}
      const mainConsoleTasks = tasks
        .filter((task) => task.status !== 'done')
        .filter((task) => !isGovernanceConsoleHiddenTask(task));
      if (mainConsoleTasks.some((task) => ['GOV-11', 'DOC-1', 'SKL-2', 'KAN-9'].includes(task.task_id))) {{
        throw new Error('governance burden cards should be removed from the primary console action lanes');
      }}
      if (!mainConsoleTasks.some((task) => task.task_id === 'KAN-5')) {{
        throw new Error('ordinary KAN product cards should remain available outside governance burden');
      }}
      if (!mainConsoleTasks.some((task) => task.task_id === 'KMO-12') || !mainConsoleTasks.some((task) => task.task_id === 'RSH-2')) {{
        throw new Error('non-governance PI-gated work should remain in primary console lanes');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_governance_healthcheck_toast_text():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{
        governanceHealthcheckRunStatusText,
        governanceHealthcheckRunStatusTone,
        governanceHealthcheckScheduleItem,
        governanceHealthcheckStatusText,
        governanceHealthcheckStatusTone,
        governanceHealthcheckToastText,
      }} from {str(_RENDER_BOARD.as_uri())!r};
      const ok = governanceHealthcheckToastText({{ ok: true, health: '正常', reason: 'commands completed' }});
      if (ok !== '治理体检完成：正常 · commands completed') {{
        throw new Error(`unexpected success text: ${{ok}}`);
      }}
      const failed = governanceHealthcheckToastText({{ ok: false, error: 'required paths missing' }});
      if (failed !== 'required paths missing') {{
        throw new Error(`unexpected failure text: ${{failed}}`);
      }}
      const schedule = {{
        ok: true,
        active: [
          {{ id: 'other_scan', health: '正常', status: 'ACTIVE' }},
          {{ id: 'governance_scan', health: '正常', status: 'ACTIVE', reason: 'preflight passed' }},
        ],
      }};
      if (governanceHealthcheckScheduleItem(schedule).reason !== 'preflight passed') {{
        throw new Error('governance_scan schedule item not found');
      }}
      if (governanceHealthcheckStatusText(schedule) !== '正常') {{
        throw new Error(`unexpected schedule text: ${{governanceHealthcheckStatusText(schedule)}}`);
      }}
      if (governanceHealthcheckStatusTone(schedule) !== 'good') {{
        throw new Error('normal health should be good tone');
      }}
      const bad = {{ ok: true, active: [{{ id: 'governance_scan', health: '异常', status: 'ACTIVE' }}] }};
      if (governanceHealthcheckStatusTone(bad) !== 'bad') {{
        throw new Error('abnormal health should be bad tone');
      }}
      const missing = {{ ok: true, active: [] }};
      if (governanceHealthcheckStatusText(missing) !== '未配置') {{
        throw new Error(`unexpected missing text: ${{governanceHealthcheckStatusText(missing)}}`);
      }}
      const runWithSignals = {{ ok: true, latest: {{ health: '有信号', signal_count: 6, failed_command_count: 0 }} }};
      if (governanceHealthcheckRunStatusText(runWithSignals) !== '有信号') {{
        throw new Error(`unexpected run text: ${{governanceHealthcheckRunStatusText(runWithSignals)}}`);
      }}
      if (governanceHealthcheckRunStatusTone(runWithSignals) !== 'running') {{
        throw new Error('signal health should use running tone');
      }}
      const cleanRun = {{ ok: true, latest: {{ health: '正常', signal_count: 0, failed_command_count: 0 }} }};
      if (governanceHealthcheckRunStatusTone(cleanRun) !== 'good') {{
        throw new Error('clean health should be good tone');
      }}
      const failedRun = {{ ok: true, latest: {{ health: '正常', failed_command_count: 1 }} }};
      if (governanceHealthcheckRunStatusTone(failedRun) !== 'bad') {{
        throw new Error('failed commands should be bad tone');
      }}
      const staleBackend = {{ ok: true, latest: {{ health: '服务待重启', service_restart_required: true }} }};
      if (governanceHealthcheckRunStatusText(staleBackend) !== '服务待重启') {{
        throw new Error(`unexpected stale backend text: ${{governanceHealthcheckRunStatusText(staleBackend)}}`);
      }}
      if (governanceHealthcheckRunStatusTone(staleBackend) !== 'running') {{
        throw new Error('stale backend should use running tone');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_governance_noise_review_status_text():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{
        governanceNoiseReviewStatusText,
        governanceNoiseReviewStatusTone,
      }} from {str(_RENDER_BOARD.as_uri())!r};
      const empty = governanceNoiseReviewStatusText({{ ok: true, latest: null }});
      if (empty !== '尚未运行') throw new Error(`unexpected empty text: ${{empty}}`);
      const running = {{
        latest: {{
          id: '421ec89f',
          status: 'running',
          metadata: {{ candidate_total: 6 }},
        }},
      }};
      if (governanceNoiseReviewStatusText(running) !== '运行中 · #421ec89f') {{
        throw new Error(`unexpected running text: ${{governanceNoiseReviewStatusText(running)}}`);
      }}
      if (governanceNoiseReviewStatusTone(running) !== 'running') {{
        throw new Error('running tone mismatch');
      }}
      const completed = {{
        latest: {{
          id: 'abc12345',
          status: 'completed',
          metadata: {{ candidate_total: 6 }},
          metrics: {{ owner_visible_after: 1 }},
        }},
      }};
      if (governanceNoiseReviewStatusText(completed) !== '已完成 · #abc12345') {{
        throw new Error(`unexpected completed text: ${{governanceNoiseReviewStatusText(completed)}}`);
      }}
      if (governanceNoiseReviewStatusTone(completed) !== 'good') {{
        throw new Error('completed tone mismatch');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_frontend_chain_config_normalization_preserves_responsibility():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ normalizeFrontendChains }} from {str(_RENDER_BOARD.as_uri())!r};
      const chains = normalizeFrontendChains([
        {{
          key: 'km',
          title: '知识管理链',
          provider: 'rko-knowledge-layers',
          stages: [
            {{ key: 'km/source_intake', title: '入口', responsibility: 'ai-owned' }},
            {{ key: 'km/triage_queue', title: '队列', responsibility: 'shared' }},
            {{ key: 'km/card_reading', title: '精读', responsibility: 'pi-gated' }},
          ],
        }},
        {{ key: 'empty', stages: [] }},
        null,
      ]);
      if (chains.length !== 1) throw new Error(`expected one valid chain, got ${{chains.length}}`);
      if (chains[0].title !== '知识管理链') throw new Error('title should come from config');
      if (chains[0].provider !== 'rko-knowledge-layers') throw new Error('provider should come from config');
      const responsibilities = chains[0].stages.map((stage) => stage.responsibility).join(',');
      if (responsibilities !== 'ai-owned,shared,pi-gated') {{
        throw new Error(`responsibility passthrough failed: ${{responsibilities}}`);
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_frontend_chain_stage_tone_keeps_pi_waiting_neutral():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ chainStatusTone, chainStageTone }} from {str(_RENDER_BOARD.as_uri())!r};
      const checks = [
        [chainStatusTone('pi-gated-waiting', 'pi-gated'), 'pi-waiting', 'explicit pi waiting'],
        [chainStatusTone('waiting', 'pi-gated'), 'pi-waiting', 'waiting pi gate'],
        [chainStageTone({{ responsibility: 'pi-gated' }}, {{ state: 'waiting' }}), 'pi-waiting', 'stage pi gate'],
        [chainStatusTone('failed', 'pi-gated'), 'error', 'failed remains red'],
        [chainStatusTone('drift', 'shared'), 'error', 'drift remains red'],
        [chainStatusTone('warn', 'shared'), 'warn', 'warn remains warning'],
      ];
      for (const [actual, expected, label] of checks) {{
        if (actual !== expected) throw new Error(`${{label}}: expected ${{expected}}, got ${{actual}}`);
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_frontend_chain_buckets_skip_team_pointers_without_explicit_stage():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required to import the frontend ES module')

    script = f"""
      import {{ buildChainStageBuckets }} from {str(_RENDER_BOARD.as_uri())!r};
      const chains = [{{
        key: 'team',
        stages: [{{ key: 'team/publish', title: '发布授权', kw: ['团队', '分发'] }}],
      }}];
      const tasks = [
        {{ title: '团队分发准备误归类指针', status: 'todo', source: 'team-kanban/TK-1' }},
        {{ title: '团队分发准备显式归类指针', status: 'todo', source: 'team-kanban/TK-2', stage: 'team/publish' }},
        {{ title: '团队分发普通任务', status: 'todo', source: '', stage: '' }},
      ];
      const buckets = buildChainStageBuckets(tasks, chains);
      const staged = buckets.byChain.team['team/publish'];
      // KAN-999：stage.kw 关键词兜底已退役——只有显式 stage 的卡入链；
      // 无显式 stage 的普通卡进 unassigned，隐式团队指针整体跳过（不入链也不入 unassigned）。
      if (staged.length !== 1) throw new Error(`expected 1 staged task (explicit stage only), got ${{staged.length}}`);
      if (staged[0].source !== 'team-kanban/TK-2') throw new Error('explicit team pointer should remain staged');
      if (buckets.unassigned.length !== 1 || buckets.unassigned[0].title !== '团队分发普通任务') {{
        throw new Error('ordinary card without explicit stage should go to unassigned (keyword routing retired)');
      }}
    """
    subprocess.run([node, '--input-type=module', '-e', script], check=True)


def test_console_research_entry_group_renamed_without_sih_page_runner():
    source = _render_board_source()

    assert '研究项目入口' not in source
    assert '研究与知识板' not in source
    assert 'makeDynamicBoardsBlock({ hideWhenEmpty: true })' not in source
    assert '/api/sih-source-today/run' not in source
    assert '/api/dynamic-boards/run' not in source
