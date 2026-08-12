#!/usr/bin/env python3
"""Browser acceptance for the canonical <comma-editor> Review Studio surface.

Run with the kanban Playwright venv. The server must already be running on
COMMA_REVIEW_PORT (default 8891). The fixture is restored on exit.
"""
import json
import os
import base64
import time
import urllib.request

from playwright.sync_api import sync_playwright

PORT = os.environ.get("COMMA_REVIEW_PORT", "8891")
BASE = f"http://127.0.0.1:{PORT}"
URL = f"{BASE}/?doc=paper.md"
ROOT = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(ROOT, "data", "paper.md")
COMMENTS = DOC + ".comments.json"
COMMENT_EVENTS = DOC + ".comment-events.jsonl"
ASSET = os.path.join(ROOT, "data", "scientific-control.png")
REVIEW_ROOT = os.path.join(ROOT, "data", "review-sessions")
SLICE_C_SESSION_ID = "review-c0ffee000001"
SLICE_C_RUN_ID = "run-c0ffee000001"
SLICE_C_SESSION = os.path.join(REVIEW_ROOT, SLICE_C_SESSION_ID + ".json")
DOC_MENU_SWITCH_DOC = os.path.join(ROOT, "data", "headless-switch.md")
DOC_MENU_NESTED_DOC = os.path.join(ROOT, "data", "headless-nested", "registered.md")
DOC_MENU_VERSION_INDEX = os.path.join(ROOT, "data", ".comma-review", "versions", "headless-doc-menu", "index.json")
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z9xkAAAAASUVORK5CYII="
)


def api(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def read_doc():
    with open(DOC, encoding="utf-8") as handle:
        return handle.read()


def reset_comments():
    for path in (COMMENTS, COMMENT_EVENTS):
        if os.path.exists(path):
            os.remove(path)


def write_slice_c_preview(document, comments_rev, human_comment_id, withdraw_comment_id, candidate_comment_id):
    def proposal(finding_id, quote, issue, action, *, placement_scope="quote"):
        return {
            "id": finding_id, "section": "Scientific media fixture",
            "quote_text": quote, "issue": issue, "action": action,
            "priority": "P1", "decision": "accepted",
            "evidence_requirement": "", "rationale": "Synthetic browser contract.",
            "context_before": "", "context_after": "", "version": 1,
            "applied_comment_id": "", "applied_signature": "",
            "anchor_state": "ready", "anchor_matches": 1,
            "source_locator": {"task_path": "paper.md", "body_rev": document["rev"]},
            "origin": {"actor_type": "ai", "actor": "AI Reviewer"},
            "placement": {"scope": placement_scope, "state": "quote_exact"},
            "placement_detail": {
                "downgrade_reason": "browser_fixture",
                "candidates": [{"section_title": "Scientific media fixture", "block_index": 1}],
            },
            "evidence": {"match_count": 1},
            "evidence_occurrences": [
                {"id": f"occ-{finding_id.lower()}-1", "progress_state": "open",
                 "section_title": "Scientific media fixture",
                 "source_locator": {"body_rev": document["rev"], "text_index": 0}},
            ],
        }

    created = proposal(
        "F-CREATE", "Scientific control image",
        "The synthetic image note needs a source boundary.", "Add a bounded review note.")
    updated = proposal(
        "F-HUMAN", "Scientific media fixture",
        "The human-edited note has a proposed revision.", "Apply only after explicit confirmation.")
    unverified = proposal(
        "F-UNVERIFIED", "Fabricated browser smoke quote",
        "This quote is intentionally unverified.", "Keep it out of normal review.",
        placement_scope="evidence_unverified")
    unverified["placement"]["state"] = "evidence_unverified"
    unverified["anchor_state"] = "missing"
    unverified["anchor_matches"] = 0
    unverified["evidence"]["match_count"] = 0
    operations = [
        {"id": "op-create", "action": "create", "finding_id": "F-CREATE",
         "supersedes_finding_id": "", "target_comment_id": "", "reason": "new finding",
         "proposed_comment": created, "human_edited_target": False},
        {"id": "op-human", "action": "update", "finding_id": "F-HUMAN",
         "supersedes_finding_id": "F-HUMAN", "target_comment_id": human_comment_id,
         "reason": "human-edited target", "proposed_comment": updated,
         "human_edited_target": True},
        {"id": "op-withdraw", "action": "withdraw", "finding_id": "F-WITHDRAW",
         "supersedes_finding_id": "F-WITHDRAW", "target_comment_id": withdraw_comment_id,
         "reason": "finding no longer applies", "proposed_comment": None,
         "human_edited_target": False},
        {"id": "op-keep", "action": "keep", "finding_id": "F-HUMAN",
         "supersedes_finding_id": "", "target_comment_id": human_comment_id,
         "reason": "lineage stays visible", "proposed_comment": None,
         "human_edited_target": True,
         "resurfacing_notice": {
             "previous_declined": True, "same_blocks_unchanged": True,
             "block_hash_state": "unchanged", "mute_available": True,
             "message": "上轮未采纳；相关原文自上轮未变化；本轮再次提出",
         }},
        {"id": "op-resolved", "action": "candidate_resolved", "finding_id": "F-RESOLVED",
         "supersedes_finding_id": "F-RESOLVED", "target_comment_id": candidate_comment_id,
         "reason": "explicitly rechecked", "proposed_comment": None,
         "human_edited_target": False,
         "resolution_review": {
             "before_text": "Candidate finding still open.",
             "after_text": "Candidate finding appears addressed.",
             "new_evidence": "The current text now narrows the claim.",
         }},
        {"id": "op-blocked", "action": "blocked", "finding_id": "F-BLOCKED",
         "supersedes_finding_id": "", "target_comment_id": "",
         "reason": "anchor is ambiguous", "proposed_comment": None,
         "human_edited_target": False},
        {"id": "op-unverified", "action": "keep", "finding_id": "F-UNVERIFIED",
         "supersedes_finding_id": "", "target_comment_id": "",
         "reason": "evidence_unverified", "proposed_comment": unverified,
         "human_edited_target": False},
    ]
    run = {
        "schema_version": "comma-review-run/v1", "id": SLICE_C_RUN_ID,
        "session_id": SLICE_C_SESSION_ID, "parent_session_id": "review-baseline0001",
        "mode": "incremental",
        "input": {"document_rev": document["rev"], "comments_rev": comments_rev,
                  "changed_block_ids": ["synthetic-block"],
                  "affected_comment_ids": [human_comment_id, withdraw_comment_id]},
        "operations": operations, "model_receipt": {"tool": "mock", "returncode": 0},
        "writeback_receipt_id": "", "status": "preview",
        "created_at": "2026-07-20T10:00:00", "updated_at": "2026-07-20T10:00:00",
    }
    session = {
        "id": SLICE_C_SESSION_ID, "doc_path": "paper.md",
        "base_rev": document["rev"], "document_rev": document["rev"],
        "tool": "codex", "status": "preview", "summary": "Synthetic operation preview.",
        "findings": [created, updated], "messages": [], "writeback_receipts": [],
        "run": run, "created_at": "2026-07-20T10:00:00",
        "updated_at": "2026-07-20T10:00:00",
    }
    os.makedirs(REVIEW_ROOT, exist_ok=True)
    with open(SLICE_C_SESSION, "w", encoding="utf-8") as handle:
        json.dump(session, handle, ensure_ascii=False, indent=2)


def editor_snapshot(page):
    return page.evaluate("""() => {
      const editor = document.querySelector('comma-editor');
      const root = editor.shadowRoot;
      const resolutions = editor._comments
        .filter(comment => comment.kind === 'anchored')
        .map(comment => editor._resolveComment(comment));
      return {
        title: editor.documentState.title,
        rev: editor.documentState.rev,
        blocks: root.querySelectorAll('.ce-block').length,
        katex: root.querySelectorAll('.katex').length,
        katexErrors: root.querySelectorAll('.katex-error').length,
        tables: root.querySelectorAll('table').length,
        tableScrolls: root.querySelectorAll('.ce-table-scroll').length,
        figures: root.querySelectorAll('figure').length,
        images: root.querySelectorAll('.ce-preview img').length,
        imageStates: Array.from(root.querySelectorAll('.ce-preview img')).map(image => image.dataset.assetState),
        code: root.querySelectorAll('pre code').length,
        comments: root.querySelectorAll('.ce-comment').length,
        resolved: resolutions.filter(item => Number.isInteger(item.blockIndex) && item.blockIndex >= 0).length,
        stale: resolutions.filter(item => item.state === 'missing').length,
        ambiguous: resolutions.filter(item => item.state === 'ambiguous').length,
        resolutionStates: resolutions.map(item => item.state),
        theme: editor.getAttribute('theme'),
        shellBackground: getComputedStyle(root.querySelector('.ce-shell')).backgroundColor,
        paperBackground: getComputedStyle(root.querySelector('.ce-document')).backgroundColor,
        textureDisplay: getComputedStyle(root.querySelector('.ce-shell'), '::before').display,
        ceHeaderCount: root.querySelectorAll('.ce-header').length,
        embeddedControls: root.querySelectorAll('[data-el=embedded-controls]').length,
      };
    }""")


def main():
    reset_comments()
    original = read_doc()
    original_slice_c_session = None
    if os.path.exists(SLICE_C_SESSION):
        with open(SLICE_C_SESSION, "rb") as handle:
            original_slice_c_session = handle.read()
    scientific_fixture = original + """

## Scientific media fixture

![Scientific control image](scientific-control.png)

| Marker | Cohort | Condition | Assay | Timepoint | Replicate | Mean | SD | CI | P value | Effect | Batch | Source | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EPCAM | Validation | Treated | Imaging | Day 14 | R03 | 18.2 | 1.4 | 16.8–19.6 | 0.004 | 1.82 | B-2026-07 | PMID:00000000 | controlled fixture |
"""
    with open(DOC, "w", encoding="utf-8") as handle:
        handle.write(scientific_fixture)
    with open(ASSET, "wb") as handle:
        handle.write(PNG_1X1)
    os.makedirs(os.path.dirname(DOC_MENU_NESTED_DOC), exist_ok=True)
    os.makedirs(os.path.dirname(DOC_MENU_VERSION_INDEX), exist_ok=True)
    with open(DOC_MENU_SWITCH_DOC, "w", encoding="utf-8") as handle:
        handle.write("# Headless switch target\n\nThis document exists only for menu switching.\n")
    with open(DOC_MENU_NESTED_DOC, "w", encoding="utf-8") as handle:
        handle.write("# Registered nested target\n\nThis subdirectory manuscript is registered.\n")
    with open(DOC_MENU_VERSION_INDEX, "w", encoding="utf-8") as handle:
        json.dump({
            "schema_version": "comma-review-versions/v1",
            "doc_path": "headless-nested/registered.md",
            "versions": [{"id": "version-headlessmenu", "rev": "fixture", "kind": "baseline"}],
        }, handle)
    results = {}
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: errors.append("PAGEERROR: " + str(error)))
            started = time.time()
            page.goto(URL, wait_until="load")
            page.locator("comma-editor").locator(".ce-block").first.wait_for(timeout=15000)
            page.locator("comma-editor").locator(".katex").first.wait_for(timeout=15000)
            page.wait_for_function("document.querySelector('comma-editor').shadowRoot.querySelector('.ce-preview img')?.dataset.assetState === 'ready'")
            page.wait_for_function("document.querySelector('comma-editor').documentState.rev.length > 0")
            first = editor_snapshot(page)
            first["fullLoadMs"] = round((time.time() - started) * 1000)
            first["rerenderMs"] = round(page.evaluate("""() => {
              const editor = document.querySelector('comma-editor');
              const started = performance.now();
              editor._renderDocument();
              return performance.now() - started;
            }"""))
            results["public_component_render"] = first
            outline_snapshot = """() => {
              const editor = document.querySelector('comma-editor');
              const root = editor.shadowRoot;
              const grid = root.querySelector('.ce-grid');
              const outline = root.querySelector('[data-el=outline]');
              const toggle = root.querySelector('[data-el=outline-toggle]');
              const state = editor.actionState.outline;
              return {
                mode: state.mode,
                open: state.open,
                preference: state.preference,
                shellMode: root.querySelector('[data-el=shell]').dataset.outlineMode,
                outlineDisplay: getComputedStyle(outline).display,
                toggleDisplay: getComputedStyle(toggle).display,
                toggleExpanded: toggle.getAttribute('aria-expanded'),
                toggleText: toggle.textContent.trim(),
                activeSectionTitle: state.activeSectionTitle,
                gridColumns: getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length,
                storage: localStorage.getItem('comma-editor:outline-preference') || '',
              };
            }"""
            page.set_viewport_size({"width": 1700, "height": 1000})
            page.evaluate("""() => {
              localStorage.removeItem('comma-editor:outline-preference');
              const editor = document.querySelector('comma-editor');
              editor._outlinePreference = '';
              editor._syncOutlineViewport({ force: true });
            }""")
            page.wait_for_function("document.querySelector('comma-editor').actionState.outline.mode === 'expanded'")
            results["outline_expanded_default"] = page.evaluate(outline_snapshot)
            page.evaluate("""() => document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=outline-toggle]').click()""")
            page.wait_for_function("localStorage.getItem('comma-editor:outline-preference') === 'closed'")
            page.reload(wait_until="load")
            page.locator("comma-editor").locator(".ce-block").first.wait_for(timeout=15000)
            page.wait_for_function("document.querySelector('comma-editor').documentState.rev.length > 0")
            page.set_viewport_size({"width": 1700, "height": 1000})
            page.wait_for_function("document.querySelector('comma-editor').actionState.outline.preference === 'closed'")
            results["outline_persisted_closed"] = page.evaluate(outline_snapshot)
            page.set_viewport_size({"width": 1400, "height": 900})
            page.evaluate("""() => {
              localStorage.removeItem('comma-editor:outline-preference');
              const editor = document.querySelector('comma-editor');
              editor._outlinePreference = '';
              editor._syncOutlineViewport({ force: true });
            }""")
            page.wait_for_function("document.querySelector('comma-editor').actionState.outline.mode === 'collapsed'")
            results["outline_collapsed_default"] = page.evaluate(outline_snapshot)
            page.set_viewport_size({"width": 820, "height": 900})
            page.evaluate("""() => {
              localStorage.removeItem('comma-editor:outline-preference');
              const editor = document.querySelector('comma-editor');
              editor._outlinePreference = '';
              editor._syncOutlineViewport({ force: true });
            }""")
            page.wait_for_function("document.querySelector('comma-editor').actionState.outline.mode === 'drawer'")
            results["outline_drawer_default"] = page.evaluate(outline_snapshot)
            page.evaluate("""() => document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=outline-toggle]').click()""")
            page.wait_for_function("document.querySelector('comma-editor').actionState.outline.open === true")
            results["outline_drawer_open"] = page.evaluate(outline_snapshot)
            results["outline_drawer_jump"] = page.evaluate("""async () => {
              const editor = document.querySelector('comma-editor');
              const root = editor.shadowRoot;
              root.querySelector('[data-action=outline-jump]').click();
              await new Promise(resolve => setTimeout(resolve, 80));
              return {
                open: editor.actionState.outline.open,
                focusEl: root.activeElement?.dataset.el || '',
              };
            }""")
            page.set_viewport_size({"width": 1400, "height": 900})
            page.evaluate("""() => {
              localStorage.removeItem('comma-editor:outline-preference');
              const editor = document.querySelector('comma-editor');
              editor._outlinePreference = '';
              editor._syncOutlineViewport({ force: true });
            }""")
            results["host_actions"] = page.evaluate("""() => {
              const root = document.querySelector('comma-editor').shadowRoot;
              const state = document.querySelector('comma-editor').actionState;
              return {
                innerHeaderCount: root.querySelectorAll('.ce-header').length,
                statePrimary: state.toolbar.primary.map(action => action.label + (Number.isFinite(action.count) ? ` ${action.count}` : '')),
                primary: Array.from(document.querySelectorAll('#doc-primary-actions [data-host-toolbar-action]')).map(button => button.textContent.trim()),
                primaryIds: Array.from(document.querySelectorAll('#doc-primary-actions [data-host-toolbar-action]')).map(button => button.dataset.hostToolbarAction),
                overflow: Array.from(document.querySelectorAll('#doc-more-editor-actions [data-host-toolbar-action]')).map(button => button.textContent.trim()),
                overflowIds: Array.from(document.querySelectorAll('#doc-more-editor-actions [data-host-toolbar-action]')).map(button => button.dataset.hostToolbarAction),
                moreHost: Array.from(document.querySelectorAll('#doc-more-actions > button')).map(button => button.textContent.trim().replace(/\\s+/g, ' ')),
                aiToolsHidden: document.querySelector('#ai-tools-popover').hidden,
                aiToolsButtons: document.querySelector('#ai-tools-popover').querySelectorAll('button').length,
                panelTitle: root.querySelector('[data-el=comment-panel-title]').textContent,
              };
	            }""")
            menu_page = browser.new_page(viewport={"width": 1400, "height": 900})
            menu_page.goto(URL, wait_until="load")
            menu_page.locator("comma-editor").locator(".ce-block").first.wait_for(timeout=15000)
            menu_page.locator("#doc-file-menu summary").click()
            menu_page.wait_for_function("document.querySelectorAll('#doc-file-list [data-doc-path]').length >= 3")
            results["document_menu"] = menu_page.evaluate("""() => {
              const rows = Array.from(document.querySelectorAll('#doc-file-list [data-doc-path]'));
              const current = rows.find(row => row.getAttribute('aria-current') === 'page');
              return {
                open: document.querySelector('#doc-file-menu').open,
                paths: rows.map(row => row.dataset.docPath),
                currentPath: current?.dataset.docPath || '',
                currentCheck: current?.querySelector('.doc-file-check')?.textContent || '',
              };
            }""")
            menu_page.locator('#doc-file-list [data-doc-path="headless-switch.md"]').click()
            menu_page.wait_for_url("**/?doc=headless-switch.md")
            menu_page.locator("comma-editor").locator(".ce-block").first.wait_for(timeout=15000)
            results["document_menu_switch"] = menu_page.evaluate("""() => ({
              search: location.search,
              docName: document.querySelector('#doc-name').textContent,
              editorTitle: document.querySelector('comma-editor').documentState.title,
            })""")
            menu_page.close()
            page.locator('#doc-primary-actions [data-host-toolbar-action="article-overview"]').click()
            page.wait_for_function("document.querySelector('#overview-drawer').classList.contains('open')")
            results["overview_shell"] = {
                "title": page.locator("#overview-drawer h2").text_content(),
                "claims": page.locator("#overview-drawer .capability-boundary-card li").count(),
                "revision": page.locator("#overview-rev").text_content(),
            }
            page.locator("#overview-close").click()

            page.locator('#doc-primary-actions [data-host-toolbar-action="import-manuscript"]').click()
            page.wait_for_function("!document.querySelector('#import-modal').hidden")
            results["import_primary"] = {
                "modalTitle": page.locator("#import-title").text_content(),
            }
            page.locator("#import-close").click()

            page.locator('#doc-primary-actions [data-host-toolbar-action="evidence"]').click()
            page.wait_for_function("document.querySelector('#evidence-drawer').getAttribute('aria-hidden') === 'false'")
            results["evidence_primary"] = {
                "drawerTitle": page.locator("#evidence-drawer h2").text_content(),
            }
            page.locator("#evidence-close").click()

            page.locator('#doc-primary-actions [data-host-toolbar-action="ai-review"]').click()
            page.wait_for_function("!document.querySelector('#review-preflight-modal').hidden && !document.querySelector('#review-preflight-primary').disabled")
            results["review_preflight"] = {
                "title": page.locator("#review-preflight-title").text_content(),
                "route": page.locator("#review-preflight-route-code").text_content(),
                "primary": page.locator("#review-preflight-primary").text_content(),
                "claims": page.locator("#review-preflight-modal .preflight-report-grid article").count(),
            }
            page.locator("#review-preflight-close").click()

            results["document_only_boundary"] = page.evaluate("""async () => {
              const fixture = document.createElement('comma-editor');
              fixture.id = 'document-only-fixture';
              fixture.toolbarActions = [
                { id: 'document-info', label: 'Info', slot: 'primary', appliesTo: 'document.load' },
                { id: 'comments', label: 'Forbidden count', slot: 'primary', appliesTo: 'comments.list', count: 'comments' },
              ];
              fixture.commentActions = [
                { id: 'edit', label: 'Forbidden edit without appliesTo' },
              ];
              fixture.adapter = {
                capabilities: {
                  savePolicy: 'explicit', document: { load: true, save: false, replace: false },
                  comments: { list: false, create: false, batch: false, update: false, delete: false },
                  events: { list: false }, assets: { resolve: false },
                },
                async load() { return { title: 'document-only.md', body: '# Fixture\\n\\nNo comment service.', rev: 'opaque-revision-token' }; },
              };
              const ready = new Promise(resolve => fixture.addEventListener('comma-ready', resolve, { once: true }));
              document.body.appendChild(fixture);
              await ready;
              const root = fixture.shadowRoot;
              const result = {
                toolbarActions: Array.from(root.querySelectorAll('[data-toolbar-action]')).map(button => button.dataset.toolbarAction),
                commentCountNodes: root.querySelectorAll('[data-comment-count]').length,
                commentActionNodes: root.querySelectorAll('[data-comment-action]').length,
                normalizedCommentAppliesTo: fixture.commentActions[0]?.appliesTo,
                missingCommentActionAvailable: fixture._commentActionAvailable(
                  fixture.commentActions[0],
                  { lifecycleState: 'active', findingState: '', kind: 'overall' },
                ),
                sidebarHidden: root.querySelector('[data-el=sidebar]').hidden,
              };
              fixture.remove();
              return result;
            }""")

            document = api("/api/doc?path=paper.md")
            human_created = api("/api/comments", "POST", {
                "path": "paper.md", "kind": "anchored", "actor": "AI Reviewer",
                "content": "Synthetic AI note before the human edit.",
                "quote_text": "Scientific media fixture", "source": "ai-review",
                "source_key": "review-browser:F-HUMAN", "finding_id": "F-HUMAN",
                "finding_state": "accepted",
            })
            human_comment = human_created["comment"]
            human_edited = api(f"/api/comments/{human_comment['id']}", "PATCH", {
                "path": "paper.md", "base_comment_version": human_comment["comment_version"],
                "content": "Synthetic note explicitly edited by a human.", "actor": "June",
            })["comment"]
            withdraw_comment = api("/api/comments", "POST", {
                "path": "paper.md", "kind": "anchored", "actor": "AI Reviewer",
                "content": "Synthetic finding that will be withdrawn.",
                "quote_text": "Validation", "source": "ai-review",
                "source_key": "review-browser:F-WITHDRAW", "finding_id": "F-WITHDRAW",
                "finding_state": "accepted",
            })["comment"]
            candidate_comment = api("/api/comments", "POST", {
                "path": "paper.md", "kind": "anchored", "actor": "AI Reviewer",
                "content": "Candidate finding still open.",
                "quote_text": "Scientific control image", "source": "ai-review",
                "source_key": "review-browser:F-RESOLVED", "finding_id": "F-RESOLVED",
                "finding_state": "accepted",
            })["comment"]
            preview_store = api("/api/comments?path=paper.md")
            write_slice_c_preview(
                document, preview_store["comments_rev"],
                human_edited["id"], withdraw_comment["id"], candidate_comment["id"],
            )
            page.evaluate("""async id => {
              window.__COMMA_REVIEW__.openReviewDrawer();
              await window.__COMMA_REVIEW__.loadReviewSession(id);
            }""", SLICE_C_SESSION_ID)
            page.wait_for_function(
                "document.querySelectorAll('[data-operation-group]').length === 4")
            page.locator("#review-accept-all").click()
            bulk_selected = page.locator("[data-operation-accept]:checked").evaluate_all(
                "nodes => nodes.map(node => node.dataset.operationAccept).sort()")
            human_checkbox = page.locator('.operation-card[data-human-edited="true"] [data-operation-accept]')
            results["operation_preview"] = {
                "groups": page.locator("[data-operation-group]").evaluate_all(
                    "nodes => nodes.map(node => node.dataset.operationGroup)"),
                "counts": page.locator("[data-operation-group] > header b").all_text_contents(),
                "bulkSelected": bulk_selected,
                "humanHighlighted": page.locator('.operation-card[data-human-edited="true"]').count(),
                "humanBulkChecked": human_checkbox.is_checked(),
                "stateTitles": page.locator("[data-operation-group] > header h4").all_text_contents(),
                "sourceBadges": page.locator(".operation-card .review-badge.source").all_text_contents(),
                "placementBadges": page.locator(".operation-card .review-badge.placement").all_text_contents(),
                "locationDetails": page.locator(".operation-card .location-details").count(),
                "locationDetailsOpen": page.locator(".operation-card .location-details").evaluate_all(
                    "nodes => nodes.map(node => node.open)"),
                "candidateAcceptLabel": page.locator('[data-operation-action="candidate_resolved"] .operation-accept span').text_content(),
                "unverifiedDisabled": page.locator('[data-operation-id="op-unverified"] [data-operation-accept]').is_disabled(),
                "muteEntry": page.locator('[data-lineage-mute]').text_content(),
                "resurfacingNotice": page.locator(".resurfacing-notice").text_content(),
                "blockedDisabled": page.locator('[data-operation-action="blocked"] [data-operation-accept]').is_disabled(),
                "blockedReason": page.locator('[data-operation-action="blocked"] .operation-reason').text_content(),
            }
            page.set_viewport_size({"width": 700, "height": 900})
            results["operation_preview_narrow"] = page.evaluate("""() => {
              const drawer = document.querySelector('#review-drawer');
              const preview = document.querySelector('.operation-preview');
              const cards = Array.from(document.querySelectorAll('.operation-card'));
              return {
                drawerWidth: drawer.getBoundingClientRect().width,
                drawerScrollWidth: drawer.scrollWidth,
                previewWidth: preview.getBoundingClientRect().width,
                previewScrollWidth: preview.scrollWidth,
                cardOverflow: cards.some(card => card.scrollWidth > card.getBoundingClientRect().width + 1),
              };
            }""")
            page.set_viewport_size({"width": 1400, "height": 900})
            human_checkbox.check()
            page.locator("#review-writeback").click()
            page.wait_for_function(
                "window.__COMMA_REVIEW__.reviewState.activeRun?.status === 'completed'")
            completed_store = api("/api/comments?path=paper.md")
            completed_run = api(f"/api/review-runs/{SLICE_C_RUN_ID}")
            receipt = completed_run["session"]["writeback_receipts"][0]
            results["operation_writeback"] = {
                "status": completed_run["run"]["status"],
                "accepted": completed_run["run"]["accepted_operation_ids"],
                "created": len(receipt["created"]),
                "updated": len(receipt["updated"]),
                "withdrawn": len(receipt["withdrawn"]),
                "kept": len(receipt["kept"]),
                "candidateResolved": len(receipt["candidate_resolved"]),
                "blocked": len(receipt["blocked"]),
                "humanStillMarked": next(
                    item for item in completed_store["comments"]
                    if item["id"] == human_edited["id"])["human_edited"],
                "withdrawState": next(
                    item for item in completed_store["comments"]
                    if item["id"] == withdraw_comment["id"])["finding_state"],
                "candidateWorkflow": next(
                    item for item in completed_store["comments"]
                    if item["id"] == candidate_comment["id"])["workflow"]["state"],
            }
            page.locator("#review-close").click()
            reset_comments()
            page.evaluate("document.querySelector('comma-editor').refreshComments()")
            page.wait_for_function(
                "document.querySelector('comma-editor').shadowRoot.querySelectorAll('.ce-comment').length === 0")

            page.locator("comma-editor").locator(".ce-preview img").click()
            page.wait_for_function("!document.querySelector('comma-editor').shadowRoot.querySelector('[data-el=lightbox]').hidden")
            results["image_lightbox_opened"] = True
            page.locator("comma-editor").locator("[data-el=lightbox-close]").click()

            document = api("/api/doc?path=paper.md")
            markers = [
                "We present a provenance-aware orchestration layer that coordinates",
                "As shown in Equation for section 3, the inline bound",
                "As shown in Equation for section 9, the inline bound",
                "As shown in Equation for section 14, the inline bound",
                "[13] Author 13, et al.",
            ]
            for index, quote in enumerate(markers):
                api("/api/comments", "POST", {
                    "path": "paper.md",
                    "kind": "anchored",
                    "actor": "TestBot",
                    "content": f"public adapter anchor {index + 1}",
                    "quoteText": quote,
                    "sourceLocator": {"bodyRev": document["rev"], "quoteText": quote},
                })
            page.evaluate("document.querySelector('comma-editor').refreshComments()")
            page.wait_for_function("document.querySelector('comma-editor').shadowRoot.querySelectorAll('.ce-comment').length === 5")
            results["anchors_baseline"] = editor_snapshot(page)

            api("/api/comments", "POST", {
                "path": "paper.md",
                "kind": "overall",
                "actor": "LayoutBot",
                "content": "continuous-scientific-review-token-" * 40,
            })
            page.evaluate("document.querySelector('comma-editor').refreshComments()")
            page.wait_for_function("document.querySelector('comma-editor').shadowRoot.querySelectorAll('.ce-comment').length === 6")
            page.set_viewport_size({"width": 2036, "height": 1143})
            results["scientific_layout"] = page.evaluate("""() => {
              const root = document.querySelector('comma-editor').shadowRoot;
              const sidebar = root.querySelector('.ce-sidebar');
              const comments = root.querySelector('.ce-comments');
              const card = root.querySelector('.ce-comment');
              return {
                sidebarWidth: sidebar.getBoundingClientRect().width,
                sidebarScrollWidth: sidebar.scrollWidth,
                commentsWidth: comments.getBoundingClientRect().width,
                commentsScrollWidth: comments.scrollWidth,
                cardWidth: card.getBoundingClientRect().width,
                cardScrollWidth: card.scrollWidth,
              };
            }""")
            page.set_viewport_size({"width": 700, "height": 900})
            results["narrow_layout"] = page.evaluate("""() => {
              const root = document.querySelector('comma-editor').shadowRoot;
              const shell = root.querySelector('.ce-shell');
              const comments = root.querySelector('.ce-comments');
              const card = root.querySelector('.ce-comment');
              return {
                shellWidth: shell.getBoundingClientRect().width,
                shellScrollWidth: shell.scrollWidth,
                commentsWidth: comments.getBoundingClientRect().width,
                commentsScrollWidth: comments.scrollWidth,
                cardWidth: card.getBoundingClientRect().width,
                cardScrollWidth: card.scrollWidth,
              };
            }""")

            body = read_doc()
            insertion = "\n\nINSERTED-UPSTREAM: " + ("provenance " * 20).strip() + "\n"
            heading = body.index("## 1. Introduction")
            insert_at = body.index("\n", heading) + 1
            edited = body[:insert_at] + insertion + body[insert_at:]
            save = api("/api/doc", "PUT", {
                "path": "paper.md", "body": edited, "base_rev": document["rev"], "actor": "test",
            })
            page.evaluate("document.querySelector('comma-editor').load()")
            page.wait_for_function(
                """rev => document.querySelector('comma-editor').documentState.rev === rev""",
                arg=save["rev"],
            )
            results["anchors_after_upstream_edit"] = editor_snapshot(page)
            results["byte_fidelity"] = read_doc() == edited

            broken = "As shown in Equation for section 9, the inline bound"
            mutated = edited.replace(broken, "As shown in a COMPLETELY REWORDED passage, the bound", 1)
            save2 = api("/api/doc", "PUT", {
                "path": "paper.md", "body": mutated, "base_rev": save["rev"], "actor": "test",
            })
            page.evaluate("document.querySelector('comma-editor').load()")
            page.wait_for_function(
                """rev => document.querySelector('comma-editor').documentState.rev === rev""",
                arg=save2["rev"],
            )
            results["anchors_after_quote_rewrite"] = editor_snapshot(page)
            results["console_errors"] = errors[:10]
            browser.close()
    finally:
        with open(DOC, "w", encoding="utf-8") as handle:
            handle.write(original)
        if os.path.exists(ASSET):
            os.remove(ASSET)
        for path in (DOC_MENU_SWITCH_DOC, DOC_MENU_NESTED_DOC, DOC_MENU_VERSION_INDEX):
            if os.path.exists(path):
                os.remove(path)
        for path in (
            os.path.dirname(DOC_MENU_NESTED_DOC),
            os.path.dirname(DOC_MENU_VERSION_INDEX),
        ):
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
        reset_comments()
        if original_slice_c_session is None:
            if os.path.exists(SLICE_C_SESSION):
                os.remove(SLICE_C_SESSION)
        else:
            with open(SLICE_C_SESSION, "wb") as handle:
                handle.write(original_slice_c_session)

    assert results["public_component_render"]["blocks"] > 100
    assert results["public_component_render"]["katex"] > 0
    assert results["public_component_render"]["images"] == 1
    assert results["public_component_render"]["figures"] == 1
    assert results["public_component_render"]["tableScrolls"] == results["public_component_render"]["tables"]
    assert results["public_component_render"]["imageStates"] == ["ready"]
    assert results["public_component_render"]["theme"] == "scientific"
    assert results["public_component_render"]["shellBackground"] == "rgb(255, 255, 255)"
    assert results["public_component_render"]["paperBackground"] == "rgb(255, 255, 255)"
    assert results["public_component_render"]["textureDisplay"] == "none"
    assert results["public_component_render"]["ceHeaderCount"] == 0
    assert results["public_component_render"]["embeddedControls"] == 1
    assert results["outline_expanded_default"]["mode"] == "expanded"
    assert results["outline_expanded_default"]["open"] is True
    assert results["outline_expanded_default"]["outlineDisplay"] == "block"
    assert results["outline_expanded_default"]["toggleDisplay"] != "none"
    assert results["outline_expanded_default"]["gridColumns"] == 3
    assert results["outline_persisted_closed"]["mode"] == "expanded"
    assert results["outline_persisted_closed"]["open"] is False
    assert results["outline_persisted_closed"]["preference"] == "closed"
    assert results["outline_persisted_closed"]["storage"] == "closed"
    assert results["outline_persisted_closed"]["gridColumns"] == 2
    assert results["outline_collapsed_default"]["mode"] == "collapsed"
    assert results["outline_collapsed_default"]["open"] is False
    assert results["outline_collapsed_default"]["outlineDisplay"] == "none"
    assert results["outline_collapsed_default"]["gridColumns"] == 2
    assert results["outline_collapsed_default"]["toggleText"].startswith("目录 ")
    assert "·" in results["outline_collapsed_default"]["toggleText"]
    assert results["outline_drawer_default"]["mode"] == "drawer"
    assert results["outline_drawer_default"]["open"] is False
    assert results["outline_drawer_default"]["outlineDisplay"] == "none"
    assert results["outline_drawer_open"]["open"] is True
    assert results["outline_drawer_open"]["outlineDisplay"] == "block"
    assert results["outline_drawer_jump"] == {"open": False, "focusEl": "outline-toggle"}
    assert results["image_lightbox_opened"] is True
    assert results["host_actions"]["innerHeaderCount"] == 0
    assert results["host_actions"]["statePrimary"] == ["文章总览", "AI Review", "导入", "参考资料", "批注 0"]
    assert results["host_actions"]["primaryIds"] == ["article-overview", "ai-review", "import-manuscript", "evidence", "comments"]
    assert results["host_actions"]["primary"] == ["文章总览", "AI Review", "导入", "参考资料", "批注 0"]
    assert results["host_actions"]["aiToolsHidden"] is True
    assert results["host_actions"]["aiToolsButtons"] == 0
    assert results["host_actions"]["overflow"] == ["全文批注", "源码编辑", "接受全部暂定", "显示已撤回"]
    more_host = results["host_actions"]["moreHost"]
    assert len(more_host) == 4
    assert more_host[0].startswith("版本 ")
    assert more_host[1] == "导出"
    assert more_host[2].startswith("讨论记录 ")
    assert more_host[3] == "评审记录"
    assert results["host_actions"]["panelTitle"] == "批注"
    assert results["document_menu"]["open"] is True
    assert results["document_menu"]["currentPath"] == "paper.md"
    assert results["document_menu"]["currentCheck"] == "✓"
    assert "headless-switch.md" in results["document_menu"]["paths"]
    assert "headless-nested/registered.md" in results["document_menu"]["paths"]
    assert results["document_menu_switch"] == {
        "search": "?doc=headless-switch.md",
        "docName": "headless-switch.md",
        "editorTitle": "headless-switch.md",
    }
    assert results["overview_shell"]["title"] == "文章总览"
    assert results["overview_shell"]["claims"] == 3
    assert results["overview_shell"]["revision"] == results["public_component_render"]["rev"]
    assert results["import_primary"]["modalTitle"] == "导入科研主稿"
    assert results["evidence_primary"]["drawerTitle"] == "参考资料"
    assert results["review_preflight"]["title"] == "复审预检"
    assert results["review_preflight"]["route"] in {"FIRST PASS", "NO DELTA", "LOCAL DELTA", "GLOBAL RISK"}
    assert results["review_preflight"]["primary"] in {"开始首次评审", "查看最近评审", "增量复审", "全文复审"}
    assert results["review_preflight"]["claims"] == 3
    assert results["document_only_boundary"] == {
        "toolbarActions": ["document-info"],
        "commentCountNodes": 0,
        "commentActionNodes": 0,
        "normalizedCommentAppliesTo": "comments.list",
        "missingCommentActionAvailable": False,
        "sidebarHidden": True,
    }
    assert results["operation_preview"]["groups"] == ["pending", "candidate-resolved", "system-conflict", "more"]
    assert results["operation_preview"]["counts"] == ["4", "1", "1", "1"]
    assert results["operation_preview"]["stateTitles"] == ["待处理", "待确认已解决", "系统冲突", "更多"]
    assert results["operation_preview"]["bulkSelected"] == ["op-create", "op-keep", "op-resolved", "op-withdraw"]
    assert results["operation_preview"]["humanHighlighted"] == 1
    assert results["operation_preview"]["humanBulkChecked"] is False
    assert "AI" in results["operation_preview"]["sourceBadges"]
    assert "原文" in results["operation_preview"]["placementBadges"]
    assert "待证" in results["operation_preview"]["placementBadges"]
    assert results["operation_preview"]["locationDetails"] >= 2
    assert all(open_state is False for open_state in results["operation_preview"]["locationDetailsOpen"])
    assert results["operation_preview"]["candidateAcceptLabel"] == "提交为待确认已解决"
    assert results["operation_preview"]["unverifiedDisabled"] is True
    assert results["operation_preview"]["muteEntry"] == "不再提示本问题"
    assert "相关原文自上轮未变化" in results["operation_preview"]["resurfacingNotice"]
    assert results["operation_preview"]["blockedDisabled"] is True
    assert "anchor is ambiguous" in results["operation_preview"]["blockedReason"]
    assert results["operation_preview_narrow"]["drawerScrollWidth"] <= results["operation_preview_narrow"]["drawerWidth"] + 1
    assert results["operation_preview_narrow"]["previewScrollWidth"] <= results["operation_preview_narrow"]["previewWidth"] + 1
    assert results["operation_preview_narrow"]["cardOverflow"] is False
    assert results["operation_writeback"] == {
        "status": "completed",
        "accepted": ["op-create", "op-human", "op-withdraw", "op-keep", "op-resolved"],
        "created": 1,
        "updated": 1,
        "withdrawn": 1,
        "kept": 1,
        "candidateResolved": 1,
        "blocked": 1,
        "humanStillMarked": True,
        "withdrawState": "withdrawn",
        "candidateWorkflow": "candidate_resolved",
    }
    assert results["scientific_layout"]["commentsScrollWidth"] <= results["scientific_layout"]["commentsWidth"] + 1
    assert results["scientific_layout"]["cardScrollWidth"] <= results["scientific_layout"]["cardWidth"] + 1
    assert results["narrow_layout"]["shellScrollWidth"] <= results["narrow_layout"]["shellWidth"] + 1
    assert results["narrow_layout"]["commentsScrollWidth"] <= results["narrow_layout"]["commentsWidth"] + 1
    assert results["narrow_layout"]["cardScrollWidth"] <= results["narrow_layout"]["cardWidth"] + 1
    assert results["anchors_baseline"]["resolved"] == 5
    assert results["anchors_after_upstream_edit"]["resolved"] == 5
    assert results["anchors_after_quote_rewrite"]["stale"] == 1
    assert results["byte_fidelity"] is True
    assert not results["console_errors"], results["console_errors"]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
