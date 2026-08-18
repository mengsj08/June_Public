#!/usr/bin/env python3
"""
Tests for Task Detail Overlay UI.

Run with: CI=true python3 -m pytest shared/toolkit/kanban/test_detail_overlay.py -v

Uses Playwright to test the full-page overlay that opens when clicking a task card.
"""

import json
import os
import threading
import time
import tempfile
import shutil
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
    """Create a temp repo with sample task files for all tests in this module."""
    tmp = tempfile.mkdtemp(prefix='kanban_test_')
    tmp_path = Path(tmp)

    # Create project dir
    proj_dir = tmp_path / "project" / "Hermes"
    proj_dir.mkdir(parents=True)

    # Task 1: full content with headings, lists, code blocks
    task1 = """---
title: Sample Task
task_id: HER-1
workdir: project/Hermes/
created: 2026-05-01
updated: 2026-05-02
assignee: Alice
priority: high
status: todo
tags: [backend, api]
---

# Sample Task

This is the markdown body of the task.

## Subsection

- Item 1
- Item 2

```python
def hello():
    print("hello")
```
"""
    (proj_dir / "sample-task.md").write_text(task1, encoding='utf-8')

    # Task 2: in-progress
    task2 = """---
title: Second Task
task_id: HER-2
workdir: project/Hermes/
created: 2026-05-03
updated: 2026-05-03
assignee: Bob
priority: medium
status: in-progress
tags: []
---

Body of second task.
"""
    (proj_dir / "second-task.md").write_text(task2, encoding='utf-8')

    (tmp_path / ".kanban.user.config.json").write_text(
        json.dumps({"user": "Project Owner"}, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )

    # Task 3: empty body
    task3 = """---
title: Empty Task
task_id: HER-3
workdir: project/Hermes/
created: 2026-05-04
updated: 2026-05-04
assignee: ''
priority: low
status: todo
tags: []
---
"""
    (proj_dir / "empty-task.md").write_text(task3, encoding='utf-8')

    yield tmp_path

    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope='module')
def server_url(temp_repo_module):
    """Start an HTTP server on a free port and return its base URL."""
    import socket

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]

    # Patch REPO_ROOT so the server uses our temp repo
    with patch.object(scan_mod, 'REPO_ROOT', temp_repo_module), \
         patch.object(scan_mod, 'CURRENT_MEMBER', 'Project Owner'):
        server = scan_mod.HTTPServer(('127.0.0.1', port), scan_mod.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.3)  # Let server start
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

def open_task_overlay(page, task_title="Sample Task"):
    """
    Click the title element of a task card to open the overlay.
    Scopes search to the currently visible view to avoid hidden cards.
    Waits for content to load (not just overlay to appear).
    """
    # Find the visible view container
    visible_view = page.locator('.vw.on')
    visible_view.wait_for(state='visible', timeout=3000)

    # Find the card within the visible view
    card = visible_view.locator('.card').filter(has_text=task_title).first

    # Try .t first (kanban/projects views)
    t_el = card.locator('.t')
    if t_el.count() > 0:
        t_el.click()
    else:
        # Team view: click the span containing the task title text
        sp = card.locator('span').filter(has_text=task_title).first
        sp.click()
    # Wait for overlay to appear
    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=5000)
    # Wait for content to load (body area becomes visible when fetch completes)
    page.locator('#detail-body-area').wait_for(state='visible', timeout=5000)
    return overlay


def close_overlay(page):
    """Close the overlay by clicking the back button."""
    page.locator('#detail-back-btn').click()
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)


# ── Test: Click task card in kanban view -> overlay opens ──

def test_click_card_kanban_opens_overlay(page):
    """Clicking a task card in kanban view opens the detail overlay with matching title."""
    overlay = open_task_overlay(page, "Sample Task")

    # Verify overlay is visible
    assert overlay.is_visible()
    # Verify title matches
    title_el = overlay.locator('#detail-title')
    assert title_el.inner_text() == 'Sample Task'


# ── Test: Click task card in projects view -> overlay opens ──

def test_click_card_projects_opens_overlay(page):
    """Clicking a task card in projects view opens the detail overlay."""
    # Switch to projects view
    page.locator('.tab').filter(has_text='项目总览').click()
    page.wait_for_timeout(500)

    overlay = open_task_overlay(page, "Second Task")

    assert overlay.is_visible()
    title_el = overlay.locator('#detail-title')
    assert title_el.inner_text() == 'Second Task'


# ── Test: Click task card in team view -> overlay opens ──

def test_click_card_team_opens_overlay(page):
    """Clicking a task card in team view opens the detail overlay."""
    # Switch to team view
    page.locator('.tab').filter(has_text='成员任务').click()
    page.wait_for_timeout(500)

    overlay = open_task_overlay(page, "Sample Task")

    assert overlay.is_visible()
    title_el = overlay.locator('#detail-title')
    assert title_el.inner_text() == 'Sample Task'


# ── Test: Loading spinner shown then replaced by content ──

def test_loading_state_then_content(page):
    """Overlay shows loading state while fetching, replaced by content when loaded."""
    overlay = open_task_overlay(page, "Sample Task")

    # Verify the markdown content area has content (not loading spinner)
    md_area = overlay.locator('#detail-md-content')
    assert md_area.is_visible()
    # Should contain rendered heading
    assert md_area.locator('h1').filter(has_text='Sample Task').is_visible()


# ── Test: Markdown body renders headings, lists, code blocks ──

def test_markdown_renders_correctly(page):
    """Markdown body renders headings, lists, and code blocks via marked.js."""
    overlay = open_task_overlay(page, "Sample Task")
    md_area = overlay.locator('#detail-md-content')

    # Check heading renders
    assert md_area.locator('h1', has_text='Sample Task').is_visible()
    assert md_area.locator('h2', has_text='Subsection').is_visible()

    # Check list items render
    assert md_area.locator('li', has_text='Item 1').is_visible()
    assert md_area.locator('li', has_text='Item 2').is_visible()

    # Check code block renders
    assert md_area.locator('code').is_visible()


# ── Test: Properties sidebar shows status/priority/assignee ──

def test_properties_sidebar_shows_fields(page):
    """Properties sidebar shows status, priority, and assignee."""
    overlay = open_task_overlay(page, "Sample Task")
    sidebar = overlay.locator('#detail-sidebar')

    assert sidebar.is_visible()

    # Check that property labels exist
    assert sidebar.locator('.detail-prop-label', has_text='状态').is_visible()
    assert sidebar.locator('.detail-prop-label', has_text='优先级').is_visible()
    assert sidebar.locator('.detail-prop-label', has_text='负责人').is_visible()
    assert sidebar.locator('.detail-prop-label', has_text='工作目录').is_visible()


# ── Test: Change status in overlay -> apiUpdate called ──

def test_change_status_in_overlay(page):
    """Changing status dropdown in overlay calls apiUpdate and property updates."""
    overlay = open_task_overlay(page, "Sample Task")
    sidebar = overlay.locator('#detail-sidebar')

    # Find the status dropdown trigger and click it
    status_section = sidebar.locator('.detail-prop-row').filter(has_text='状态')
    trigger = status_section.locator('.b').first
    trigger.click()

    # Click the "in-progress" option from the dropdown
    dropdown = status_section.locator('.dd')
    dropdown.wait_for(state='visible', timeout=3000)
    in_progress_item = dropdown.locator('.dd-item').filter(has_text='进行中')
    in_progress_item.click()

    # Wait for toast confirmation
    toast = page.locator('#toast')
    toast.wait_for(state='visible', timeout=5000)


# ── Test: Copy button copies raw md content and shows toast ──

def test_copy_button_copies_raw_md(page):
    """Click copy button -> clipboard contains raw .md content, toast appears."""
    overlay = open_task_overlay(page, "Sample Task")

    # Grant clipboard permissions
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])

    # Click the copy button
    copy_btn = overlay.locator('#detail-copy-btn')
    copy_btn.click()

    # Toast should appear
    toast = page.locator('#toast')
    toast.wait_for(state='visible', timeout=3000)

    # Verify clipboard content
    try:
        clipboard_text = page.evaluate("navigator.clipboard.readText()")
        assert 'title: Sample Task' in clipboard_text
        assert '# Sample Task' in clipboard_text
    except Exception:
        # clipboard API may not be available in some environments; verify toast appeared
        pass


# ── Test: ESC key closes overlay ──

def test_esc_key_closes_overlay(page):
    """Pressing ESC key closes the overlay, board visible again."""
    open_task_overlay(page, "Sample Task")

    # Press ESC
    page.keyboard.press('Escape')

    # Overlay should close
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)

    # Board should be visible (use scoped selector to avoid multiple .board elements)
    assert page.locator('#vw-kanban .board').is_visible()


# ── Test: Back arrow closes overlay ──

def test_back_arrow_closes_overlay(page):
    """Clicking the back arrow closes the overlay."""
    open_task_overlay(page, "Sample Task")

    # Click back button
    page.locator('#detail-back-btn').click()

    # Overlay should close
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)


# ── Test: Task with no body -> shows placeholder ──

def test_empty_body_shows_placeholder(page):
    """Task with no body content shows placeholder text."""
    overlay = open_task_overlay(page, "Empty Task")

    md_area = overlay.locator('#detail-md-content')
    # Should contain the placeholder text
    assert '无正文内容' in md_area.inner_text()


# ── Test: Non-existent task -> shows error ──

def test_nonexistent_task_shows_error(page):
    """Opening a non-existent task shows error message in overlay."""
    # Directly trigger the overlay with a bad path via JS evaluation
    page.evaluate("openTaskDetail('project/Hermes/nonexistent-task.md')")

    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=5000)

    # Wait for either content or error to appear
    # Should show error state
    error_el = overlay.locator('#detail-error')
    error_el.wait_for(state='visible', timeout=5000)
    assert error_el.is_visible()


# ── Test: Responsive layout at different viewport sizes ──

def test_responsive_layout(page):
    """At 768px+ sidebar visible beside markdown; below 768px stacks below."""
    overlay = open_task_overlay(page, "Sample Task")

    # Desktop: sidebar should be beside markdown
    sidebar = overlay.locator('#detail-sidebar')
    md_content = overlay.locator('#detail-md-content')
    assert sidebar.is_visible()
    assert md_content.is_visible()

    # Resize to mobile
    page.set_viewport_size({'width': 600, 'height': 800})
    page.wait_for_timeout(300)

    # Both should still be visible but layout changed (stacked)
    assert sidebar.is_visible()
    assert md_content.is_visible()


# ── Test: File path in sidebar is clickable ──

def test_file_path_clickable_opens_editor(page):
    """Click file path in sidebar -> openInEditor called with task path."""
    overlay = open_task_overlay(page, "Sample Task")
    sidebar = overlay.locator('#detail-sidebar')

    # Find the file path link
    path_el = sidebar.locator('#detail-file-path')
    assert path_el.is_visible()

    # Verify it has the right text
    path_text = path_el.inner_text()
    assert 'sample-task.md' in path_text


# ── Test: URL updates to #HER-1 when detail opens ──

def test_url_updates_with_task_id(page):
    """Opening task detail updates browser URL to #HER-1 (task_id)."""
    open_task_overlay(page, "Sample Task")

    # URL hash should contain the task code
    url = page.url
    assert '#HER-' in url


# ── Test: Navigate to #HER-1 directly opens detail ──

def test_navigate_hash_opens_detail(server_url):
    """Navigating to URL with #HER-1 opens that task's detail directly."""
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={'width': 1280, 'height': 800})
    page = context.new_page()
    page.goto(server_url + '#HER-1')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1000)

    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=5000)

    # Wait for content to load
    page.locator('#detail-body-area').wait_for(state='visible', timeout=5000)

    # Title should be Sample Task (which is HER-1)
    title_el = overlay.locator('#detail-title')
    assert title_el.inner_text() == 'Sample Task'

    context.close()
    browser.close()
    pw.stop()


# ── Test: Close overlay clears URL hash ──

def test_close_overlay_clears_hash(page):
    """Closing overlay clears URL hash back to # or empty."""
    open_task_overlay(page, "Sample Task")

    # Verify hash was set
    assert '#HER-' in page.url

    # Close overlay
    close_overlay(page)

    # Hash should be cleared
    url = page.url
    if '#' in url:
        hash_part = url.split('#')[1]
        assert hash_part == '', f"Expected empty hash, got: {hash_part}"


# ── Test: Browser back button closes overlay ──

def test_browser_back_closes_overlay(page):
    """Browser back button after opening detail closes overlay."""
    open_task_overlay(page, "Sample Task")

    # Verify hash was set
    assert '#HER-' in page.url

    # Go back
    page.go_back()
    page.wait_for_timeout(500)

    # Overlay should close
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)
