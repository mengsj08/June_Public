#!/usr/bin/env python3
"""Load the generated Manifest V3 extension and open its real side panel page."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "release" / "chrome-extension"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="comma-chrome-smoke-") as profile:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                profile,
                headless=False,
                args=[
                    f"--disable-extensions-except={EXTENSION}",
                    f"--load-extension={EXTENSION}",
                ],
            )
            try:
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
                manifest = worker.evaluate("chrome.runtime.getManifest()")
                extension_id = worker.url.split("/")[2]
                page = context.new_page()
                page.goto(f"chrome-extension://{extension_id}/sidepanel.html", wait_until="networkidle")
                page.wait_for_function(
                    "document.querySelector('comma-editor')?.shadowRoot?.querySelectorAll('.ce-block').length > 0"
                )
                title = page.locator("comma-editor").evaluate(
                    "el => el.shadowRoot.querySelector('[data-el=title]').textContent"
                )
                result = {
                    "ok": True,
                    "extension_id": extension_id,
                    "manifest_version": manifest["manifest_version"],
                    "version": manifest["version"],
                    "title": title,
                }
                artifact = ROOT / "test-artifacts" / "chrome-smoke.json"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result))
            finally:
                context.close()


if __name__ == "__main__":
    main()
