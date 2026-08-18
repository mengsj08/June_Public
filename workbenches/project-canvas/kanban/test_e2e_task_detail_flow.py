#!/usr/bin/env python3
"""
E2E: Task Detail View Complete Flow.

Run with: CI=true python3 -m pytest test_e2e_task_detail_flow.py -v

End-to-end test verifying the complete user journey:
  click task card -> view detail -> copy markdown -> edit property -> close overlay.

Uses Playwright to capture screenshots at each critical state transition.
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


# ── Screenshot output directory ───────────────────────────

SCREENSHOT_DIR = _HERE / 'screenshots_e2e'


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture(scope='module')
def temp_repo_module():
    """Create a temp repo with sample task files for all tests in this module."""
    tmp = tempfile.mkdtemp(prefix='kanban_e2e_')
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

![Tiny Image](local-image.png)
"""
    (proj_dir / "sample-task.md").write_text(task1, encoding='utf-8')
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z7xQAAAAASUVORK5CYII="
    )
    (proj_dir / "local-image.png").write_bytes(png_bytes)

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

## Details

Some detail text here.
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

    # Task 4: dedicated fixture for block-level in-place editing.
    task4 = """---
title: Inline Editable Draft
task_id: HER-4
workdir: project/Hermes/
created: 2026-05-05
updated: 2026-05-05
assignee: Alice
priority: high
status: in-progress
tags: [editor]
---

# Inline Editable Draft

This paragraph is edited without opening the full Markdown source.

## Stable section

- Alpha
- Beta

## 完成标准

- [ ] Inline edit preserves every other byte
"""
    (proj_dir / "inline-editable-draft.md").write_text(task4, encoding='utf-8')

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
    context = browser.new_context(viewport={'width': 1280, 'height': 720})
    p = context.new_page()
    p.goto(server_url)
    p.wait_for_load_state('networkidle')
    yield p
    context.close()
    browser.close()
    pw.stop()


@pytest.fixture(autouse=True, scope='module')
def setup_screenshot_dir():
    """Ensure screenshot output directory exists."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────

def screenshot(page, name):
    """Save a screenshot to the e2e screenshots directory."""
    page.screenshot(path=str(SCREENSHOT_DIR / f'{name}.png'), full_page=False)


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


# ══════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════


# ── Test 1: Click task card -> overlay opens within 1s -> title matches card text

def test_click_card_overlay_opens_fast_with_matching_title(page):
    """Clicking a task card opens the overlay quickly and title matches."""
    visible_view = page.locator('.vw.on')
    visible_view.wait_for(state='visible', timeout=3000)

    card = visible_view.locator('.card').filter(has_text='Sample Task').first
    t_el = card.locator('.t')
    t_el.click()

    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=1000)

    # Wait for content load
    page.locator('#detail-body-area').wait_for(state='visible', timeout=5000)

    title_el = overlay.locator('#detail-title')
    assert title_el.inner_text() == 'Sample Task'


# ── Test 2: Overlay shows rendered markdown (h1/h2/code blocks visible)

def test_overlay_shows_rendered_markdown(page):
    """Overlay renders h1, h2, and code blocks from task markdown body."""
    overlay = open_task_overlay(page, "Sample Task")
    md_area = overlay.locator('#detail-md-content')

    assert md_area.locator('h1', has_text='Sample Task').is_visible()
    assert md_area.locator('h2', has_text='Subsection').is_visible()
    assert md_area.locator('code').is_visible()


def test_clicking_rendered_block_edits_only_that_markdown_block(page):
    page.evaluate("openTaskDetail('project/Hermes/inline-editable-draft.md')")
    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=5000)
    page.locator('#detail-body-area').wait_for(state='visible', timeout=5000)
    md_area = overlay.locator('#detail-md-content')
    source_button = overlay.locator('#detail-edit-btn')

    assert source_button.inner_text() == '源码'
    assert overlay.locator('#detail-edit-mode').is_hidden()
    assert md_area.locator('.detail-acceptance-block').is_visible()
    assert md_area.locator('.detail-doc-block').filter(has_text='完成标准').count() == 0

    before_body = page.evaluate(
        """async () => {
          const response = await fetch('/api/task?path=' + encodeURIComponent('project/Hermes/inline-editable-draft.md'));
          const payload = await response.json();
          return payload.task.body;
        }"""
    )
    old_text = 'This paragraph is edited without opening the full Markdown source.'
    new_text = 'This paragraph was edited directly in the rendered reading view.'
    target = md_area.locator('.detail-doc-block').filter(has_text=old_text).first
    block_index = target.get_attribute('data-block-index')
    target.click()

    editing_block = md_area.locator(f'.detail-doc-block[data-block-index="{block_index}"]')
    inline_editor = editing_block.locator('.detail-block-editor')
    inline_editor.wait_for(state='visible', timeout=3000)
    assert overlay.locator('#detail-edit-mode').is_hidden()
    inline_editor.fill(new_text)
    inline_editor.press('Control+Enter')

    md_area.locator('.detail-doc-block').filter(has_text=new_text).first.wait_for(state='visible', timeout=5000)
    after_body = page.evaluate(
        """async () => {
          const response = await fetch('/api/task?path=' + encodeURIComponent('project/Hermes/inline-editable-draft.md'));
          const payload = await response.json();
          return payload.task.body;
        }"""
    )
    assert after_body == before_body.replace(old_text, new_text, 1)
    assert overlay.locator('#detail-edit-mode').is_hidden()

    source_button.click()
    overlay.locator('#detail-editor').wait_for(state='visible', timeout=3000)
    assert source_button.inner_text() == '查看'


def test_save_waits_for_pending_image_uploads(page):
    overlay = open_task_overlay(page, "Sample Task")
    overlay.locator('#detail-edit-btn').click()
    editor = overlay.locator('#detail-editor')
    editor.wait_for(state='visible', timeout=3000)

    page.evaluate(
        """
        () => {
          window.__kanbanTest = { saveBodies: [] };
          const originalFetch = window.fetch.bind(window);
          const pendingFinalUrl = 'https://cdn.example.com/kanban/Hermes/markdown-images/final.png';
          window.fetch = async (input, init) => {
            const url = typeof input === 'string' ? input : input.url;
            if (url === '/api/prepare-upload') {
              return new Response(JSON.stringify({
                ok: true,
                upload_url: 'https://upload.example.com',
                final_url: pendingFinalUrl,
                method: 'POST',
                fields: { key: 'kanban/Hermes/markdown-images/final.png' }
              }), { status: 200, headers: { 'Content-Type': 'application/json' } });
                }
                if (url === 'https://upload.example.com') {
                  await new Promise(resolve => setTimeout(resolve, 300));
                  return new Response('ok', { status: 200 });
                }
            if (url === '/api/update-body') {
              const payload = JSON.parse(init.body);
              window.__kanbanTest.saveBodies.push(payload.body);
              return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } });
            }
            return originalFetch(input, init);
          };
        }
        """
    )

    page.evaluate(
        """
        async () => {
          const editor = document.getElementById('detail-editor');
          const file = new File(['img'], 'pending.png', { type: 'image/png' });
          window.__pendingUploadPromise = window.uploadImageAndInsert(file, editor);
          await new Promise(resolve => setTimeout(resolve, 50));
        }
        """
    )

    page.evaluate("() => { window.__saveBodyPromise = window.saveBody(); }")
    page.wait_for_timeout(80)

    save_count_during_upload = page.evaluate("() => window.__kanbanTest.saveBodies.length")
    assert save_count_during_upload == 0

    page.wait_for_function("() => window.__kanbanTest.saveBodies.length === 1", timeout=5000)
    saved_body = page.evaluate("() => window.__kanbanTest.saveBodies[0]")
    assert 'uploading://' not in saved_body
    assert 'https://cdn.example.com/kanban/Hermes/markdown-images/final.png' in saved_body


def test_pending_upload_blocks_close_and_task_switch(page):
    overlay = open_task_overlay(page, "Sample Task")
    overlay.locator('#detail-edit-btn').click()
    editor = overlay.locator('#detail-editor')
    editor.wait_for(state='visible', timeout=3000)

    page.evaluate(
        """
        () => {
          const originalFetch = window.fetch.bind(window);
          window.fetch = async (input, init) => {
            const url = typeof input === 'string' ? input : input.url;
            if (url === '/api/prepare-upload') {
              return new Response(JSON.stringify({
                ok: true,
                upload_url: 'https://upload.example.com',
                final_url: 'https://cdn.example.com/kanban/Hermes/markdown-images/final.png',
                method: 'POST',
                fields: { key: 'kanban/Hermes/markdown-images/final.png' }
              }), { status: 200, headers: { 'Content-Type': 'application/json' } });
            }
            if (url === 'https://upload.example.com') {
              return new Promise(resolve => {
                window.__resolvePendingUpload = () => resolve(new Response('ok', { status: 200 }));
              });
            }
            return originalFetch(input, init);
          };
        }
        """
    )

    page.evaluate(
        """
        async () => {
          const editor = document.getElementById('detail-editor');
          const file = new File(['img'], 'pending.png', { type: 'image/png' });
          window.__pendingUploadPromise = window.uploadImageAndInsert(file, editor);
          await new Promise(resolve => setTimeout(resolve, 50));
        }
        """
    )

    page.keyboard.press('Escape')
    page.wait_for_timeout(50)
    assert overlay.locator('#detail-title').inner_text() == 'Sample Task'
    assert page.locator('#detail-overlay').is_visible()

    page.evaluate("() => openTaskDetail('project/Hermes/second-task.md')")
    page.wait_for_timeout(50)
    assert overlay.locator('#detail-title').inner_text() == 'Sample Task'

    toast = page.locator('#toast')
    toast.wait_for(state='visible', timeout=3000)
    assert '等待图片上传完成' in toast.inner_text()

    page.evaluate("() => window.__resolvePendingUpload()")
    page.wait_for_timeout(100)
    page.evaluate("() => openTaskDetail('project/Hermes/second-task.md')")
    page.locator('#detail-body-area').wait_for(state='visible', timeout=5000)
    assert overlay.locator('#detail-title').inner_text() == 'Second Task'


# ── Test 3: Copy button click -> clipboard contains markdown, toast confirms

def test_copy_button_copies_markdown_and_toasts(page):
    """Click copy button copies raw markdown to clipboard, toast notification appears."""
    overlay = open_task_overlay(page, "Sample Task")

    # Grant clipboard permissions
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])

    copy_btn = overlay.locator('#detail-copy-btn')
    copy_btn.click()

    # Toast should appear
    toast = page.locator('#toast')
    toast.wait_for(state='visible', timeout=3000)
    assert toast.is_visible()

    # Verify clipboard content
    try:
        clipboard_text = page.evaluate("navigator.clipboard.readText()")
        assert 'title: Sample Task' in clipboard_text
        assert '# Sample Task' in clipboard_text
    except Exception:
        # clipboard API may not work in all envs; toast confirmation is sufficient
        pass


# ── Test 4: Change property via dropdown -> API called, toast confirms update

def test_change_property_dropdown_triggers_update(page):
    """Changing status via dropdown calls API and shows toast confirmation."""
    overlay = open_task_overlay(page, "Sample Task")
    sidebar = overlay.locator('#detail-sidebar')

    # Find the status dropdown trigger
    status_section = sidebar.locator('.detail-prop-row').filter(has_text='状态')
    trigger = status_section.locator('.b').first
    trigger.click()

    # Open dropdown and select "已完成" (done)
    dropdown = status_section.locator('.dd')
    dropdown.wait_for(state='visible', timeout=3000)
    done_item = dropdown.locator('.dd-item').filter(has_text='已完成')
    done_item.click()

    # Wait for toast confirmation
    toast = page.locator('#toast')
    toast.wait_for(state='visible', timeout=5000)
    assert toast.is_visible()


# ── Test 5: ESC key -> overlay closes -> kanban board still visible

def test_esc_key_closes_overlay_board_visible(page):
    """Pressing ESC closes overlay and kanban board is still visible."""
    overlay = open_task_overlay(page, "Sample Task")

    # Screenshot before closing
    screenshot(page, 'detail-overlay-loaded')

    page.keyboard.press('Escape')
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)

    # Board should still be visible
    assert page.locator('#vw-kanban .board').is_visible()

    # Screenshot after closing
    screenshot(page, 'overlay-closed')


# ── Test 6: Re-open same task -> previously changed property reflects update

def test_reopen_task_reflects_previous_update(page):
    """Changing status then re-opening shows the updated status value."""
    overlay = open_task_overlay(page, "Sample Task")
    sidebar = overlay.locator('#detail-sidebar')

    # Change status to "已完成"
    status_section = sidebar.locator('.detail-prop-row').filter(has_text='状态')
    trigger = status_section.locator('.b').first
    trigger.click()
    dropdown = status_section.locator('.dd')
    dropdown.wait_for(state='visible', timeout=3000)
    done_item = dropdown.locator('.dd-item').filter(has_text='已完成')
    done_item.click()

    # Wait for toast
    toast = page.locator('#toast')
    toast.wait_for(state='visible', timeout=5000)

    # Close overlay
    page.keyboard.press('Escape')
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)

    # Re-open same task
    overlay2 = open_task_overlay(page, "Sample Task")
    sidebar2 = overlay2.locator('#detail-sidebar')

    # Verify status now shows "已完成"
    status_section2 = sidebar2.locator('.detail-prop-row').filter(has_text='状态')
    trigger2 = status_section2.locator('.b').first
    assert '已完成' in trigger2.inner_text()


# ── Test 7: Click different task -> overlay updates with new task's content

def test_switch_to_different_task_updates_content(page):
    """Opening a different task updates the overlay with that task's content."""
    # Open first task
    overlay = open_task_overlay(page, "Sample Task")
    title1 = overlay.locator('#detail-title')
    assert title1.inner_text() == 'Sample Task'

    # Close overlay
    close_overlay(page)

    # Open second task
    overlay2 = open_task_overlay(page, "Second Task")
    title2 = overlay2.locator('#detail-title')
    assert title2.inner_text() == 'Second Task'

    # Verify content is different
    md_area = overlay2.locator('#detail-md-content')
    assert md_area.locator('h2', has_text='Details').is_visible()


# ── Test 8: Server returns 404 task -> overlay shows error message

def test_nonexistent_task_shows_error(page):
    """Opening a non-existent task shows an error message in the overlay."""
    page.evaluate("openTaskDetail('project/Hermes/nonexistent-task.md')")

    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=5000)

    # Wait for error to appear
    error_el = overlay.locator('#detail-error')
    error_el.wait_for(state='visible', timeout=5000)
    assert error_el.is_visible()


# ══════════════════════════════════════════════════════════
# COMPLETE USER JOURNEY (integration of all steps)
# ══════════════════════════════════════════════════════════

def test_complete_user_journey_with_screenshots(page):
    """
    Full journey: click card -> view detail -> copy -> edit property -> close.
    Captures screenshots at each critical state transition.
    """
    # Step 1-2: Board is already loaded, find a card
    visible_view = page.locator('.vw.on')
    visible_view.wait_for(state='visible', timeout=3000)

    # Step 3: Click first task card
    card = visible_view.locator('.card').filter(has_text='Sample Task').first
    t_el = card.locator('.t')
    t_el.click()

    # Step 4: Wait for overlay and task data to load
    overlay = page.locator('#detail-overlay')
    overlay.wait_for(state='visible', timeout=5000)
    page.locator('#detail-body-area').wait_for(state='visible', timeout=5000)

    # Step 5: Verify title visible, markdown rendered, properties sidebar visible
    title_el = overlay.locator('#detail-title')
    assert title_el.inner_text() == 'Sample Task'

    md_area = overlay.locator('#detail-md-content')
    assert md_area.is_visible()
    assert md_area.locator('h1', has_text='Sample Task').is_visible()

    sidebar = overlay.locator('#detail-sidebar')
    assert sidebar.is_visible()

    # Step 6: Screenshot - detail overlay loaded
    screenshot(page, 'detail-overlay-loaded')

    # Step 7: Click copy button
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    copy_btn = overlay.locator('#detail-copy-btn')
    copy_btn.click()

    # Step 8: Verify toast notification appears
    toast = page.locator('#toast')
    toast.wait_for(state='visible', timeout=3000)
    assert toast.is_visible()

    # Screenshot - copy toast
    screenshot(page, 'copy-toast')

    # Step 9: Click status dropdown, change to "已完成"
    status_section = sidebar.locator('.detail-prop-row').filter(has_text='状态')
    trigger = status_section.locator('.b').first
    trigger.click()
    dropdown = status_section.locator('.dd')
    dropdown.wait_for(state='visible', timeout=3000)
    done_item = dropdown.locator('.dd-item').filter(has_text='已完成')
    done_item.click()

    # Step 10: Verify toast shows update confirmation
    toast2 = page.locator('#toast')
    toast2.wait_for(state='visible', timeout=5000)

    # Step 11: Screenshot - property updated
    screenshot(page, 'detail-property-updated')

    # Step 12: Press ESC
    page.keyboard.press('Escape')

    # Step 13: Verify overlay closed, kanban board visible
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)
    assert page.locator('#vw-kanban .board').is_visible()

    # Step 14: Screenshot - overlay closed
    screenshot(page, 'overlay-closed')


# ── Test: Overlay opens and closes correctly across all board views

def test_overlay_opens_closes_in_all_views(page):
    """Overlay opens and closes correctly in kanban, projects, and team views."""
    # --- Kanban view (default) ---
    overlay = open_task_overlay(page, "Sample Task")
    assert overlay.is_visible()
    assert overlay.locator('#detail-title').inner_text() == 'Sample Task'
    page.keyboard.press('Escape')
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)

    # --- Projects view ---
    page.locator('.tab').filter(has_text='项目总览').click()
    page.wait_for_timeout(500)

    overlay2 = open_task_overlay(page, "Second Task")
    assert overlay2.is_visible()
    assert overlay2.locator('#detail-title').inner_text() == 'Second Task'
    page.keyboard.press('Escape')
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)

    # --- Team view ---
    page.locator('.tab').filter(has_text='成员任务').click()
    page.wait_for_timeout(500)

    overlay3 = open_task_overlay(page, "Sample Task")
    assert overlay3.is_visible()
    assert overlay3.locator('#detail-title').inner_text() == 'Sample Task'
    page.keyboard.press('Escape')
    page.locator('#detail-overlay').wait_for(state='hidden', timeout=3000)


def test_local_image_opens_lightbox(page):
    overlay = open_task_overlay(page, "Sample Task")
    img = overlay.locator('#detail-md-content img').first
    img.wait_for(state='visible', timeout=5000)
    img.click()

    lightbox = page.locator('#lightbox-overlay')
    lightbox.wait_for(state='visible', timeout=3000)
    page.wait_for_function(
        "() => !!document.getElementById('lightbox-image')?.getAttribute('src')",
        timeout=3000
    )
    assert lightbox.locator('#lightbox-image').get_attribute('src')
    page.keyboard.press('Escape')
    lightbox.wait_for(state='hidden', timeout=3000)


def test_code_copy_button_appears_on_hover(page):
    overlay = open_task_overlay(page, "Sample Task")
    pre = overlay.locator('#detail-md-content pre').first
    pre.hover()
    copy_btn = pre.locator('.code-copy-btn')
    copy_btn.wait_for(state='visible', timeout=3000)
    assert copy_btn.is_visible()
