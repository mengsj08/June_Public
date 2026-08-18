"""KAN-7 公众态入口 — default-deny 脱敏与泄露红线回归。

核心不变量：未登录公众页只露形态计数，绝不漏真实任务标题 / 指派 / 本机路径 / 会议代号。
"""
import re
from pathlib import Path
import importlib.util
import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


def test_public_preview_is_default_deny():
    """没有任何卡显式标 public_safe 时，预览只出计数，cards 必须为空。"""
    preview = scan_mod.build_public_preview()
    assert set(preview.keys()) >= {'lanes', 'cards', 'totals'}
    # default-deny：当前仓没有 public_safe 卡 → 一张卡都不该出
    safe_docs = [d for d in scan_mod.scan_all() if d.get('public_safe') is True]
    if not safe_docs:
        assert preview['cards'] == []
    # lanes 只含 label + 整数 count，不含任何标题字段
    for lane in preview['lanes']:
        assert set(lane.keys()) == {'label', 'count'}
        assert isinstance(lane['count'], int)


@pytest.mark.skipif(not scan_mod._COCKPIT_LANDING_PATH.is_file(), reason='missing optional source path: landing/cockpit-landing.html')
def test_public_entry_html_leaks_no_real_titles():
    """泄露红线：任何真实 active 卡标题都不得出现在未登录公众页。"""
    html = scan_mod.render_public_entry_html()
    assert html, '公众页应能渲染（cockpit-landing.html 存在）'
    docs = scan_mod.scan_all()
    leaked = []
    for d in docs:
        if d.get('status', 'todo') == 'done':
            continue
        if d.get('public_safe') is True:
            continue  # 显式放行的卡不算泄露
        title = (d.get('title') or '').strip()
        # 只校验有辨识度的标题（≥6 字符），避免极短词误伤
        if len(title) >= 6 and title in html:
            leaked.append(title)
    assert not leaked, f'公众页泄露了真实卡标题: {leaked[:5]}'


@pytest.mark.skipif(not scan_mod._COCKPIT_LANDING_PATH.is_file(), reason='missing optional source path: landing/cockpit-landing.html')
def test_public_entry_html_leaks_no_paths_or_codenames():
    """公众页不得含本机路径或代号形态 token。"""
    html = scan_mod.render_public_entry_html()
    assert html
    assert '/Users/' not in html
    assert 'project/个人调度' not in html
    # 代号形态（cli_xxxxxx）不得出现
    assert not re.search(r'\bcli_[a-z0-9]{6,}\b', html, re.IGNORECASE)


@pytest.mark.skipif(not scan_mod._COCKPIT_LANDING_PATH.is_file(), reason='missing optional source path: landing/cockpit-landing.html')
def test_public_entry_has_hero_and_cta():
    """公众页 = cockpit 价值主张（唯一来源）+ 进入驾驶舱 CTA。"""
    html = scan_mod.render_public_entry_html()
    assert html
    assert '把时间还给决策' in html          # hero 来自 cockpit-landing.html
    assert '/?app=1' in html                  # CTA 进入 app 壳走既有登录
    assert '此刻在跑' in html                  # 脱敏计数块


def test_redact_public_text_scrubs_paths_and_codenames():
    out = scan_mod._redact_public_text('看 /Users/example/secret 和 cli_a930b2c1 还有 FE72')
    assert '/Users/' not in out
    assert 'cli_a930b2c1' not in out
    assert 'FE72' not in out
