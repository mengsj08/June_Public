#!/usr/bin/env python3
"""Headless browser acceptance check for the standalone host."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PORT = 4178
URL = f"http://127.0.0.1:{PORT}/standalone/"


def wait_ready() -> None:
    for _ in range(80):
        try:
            with urlopen(URL, timeout=0.4) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Vite server did not become ready")


def main() -> None:
    server = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_ready()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.add_init_script("localStorage.clear()")
            page.goto(URL, wait_until="networkidle")
            page.wait_for_function("document.querySelector('comma-editor')?.shadowRoot?.querySelectorAll('.ce-block').length > 3")
            title = page.locator("comma-editor").evaluate("el => el.shadowRoot.querySelector('[data-el=title]').textContent")
            blocks = page.locator("comma-editor").evaluate("el => el.shadowRoot.querySelectorAll('.ce-block').length")

            page.locator("comma-editor").evaluate(
                """el => {
                  el.selectionActions = [
                    { id: 'quick-explain', label: 'Quick explain' },
                    { id: 'discuss', label: 'Discuss' }
                  ];
                  window.__selectionAction = null;
                  el.addEventListener('comma-selection-action', event => {
                    window.__selectionAction = {
                      actionId: event.detail.actionId,
                      quoteText: event.detail.quoteText,
                      rev: event.detail.document.rev
                    };
                  });
                }"""
            )

            # A real pointer drag must be captured. Script-created ranges do
            # not exercise the browser's native selection event timing.
            native_target = page.locator("comma-editor .ce-block p").first
            native_box = native_target.bounding_box()
            assert native_box is not None
            native_y = native_box["y"] + min(12, native_box["height"] / 2)
            page.mouse.move(native_box["x"] + 6, native_y)
            page.mouse.down()
            page.mouse.move(native_box["x"] + min(280, native_box["width"] - 8), native_y, steps=12)
            page.mouse.up()
            page.wait_for_function("!document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=selection-bar]').hidden")
            native_pointer_state = page.locator("comma-editor").evaluate(
                """el => ({
                  quoteText: el._selection?.quoteText || '',
                  editorActive: Boolean(el.shadowRoot.querySelector('.ce-block-editor')),
                  barHidden: el.shadowRoot.querySelector('[data-el=selection-bar]').hidden
                })"""
            )
            assert native_pointer_state["quoteText"]
            assert native_pointer_state["editorActive"] is False
            assert native_pointer_state["barHidden"] is False

            native_paragraphs = page.locator("comma-editor .ce-block p")
            assert native_paragraphs.count() >= 2
            native_second_box = native_paragraphs.nth(1).bounding_box()
            assert native_second_box is not None
            page.mouse.click(native_box["x"] + 60, native_y)
            page.mouse.move(native_box["x"] + 60, native_y)
            page.mouse.down()
            page.mouse.move(
                native_second_box["x"] + min(190, native_second_box["width"] - 8),
                native_second_box["y"] + min(12, native_second_box["height"] / 2),
                steps=18,
            )
            page.mouse.up()
            page.wait_for_function(
                """previous => {
                  const selection = document.querySelector('comma-editor')._selection;
                  return selection?.quoteText && selection.quoteText !== previous
                    && selection.sourceLocator?.endBlockIndex > selection.sourceLocator?.blockIndex;
                }""",
                arg=native_pointer_state["quoteText"],
            )
            native_multiblock_state = page.locator("comma-editor").evaluate(
                """el => ({
                  quoteText: el._selection?.quoteText || '',
                  blockIndex: el._selection?.sourceLocator?.blockIndex,
                  endBlockIndex: el._selection?.sourceLocator?.endBlockIndex,
                  barHidden: el.shadowRoot.querySelector('[data-el=selection-bar]').hidden
                })"""
            )
            assert native_multiblock_state["quoteText"]
            assert native_multiblock_state["endBlockIndex"] > native_multiblock_state["blockIndex"]
            assert native_multiblock_state["barHidden"] is False
            native_multiblock_resolution = page.locator("comma-editor").evaluate(
                """el => el._resolveComment({
                  quoteText: el._selection.quoteText,
                  sourceLocator: el._selection.sourceLocator
                })"""
            )
            assert native_multiblock_resolution["state"] == "rendered-range"
            assert native_multiblock_resolution["blockIndex"] == native_multiblock_state["blockIndex"]

            # Select a whole rendered paragraph that crosses ** markers in the
            # raw source. The component must use rendered-block fallback.
            page.locator("comma-editor").evaluate(
                """el => {
                  const paragraph = el.shadowRoot.querySelector('.ce-block p');
                  const range = document.createRange();
                  range.selectNodeContents(paragraph);
                  const selection = getSelection();
                  selection.removeAllRanges();
                  selection.addRange(range);
                  paragraph.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                }"""
            )
            page.wait_for_function("!document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=selection-bar]').hidden")
            selection_priority_state = page.locator("comma-editor").evaluate(
                """el => {
                  el.shadowRoot.querySelector('.ce-block p').click();
                  return {
                    barHidden: el.shadowRoot.querySelector('[data-el=selection-bar]').hidden,
                    editorActive: Boolean(el.shadowRoot.querySelector('.ce-block-editor'))
                  };
                }"""
            )
            assert selection_priority_state == {"barHidden": False, "editorActive": False}
            selection_actions = page.locator("comma-editor").evaluate(
                "el => Array.from(el.shadowRoot.querySelectorAll('[data-selection-action]')).map(button => button.textContent)"
            )
            page.locator("comma-editor").evaluate(
                "el => el.shadowRoot.querySelector('[data-selection-action=quick-explain]').click()"
            )
            page.wait_for_function("window.__selectionAction?.actionId === 'quick-explain'")
            selection_event = page.evaluate("window.__selectionAction")
            assert selection_actions == ["Quick explain", "Discuss"]
            assert selection_event["actionId"] == "quick-explain"
            assert selection_event["quoteText"]
            assert selection_event["rev"]

            # Re-select after the host action consumes the quote, then create a
            # native comment through the editor-owned action.
            page.locator("comma-editor").evaluate(
                """el => {
                  const paragraph = el.shadowRoot.querySelector('.ce-block p');
                  const range = document.createRange();
                  range.selectNodeContents(paragraph);
                  const selection = getSelection();
                  selection.removeAllRanges();
                  selection.addRange(range);
                  paragraph.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                }"""
            )
            page.wait_for_function("!document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=selection-bar]').hidden")
            page.locator("comma-editor").evaluate("el => el.shadowRoot.querySelector('[data-action=selection-comment]').click()")
            page.locator("comma-editor").evaluate(
                "el => { el.shadowRoot.querySelector('[data-el=comment-input]').value = 'Keep this as the core invariant.'; }"
            )
            page.locator("comma-editor").evaluate("el => el.shadowRoot.querySelector('[data-action=save-comment]').click()")
            page.wait_for_function("document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=comment-count]').textContent === '1'")
            action_projection_state = page.locator("comma-editor").evaluate(
                """el => {
                  const state = el.actionState;
                  const primaryButtons = Array.from(el.shadowRoot.querySelectorAll('[data-el=toolbar-primary] [data-toolbar-action]'));
                  const overflowButtons = Array.from(el.shadowRoot.querySelectorAll('[data-el=toolbar-overflow-menu] [data-toolbar-action]'));
                  return {
                    schemaVersion: state.schemaVersion,
                    stateCommentCount: state.comments.count,
                    domCommentCount: Number(el.shadowRoot.querySelector('[data-el=comment-count]').textContent),
                    primaryIds: state.toolbar.primary.map(action => action.id),
                    primaryDomIds: primaryButtons.map(button => button.dataset.toolbarAction),
                    overflowIds: state.toolbar.overflow.map(action => action.id),
                    overflowDomIds: overflowButtons.map(button => button.dataset.toolbarAction),
                    disabledMatch: [...primaryButtons, ...overflowButtons].every(button => {
                      const action = state.toolbar.actions.find(item => item.id === button.dataset.toolbarAction);
                      return action && button.disabled === (!action.enabled || action.loading);
                    })
                  };
                }"""
            )
            assert action_projection_state["schemaVersion"] == "comma-action-state/v1"
            assert action_projection_state["stateCommentCount"] == action_projection_state["domCommentCount"] == 1
            assert action_projection_state["primaryIds"] == action_projection_state["primaryDomIds"]
            assert action_projection_state["overflowIds"] == action_projection_state["overflowDomIds"]
            assert action_projection_state["disabledMatch"] is True
            anchor_state = page.locator("comma-editor").evaluate(
                "el => el.shadowRoot.querySelector('.ce-comment-state').textContent"
            )

            # Feed a host-produced structured review into the public SDK API.
            # One exact quote is eligible; one missing quote must stay blocked.
            batch_preview = page.locator("comma-editor").evaluate(
                """el => el.previewCommentBatch({
                  base_rev: el.documentState.rev,
                  comments: [
                    {
                      quote_text: 'A mature component is defined by its boundary, not by the number of buttons it contains.',
                      content: 'Keep this as the acceptance criterion.',
                      priority: 'P1',
                      section: 'The small contract'
                    },
                    {
                      quote_text: 'This sentence does not exist.',
                      content: 'This proposal must never be written.'
                    }
                  ]
                }, { actor: 'browser-smoke-ai', source: 'test-review' })"""
            )
            assert batch_preview["counts"]["ready"] == 1
            assert batch_preview["counts"]["missing"] == 1
            page.wait_for_timeout(260)
            review_screenshot = ROOT / "test-artifacts" / "review-queue.png"
            review_screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(review_screenshot), full_page=False)
            page.locator("comma-editor").evaluate(
                "el => el.shadowRoot.querySelector('[data-action=apply-review]').click()"
            )
            page.wait_for_function(
                "document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=comment-count]').textContent === '2'"
            )
            review_queue_closed = page.locator("comma-editor").evaluate(
                "el => el.shadowRoot.querySelector('[data-el=review-queue]').hidden"
            )

            # Reading and editing are separate modes: clicking manuscript text
            # must never consume a quote selection or silently open a textarea.
            passive_click_state = page.locator("comma-editor").evaluate(
                """el => {
                  el.shadowRoot.querySelector('[data-block-type=paragraph] p').click();
                  return {
                    editorActive: Boolean(el.shadowRoot.querySelector('.ce-block-editor')),
                    editActions: el.shadowRoot.querySelectorAll('[data-action=edit-block]').length
                  };
                }"""
            )
            assert passive_click_state["editorActive"] is False
            assert passive_click_state["editActions"] > 0

            # Exercise the explicit in-place edit affordance before whole-source editing.
            page.locator("comma-editor").evaluate(
                "el => el.shadowRoot.querySelector('[data-block-type=paragraph] [data-action=edit-block]').click()"
            )
            page.wait_for_function("document.querySelector('comma-editor').shadowRoot.querySelector('.ce-block-editor')")
            page.locator("comma-editor").evaluate(
                """el => {
                  const ta = el.shadowRoot.querySelector('.ce-block-editor');
                  ta.value += ' Block edit.';
                  el.shadowRoot.querySelector('[data-action=commit-block-edit]').click();
                }"""
            )
            page.wait_for_function("document.querySelector('comma-editor').documentState.body.includes('Block edit.')")

            page.locator("comma-editor").evaluate("el => el.shadowRoot.querySelector('[data-toolbar-action=source]').click()")
            page.locator("comma-editor").evaluate(
                "el => { const ta = el.shadowRoot.querySelector('[data-el=source-editor]'); ta.value += '\\nBrowser smoke edit.\\n'; }"
            )
            page.locator("comma-editor").evaluate("el => el.shadowRoot.querySelector('[data-action=save-source]').click()")
            page.wait_for_function("document.querySelector('comma-editor').documentState.body.includes('Browser smoke edit.')")
            screenshot = ROOT / "test-artifacts" / "standalone.png"
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot), full_page=True)

            page.locator("comma-editor").evaluate(
                """async el => {
                  const tiny = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';
                  await el.replaceDocument({
                    title: 'image-integrity.md',
                    body: `# Image integrity\\n\\n![Tiny \\`tick'.](${tiny})\\n\\n![Second tiny](${tiny})\\n`,
                    actor: 'browser-smoke'
                  });
                }"""
            )
            page.wait_for_function(
                """() => {
                  const root = document.querySelector('comma-editor').shadowRoot;
                  const imgs = Array.from(root.querySelectorAll('.ce-preview img'));
                  return imgs.length === 2 && imgs.every(img => img.complete && img.naturalWidth > 0);
                }"""
            )
            image_integrity_state = page.locator("comma-editor").evaluate(
                """el => {
                  const refs = el.documentState.body.match(/!\\[[^\\n]*?\\]\\([^\\n)]+\\)/g) || [];
                  const imgs = Array.from(el.shadowRoot.querySelectorAll('.ce-preview img'));
                  const ready = imgs.filter(img => img.dataset.assetState === 'ready' && img.naturalWidth > 0);
                  return { refs: refs.length, images: imgs.length, ready: ready.length };
                }"""
            )
            assert image_integrity_state == {"refs": 2, "images": 2, "ready": 2}

            page.locator("comma-editor").evaluate(
                """async el => {
                  await el.replaceDocument({
                    title: 'broken-images.md',
                    body: '# Broken images\\n\\n![PDF panel](figures/panel.pdf)\\n\\n![empty source]()\\n',
                    actor: 'browser-smoke'
                  });
                }"""
            )
            page.wait_for_function(
                "document.querySelector('comma-editor').shadowRoot.querySelectorAll('.ce-image-fallback').length === 2"
            )
            broken_image_state = page.locator("comma-editor").evaluate(
                """el => ({
                  images: el.shadowRoot.querySelectorAll('.ce-preview img').length,
                  fallbacks: Array.from(el.shadowRoot.querySelectorAll('.ce-image-fallback')).map(node => node.textContent)
                })"""
            )
            assert broken_image_state["images"] == 0
            assert any("Unsupported image format: panel.pdf" in text for text in broken_image_state["fallbacks"])
            assert any("missing image source" in text for text in broken_image_state["fallbacks"])

            result = {
                "ok": True,
                "title": title,
                "blocks": blocks,
                "selection_actions": selection_actions,
                "selection_event": selection_event,
                "native_pointer_state": native_pointer_state,
                "native_multiblock_state": native_multiblock_state,
                "native_multiblock_resolution": native_multiblock_resolution,
                "selection_priority_state": selection_priority_state,
                "action_projection_state": action_projection_state,
                "anchor_state": anchor_state,
                "batch_ready": batch_preview["counts"]["ready"],
                "batch_missing": batch_preview["counts"]["missing"],
                "review_queue_closed": review_queue_closed,
                "passive_click_state": passive_click_state,
                "image_integrity_state": image_integrity_state,
                "broken_image_state": broken_image_state,
                "review_screenshot": str(review_screenshot),
                "screenshot": str(screenshot),
            }
            (ROOT / "test-artifacts" / "browser-smoke.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(result, ensure_ascii=False))
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=4)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
