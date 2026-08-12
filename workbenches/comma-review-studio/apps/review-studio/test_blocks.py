#!/usr/bin/env python3
"""Browser acceptance for block editing through the public custom element."""
import json
import os

from playwright.sync_api import sync_playwright

PORT = os.environ.get("COMMA_REVIEW_PORT", "8891")
BASE = f"http://127.0.0.1:{PORT}"
URL = f"{BASE}/?doc=paper.md"
ROOT = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(ROOT, "data", "paper.md")
COMMENTS = DOC + ".comments.json"


def read_doc():
    with open(DOC, encoding="utf-8") as handle:
        return handle.read()


def reset_comments():
    if os.path.exists(COMMENTS):
        os.remove(COMMENTS)


def main():
    reset_comments()
    original = read_doc()
    results = {}
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: errors.append("PAGEERROR: " + str(error)))
            page.goto(URL, wait_until="load")
            page.locator("comma-editor").locator(".ce-block").first.wait_for(timeout=15000)
            page.wait_for_function("document.querySelector('comma-editor').documentState.rev.length > 0")

            pick = page.evaluate("""() => {
              const editor = document.querySelector('comma-editor');
              const candidates = editor._blocks.filter(block => block.type === 'paragraph');
              const block = candidates[Math.floor(candidates.length / 2)];
              return { index: block.index, start: block.start, end: block.end, raw: block.raw, type: block.type };
            }""")
            block = page.locator("comma-editor").locator(f'.ce-block[data-block-index="{pick["index"]}"]')
            block.locator('[data-action="edit-block"]').evaluate("button => button.click()")
            textarea = page.locator("comma-editor").locator(".ce-block-editor")
            textarea.wait_for()
            results["explicit_edit"] = {"blockIndex": pick["index"], "entered": textarea.is_visible()}
            textarea.fill(textarea.input_value() + " EDITED-BY-PUBLIC-KIT")
            textarea.press("Control+Enter")
            page.wait_for_function("""() => document.querySelector('comma-editor').documentState.body.includes(' EDITED-BY-PUBLIC-KIT')""")
            page.wait_for_timeout(250)

            trailer_len = len(pick["raw"]) - len(pick["raw"].rstrip("\n"))
            trailer = pick["raw"][-trailer_len:] if trailer_len else ""
            content = pick["raw"][:-trailer_len] if trailer_len else pick["raw"]
            replacement = content + " EDITED-BY-PUBLIC-KIT" + trailer
            expected = original[:pick["start"]] + replacement + original[pick["end"]:]
            after = read_doc()
            results["byte_fidelity"] = {
                "onlySelectedBlockChanged": after == expected,
                "delta": len(after) - len(original),
                "rev": page.evaluate("document.querySelector('comma-editor').documentState.rev"),
            }

            stale = page.evaluate("""async () => {
              const editor = document.querySelector('comma-editor');
              const block = editor._blocks.find(item => item.raw.includes('We present a provenance-aware'));
              if (!block) throw new Error('anchor fixture block not found');
              const quote = 'We present a provenance-aware orchestration layer that coordinates';
              await editor.adapter.createComment({
                kind: 'anchored', actor: 'TestBot', content: 'stale anchor contract', quoteText: quote,
                sourceLocator: { bodyRev: editor.documentState.rev, blockIndex: block.index, quoteText: quote },
              });
              await editor.refreshComments();
              const before = editor._resolveComment(editor._comments[0]).state;
              editor._enterBlockEdit(block.index);
              editor._activeBlock.textarea.value = 'This paragraph is completely rewritten; the prior quote no longer exists.';
              await editor._commitBlock(false);
              await editor.refreshComments();
              const after = editor._resolveComment(editor._comments[0]).state;
              return { before, after };
            }""")
            results["edited_anchor"] = stale
            results["console_errors"] = errors[:10]
            browser.close()
    finally:
        with open(DOC, "w", encoding="utf-8") as handle:
            handle.write(original)
        reset_comments()

    assert results["explicit_edit"]["entered"]
    assert results["byte_fidelity"]["onlySelectedBlockChanged"]
    assert results["edited_anchor"] == {"before": "unique", "after": "missing"}
    assert not results["console_errors"], results["console_errors"]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
