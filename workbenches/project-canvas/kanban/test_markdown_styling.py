#!/usr/bin/env python3
"""
Tests for Markdown Rendering Styling inside the task detail overlay.

Run with: CI=true python3 -m pytest shared/toolkit/kanban/test_markdown_styling.py -v

Uses Playwright to verify that rendered markdown elements have correct CSS styles:
headings, code blocks, inline code, lists, links, blockquotes, tables, and overflow behavior.
"""

import json
import os
import threading
import time
import tempfile
import shutil
import base64
from pathlib import Path
from unittest.mock import patch

import pytest
sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="optional Playwright dependency is not installed"
).sync_playwright

# Import the module -- file is scan-docs.py (dash, not underscore)
_HERE = Path(__file__).resolve().parent
import importlib.util

_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)
Handler = scan_mod.Handler
generate_html = scan_mod.generate_html


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture(scope='module')
def temp_repo_module():
    """Create a temp repo with a rich-markdown task file for all tests."""
    tmp = tempfile.mkdtemp(prefix='kanban_md_style_')
    tmp_path = Path(tmp)

    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)

    # Rich markdown task with all elements to test
    task = """---
title: Rich Markdown Task
created: 2026-05-01
updated: 2026-05-02
assignee: Alice
priority: high
status: todo
tags: [backend, api]
---

# Heading One

## Heading Two

### Heading Three

#### Heading Four

##### Heading Five

###### Heading Six

This is a paragraph with `inline code` embedded.

```python
def hello():
    print("hello world")
    return 42
```

```mermaid
graph LR
A-->B
```

- Unordered item 1
- Unordered item 2
- Unordered item 3

1. Ordered item 1
2. Ordered item 2

[Example Link](https://example.com)

> This is a blockquote with some text.
> It spans multiple lines.

| Column A | Column B |
|----------|----------|
| Cell 1   | Cell 2   |
| Cell 3   | Cell 4   |

┌──────────┬──────────┐
│ Header A │ Header B │
├──────────┼──────────┤
│ Value 1  │ Value 2  │
└──────────┴──────────┘

![Local Diagram](local-image.png)

"""
    (proj_dir / "rich-task.md").write_text(task, encoding='utf-8')
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z7xQAAAAASUVORK5CYII="
    )
    (proj_dir / "local-image.png").write_bytes(png_bytes)

    # A second task for scrolling tests
    long_body = "\n".join([f"## Section {i}\n\n" + "Lorem ipsum dolor sit amet. " * 20 + "\n" for i in range(50)])
    long_task = f"""---
title: Long Task
created: 2026-05-03
updated: 2026-05-03
assignee: Bob
priority: medium
status: in-progress
tags: []
---

{long_body}
"""
    (proj_dir / "long-task.md").write_text(long_task, encoding='utf-8')

    yield tmp_path

    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope='module')
def server_url(temp_repo_module):
    """Start an HTTP server on a free port and return its base URL."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]

    with patch.object(scan_mod, 'REPO_ROOT', temp_repo_module):
        server = scan_mod.HTTPServer(('127.0.0.1', port), scan_mod.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.3)
        yield f'http://127.0.0.1:{port}'
        server.shutdown()


@pytest.fixture
def page(server_url):
    """Create a fresh browser context and page for each test."""
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={'width': 1280, 'height': 800})
    p = context.new_page()
    p.goto(server_url)
    p.wait_for_load_state('networkidle')
    yield p
    context.close()
    browser.close()
    pw.stop()


# ── Helper ────────────────────────────────────────────────

def open_task_overlay(page, task_title="Rich Markdown Task"):
    """Open the task detail overlay and wait for content to load."""
    visible_view = page.locator('.vw.on')
    visible_view.wait_for(state='visible', timeout=3000)

    card = visible_view.locator('.card').filter(has_text=task_title).first
    t_el = card.locator('.t')
    if t_el.count() > 0:
        t_el.click()
    else:
        sp = card.locator('span').filter(has_text=task_title).first
        sp.click()

    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=5000)
    page.locator('#detail-body-area').wait_for(state='visible', timeout=5000)
    return overlay


# ── Test: Heading sizes decrease from h1 to h6 ───────────

def test_heading_sizes_decrease(page):
    """Rendered h1 font-size > h2 > h3 > h4 > h5 > h6, all with proper margins."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    h1 = md.locator('h1', has_text='Heading One')
    h2 = md.locator('h2', has_text='Heading Two')
    h3 = md.locator('h3', has_text='Heading Three')
    h4 = md.locator('h4', has_text='Heading Four')
    h5 = md.locator('h5', has_text='Heading Five')
    h6 = md.locator('h6', has_text='Heading Six')

    assert h1.is_visible()
    assert h2.is_visible()
    assert h3.is_visible()
    assert h4.is_visible()
    assert h5.is_visible()
    assert h6.is_visible()

    h1_size = h1.evaluate('el => parseInt(getComputedStyle(el).fontSize, 10)')
    h2_size = h2.evaluate('el => parseInt(getComputedStyle(el).fontSize, 10)')
    h3_size = h3.evaluate('el => parseInt(getComputedStyle(el).fontSize, 10)')
    h4_size = h4.evaluate('el => parseInt(getComputedStyle(el).fontSize, 10)')
    h5_size = h5.evaluate('el => parseInt(getComputedStyle(el).fontSize, 10)')
    h6_size = h6.evaluate('el => parseInt(getComputedStyle(el).fontSize, 10)')

    assert h1_size > h2_size, f"h1 ({h1_size}px) should be larger than h2 ({h2_size}px)"
    assert h2_size > h3_size, f"h2 ({h2_size}px) should be larger than h3 ({h3_size}px)"
    assert h3_size > h4_size, f"h3 ({h3_size}px) should be larger than h4 ({h4_size}px)"
    assert h4_size > h5_size, f"h4 ({h4_size}px) should be larger than h5 ({h5_size}px)"
    assert h5_size > h6_size, f"h5 ({h5_size}px) should be larger than h6 ({h6_size}px)"

    # Headings should have non-zero margin-top (spacing above)
    h1_mt = h1.evaluate('el => parseInt(getComputedStyle(el).marginTop, 10)')
    assert h1_mt > 0, "h1 should have top margin"

    # h4-h6 should have explicit styling (not just browser defaults)
    # They should use the sans-serif font family from the design, not monospace
    h4_ff = h4.evaluate('el => getComputedStyle(el).fontFamily')
    assert 'mono' not in h4_ff.lower(), f"h4 should use sans-serif font, got: {h4_ff}"


# ── Test: Code blocks use monospace font with background ─

def test_code_blocks_monospace_with_bg(page):
    """Code blocks (```) use monospace font with gray/dark background."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    pre = md.locator('pre').first
    assert pre.is_visible()

    font_family = pre.evaluate('el => getComputedStyle(el).fontFamily')
    assert 'mono' in font_family.lower(), f"Code block font should be monospace, got: {font_family}"

    bg = pre.evaluate('el => getComputedStyle(el).backgroundColor')
    # Should not be transparent (rgba(0,0,0,0))
    assert bg != 'rgba(0, 0, 0, 0)' and bg != 'rgb(0, 0, 0)', \
        f"Code block should have a background color, got: {bg}"


# ── Test: Inline code has subtle highlight background ─────

def test_inline_code_has_background(page):
    """Inline code (`code`) has subtle highlight background, different from pre."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    # Find inline code (inside a <p>, not inside <pre>)
    inline_code = md.locator('p > code').first
    assert inline_code.is_visible(), "Inline code element should be visible"

    bg = inline_code.evaluate('el => getComputedStyle(el).backgroundColor')
    assert bg != 'rgba(0, 0, 0, 0)', \
        f"Inline code should have a background color, got: {bg}"

    # Inline code should also use monospace font
    font_family = inline_code.evaluate('el => getComputedStyle(el).fontFamily')
    assert 'mono' in font_family.lower(), f"Inline code should use monospace font, got: {font_family}"


# ── Test: Unordered lists have proper indentation ─────────

def test_unordered_list_indentation(page):
    """Unordered lists have bullet points with proper indentation."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    ul = md.locator('ul').first
    assert ul.is_visible()

    padding_left = ul.evaluate('el => parseInt(getComputedStyle(el).paddingLeft, 10)')
    assert padding_left > 0, f"ul should have left padding for indentation, got: {padding_left}"

    # List items should exist and be visible
    li = ul.locator('li').first
    assert li.is_visible()


# ── Test: Links render in accent color (#4c6ef5) ──────────

def test_links_accent_color(page):
    """Links render in accent color (#4c6ef5)."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    link = md.locator('a', has_text='Example Link')
    assert link.is_visible()

    color = link.evaluate('el => getComputedStyle(el).color')
    # The accent color #4c6ef5 -> rgb(76, 110, 245)
    assert '76' in color or '4c6ef5' in color, \
        f"Link should be in accent color (#4c6ef5), got: {color}"


# ── Test: Blockquotes have left border and background ─────

def test_blockquotes_have_left_border_and_bg(page):
    """Blockquotes have left border accent and subtle background."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    bq = md.locator('blockquote').first
    assert bq.is_visible()

    border_left = bq.evaluate('el => parseInt(getComputedStyle(el).borderLeftWidth, 10)')
    assert border_left > 0, \
        f"Blockquote should have a left border, got width: {border_left}"

    border_left_color = bq.evaluate('el => getComputedStyle(el).borderLeftColor')
    # Should not be the default transparent/no-color
    assert border_left_color != 'rgba(0, 0, 0, 0)', \
        f"Blockquote left border should have a color, got: {border_left_color}"

    # Blockquote should have a subtle background color (not transparent)
    bq_bg = bq.evaluate('el => getComputedStyle(el).backgroundColor')
    assert bq_bg != 'rgba(0, 0, 0, 0)', \
        f"Blockquote should have a subtle background color, got: {bq_bg}"


# ── Test: Tables have borders and padding ─────────────────

def test_tables_have_borders_and_padding(page):
    """Tables have borders and proper padding on cells."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    table = md.locator('table').first
    assert table.is_visible()

    # Check a td cell for border
    td = table.locator('td').first
    td_border = td.evaluate('el => parseInt(getComputedStyle(el).borderBottomWidth, 10)')
    assert td_border > 0, \
        f"Table cells should have borders, got: {td_border}"

    # Check padding
    td_padding = td.evaluate('el => parseInt(getComputedStyle(el).paddingLeft, 10)')
    assert td_padding > 0, \
        f"Table cells should have padding, got: {td_padding}"


# ── Test: Long markdown content scrolls independently ─────

def test_long_content_scrolls_independently(page):
    """Long markdown content scrolls independently in the center area."""
    overlay = open_task_overlay(page, "Long Task")
    center = overlay.locator('.detail-center')

    # The center area should be scrollable (overflow-y is auto or scroll)
    overflow_y = center.evaluate('el => getComputedStyle(el).overflowY')
    assert overflow_y in ('auto', 'scroll'), \
        f"detail-center should have overflow-y: auto or scroll, got: {overflow_y}"

    # The content should be taller than the container (scrollable)
    scroll_height = center.evaluate('el => el.scrollHeight')
    client_height = center.evaluate('el => el.clientHeight')
    assert scroll_height > client_height, \
        f"Content ({scroll_height}px) should be taller than container ({client_height}px) for scrolling"


# ── Test: Markdown content doesn't overflow container width

def test_content_does_not_overflow_width(page):
    """Markdown content doesn't overflow the container width."""
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')

    # Check that the element has constrained width
    overflow_x = md.evaluate('el => getComputedStyle(el).overflowX')
    max_width = md.evaluate('el => getComputedStyle(el).maxWidth')

    # Content should either have overflow hidden/auto OR a max-width constraint
    has_overflow_control = overflow_x in ('hidden', 'auto', 'clip')
    has_max_width = max_width != 'none'

    assert has_overflow_control or has_max_width, \
        f"Markdown content should have overflow-x control or max-width, got overflow-x={overflow_x}, max-width={max_width}"

    # Also verify pre (code blocks) have overflow-x:auto so code doesn't break layout
    pre = md.locator('pre').first
    if pre.is_visible():
        pre_overflow_x = pre.evaluate('el => getComputedStyle(el).overflowX')
        assert pre_overflow_x in ('auto', 'scroll'), \
            f"Code blocks should have overflow-x: auto or scroll, got: {pre_overflow_x}"


def test_unicode_box_table_renders_as_html_table(page):
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')
    tables = md.locator('table')
    assert tables.count() >= 2
    assert tables.nth(1).locator('th', has_text='Header A').is_visible()
    assert tables.nth(1).locator('td', has_text='Value 2').is_visible()


def test_code_copy_button_visible_on_hover(page):
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')
    pre = md.locator('pre').first
    pre.hover()
    assert pre.locator('.code-copy-btn').is_visible()


def test_local_image_rewritten_to_proxy(page):
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')
    img = md.locator('img').first
    assert img.is_visible()
    src = img.get_attribute('src')
    assert src.startswith('/api/file?path=project%2FHermes%2Flocal-image.png')


def test_local_image_fallback_link_uses_proxy(page):
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')
    img = md.locator('img').first
    page.evaluate(
        """
        () => {
          const img = document.querySelector('#detail-md-content img');
          if (!img) throw new Error('img not found');
          img.dispatchEvent(new Event('error'));
        }
        """
    )
    link = md.locator('a.image-fallback-link').first
    assert link.is_visible()
    href = link.get_attribute('href')
    assert href.startswith('/api/file?path=project%2FHermes%2Flocal-image.png')


def test_mermaid_wrapper_present(page):
    overlay = open_task_overlay(page)
    md = overlay.locator('#detail-md-content')
    wrapper = md.locator('.mermaid-wrapper').first
    wrapper.wait_for(state='visible', timeout=5000)
    assert wrapper.is_visible()
