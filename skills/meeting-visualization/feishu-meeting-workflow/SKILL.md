---
name: feishu-meeting-workflow
description: "Use when Codex needs to process meeting material from a bot message, Feishu/Lark AI Notes, Meeting transcript docs, minutes links, Get笔记 or third-party notes, local Markdown/transcripts, pasted text, or uploaded meeting text. Handles source normalization, multi-organization Feishu routing, team case creation, route selection, Agent analysis, optional supplement, optional crm/skill_客户洽谈, WOW handoff, meeting-visual-report HTML with Prompt confirmation, optional AirDrop publishing of approved HTML as a shareable live webpage, and unified one-document Feishu return."
---

# Meeting Material Workflow

Use this skill to turn meeting material into a reviewed local case package and, when approved, one formal Feishu archive document. Scripts orchestrate fetching, scaffolding, route state, manifests, and delivery. The Agent must read the transcript/notes and write the actual analysis.

## Reference Loading

- Load `references/output_contract.md` before deciding what files or Feishu documents may be created. It is the source of truth for output types, route ownership, pauses, and the one-document archive rule.
- Load `references/guided_setup.md` when installing/configuring Lark CLI, choosing Lark profiles, resolving permission issues, or deciding where the external pre-consult/customer consultation skill lives.
- Load `references/team_bot_chain.md` when the user mentions the team bot, FE72/FM96 automation, old Mac / WOW routing, two-Mac sync, `business_meeting_cases`, route keywords, or Feishu return behavior.

## Hard Boundaries

- Treat the original transcript as the primary source when one exists.
- Treat AI notes, Get笔记, third-party notes, and summaries as entry points or secondary sources unless they are the only available material.
- If given Feishu AI Notes docx, fetch it, extract the embedded `Meeting transcript` docx or minutes link, then fetch the transcript.
- If given a transcript docx, local transcript, Markdown, exported note, or pasted text, normalize it directly into the case source directory.
- If a non-Feishu source cannot be read with current tools or permissions, ask the user to export Markdown/text or paste the content.
- Source provenance is a mandatory gate, not a manual optional step. Before route recording, analysis rendering, route finalization, or Feishu return, scripts require either a non-empty `source/meeting_transcript.md` or an explicit negative `source/source_resolution.json` with `transcript_available:false` and `reason`; finalization and return still require the real transcript and must block on negative provenance.
- Do not let deterministic scripts invent conclusions, risks, action items, customer-facing wording, or route-specific business judgment.
- For team @bot input, parse route keywords from the original message first. If absent, show the route menu and wait.
- Do not start formal analysis before the route is known.
- The default route uses the current Agent directly. Do not invoke `crm`, `skill_客户洽谈`, `meeting-visual-report`, WOW, or another specialist route unless the user selected it or the route contract requires it.
- `补资料` is an intermediate route. After context collection, ask which final route to enter unless the user explicitly stops there.
- Use `crm` / `skill_客户洽谈` only when the user explicitly chooses the customer-consultation route.
- Use `meeting-visual-report` only after customer-facing HTML is explicitly requested; it must output a structured Prompt first and wait for confirmation before final HTML.
- After a final route creates Markdown or HTML, run `scripts/finalize_route.py` to normalize outputs and build the Feishu return package.
- Require user approval before CRM/customer-facing HTML send/upload, before real Feishu writes when the target changed, and before any legacy split-document delivery.
- Archive team meeting outputs only into the configured 智回 `【内部】脑回路实验室` meeting-chain targets. Validate the target Wiki space before send/upload.
- Default Feishu hygiene is one meeting source -> one formal Feishu archive document from `analysis/feishu_meeting_document.md`. Do not fan out local artifacts into multiple Wiki/Drive documents unless the user explicitly asks for legacy multi-artifact upload.
- The meeting output can be requested as a live webpage, not just a local HTML file. Publishing reviewed HTML to AirDrop (`airdrop deploy`) is an outward-facing, shareable action: require explicit user confirmation before deploying, deploy only customer-safe HTML (no Feishu private links, signed media URLs, tokens, secrets, or internal sales judgment), and record only the returned public URL — never the AirDrop token. The token lives in `~/.airdrop/config.json` (0600) or `AIRDROP_TOKEN`; never print, copy, or commit it.
- Never print or copy app secrets, tokens, cookies, browser profiles, auth files, raw private logs, Feishu doc/minute tokens, or signed media URLs into docs, reports, commits, screenshots, chat, or customer-facing HTML.
- Do not hard-code the author's home directory, workspace paths, app secrets, chat IDs, or profile names. Resolve paths from user input, the current working directory, the installed skill directory, env config, or Lark CLI profile checks.
- Do not assume the external customer-consultation skill location. Accept a user-provided local skill path or GitHub HTTPS repo URL. The default public source, when needed, is `https://github.com/jeffzh0802/skill_pre-consult.git`.

## Setup Questions

Ask only when the answer is not obvious from the request:

1. Where should local outputs go? Normalize to `WORK_DIR`.
2. What is the source type: Feishu AI Notes docx, Meeting transcript docx, Feishu minutes, Get笔记/third-party note, local transcript, pasted text, or local media?
3. Which route is requested? If no route is provided, pause and show the route choices from `references/output_contract.md`.
4. For Feishu/Lark sources, is `lark-cli` installed, configured, and authorized for the source organization?
5. For multiple organizations, which profile can read the source? Prefer profile verification over guessing.
6. For customer-consultation routing, where is `skill_客户洽谈` / `skill_pre-consult`: local path or GitHub URL?

## Path Setup

Set paths per machine before running scripts:

```bash
SKILL_DIR="<absolute-path-to-feishu-meeting-workflow>"
WORK_DIR="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "<user-work-dir-or-.>")"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
```

Standalone workbench defaults:

```text
./meeting-runtime
./meeting-cases
```

Team bot defaults:

```text
~/Documents/Shape-of-thought/z-h-ai/team-workspace/shared/docs/business_meeting_rawdata/_automation_inbox
~/Documents/Shape-of-thought/z-h-ai/team-workspace/shared/docs/business_meeting_cases
```

## Operating Flow

### 1. Resolve Source

For Feishu/Lark sources, verify CLI/profile access first:

```bash
command -v lark-cli
lark-cli profile list
lark-cli auth status
python3 "$SKILL_DIR/scripts/check_lark_profiles.py" \
  --source-ref "<feishu-url>" \
  --format table
```

For Feishu docx, minutes, or Get笔记 sources, `meeting_case.py` automatically invokes the resolver after writing `case.yaml` when a supported `--source-ref` is present. You may still run the resolver directly before case creation for diagnosis or controlled re-fetch:

```bash
python3 "$SKILL_DIR/scripts/resolve_meeting_source.py" \
  --source-ref "<ai-notes-or-transcript-docx-url-or-minutes-link>" \
  --case-id "<YYYY-MM-DD-short-name>" \
  --runtime-dir "$WORK_DIR/meeting-runtime/<case-id>"
```

This should produce `source/meeting_transcript.md`, `source/source_resolution.json`, and optionally `source/ai_notes.md`. If the source cannot be fetched or the fetched transcript is empty, the resolver must still write `source/source_resolution.json` with `transcript_available:false`, `reason`, attempted profile/identity data, and any discovered transcript fallback link. That negative provenance is a stop record, not approval to analyze or return.

### 2. Create Or Reuse Case

When a case already exists under the team workspace, reuse it unless the user asks to re-fetch. Read `case.json`, route/request files under `analysis/`, and source files under `source/`.

For a new case:

```bash
python3 "$SKILL_DIR/scripts/meeting_case.py" \
  --case-id "<case-id>" \
  --title "<meeting-title>" \
  --source-kind "<feishu_docx|feishu_meeting|feishu_minutes|getbiji_note|local_media|manual_text>" \
  --source-ref "primary_transcript: <path-or-url>" \
  --input-file "<runtime-dir>/source/meeting_transcript.md" \
  --meeting-type auto \
  --customer-short-name "<short-name>" \
  --pre-consult-git-url "https://github.com/jeffzh0802/skill_pre-consult.git" \
  --case-root "$WORK_DIR/meeting-cases" \
  --runtime-root "$WORK_DIR/meeting-runtime"
```

Re-running case creation should preserve existing non-empty analysis files. Use `--force` only when intentionally regenerating scaffolds. For local transcript input, the script normalizes the text into `<runtime-dir>/source/meeting_transcript.md` and writes positive source provenance. For Feishu/minutes/Get笔记 source refs, it writes `case.yaml` first, then automatically resolves the primary source into the same runtime `source/` directory.

### 3. Record Route

If the case is at `analysis_status=needs_user_context` or `analysis_stage=meeting/context`, handle the route reply before analysis:

```bash
python3 "$SKILL_DIR/scripts/route_context_reply.py" \
  --case-dir "<case-dir>" \
  --reply "<用户回复>"
```

The helper records route state only. The Agent then performs the selected work according to `references/output_contract.md`.

### 4. Analyze

Read `source/meeting_transcript.md` and available notes personally. Do not start analysis from AI Notes alone when the transcript gate is unresolved or negative. Write route outputs into the case package:

- Default analysis: `analysis/meeting_analysis.md`
- Supplement: `analysis/context_materials.md`
- WOW return: `analysis/remote_outputs/` and/or `html/`
- CRM/customer-consultation: `analysis/crm/` and/or `html/`
- Customer-facing HTML: final reviewed HTML under `html/`

If the user wants the output as a webpage (a live shareable URL rather than a local file), still write the reviewed HTML under `html/` here, then publish it in step 6.

Use exact dates. Convert relative dates from the meeting date when needed. Treat `internal`, `partner`, and `customer` as separate archive audiences: partner meetings are external collaboration, but not customer sales. Keep customer-facing material free of internal sales labels, private strategy, Feishu private links, signed media URLs, and unsupported claims.

### 5. Finalize And Return

After final route outputs exist:

```bash
python3 "$SKILL_DIR/scripts/finalize_route.py" \
  --case-dir "<case-dir>" \
  --route "<agent_default|crm_skill|customer_html_prompt|wow_codex|wow_claude>" \
  --scan-case
```

For CRM or customer-facing HTML, ask:

```text
成果已放入会议 case。是否确认收尾归档并回传飞书？
```

After approval:

```bash
python3 "$SKILL_DIR/scripts/finalize_route.py" \
  --case-dir "<case-dir>" \
  --route "<route>" \
  --approve
```

When a Feishu target is known and approved, add `--send`. Use `--send --dry-run` before enabling or changing a target. Use `--doc` to append to an existing Feishu document, or `--folder-token` / `--wiki-token` to create the single archive document under a specific parent. Without `--send`, the script only writes local return files.

Expected return files:

- `analysis/route_done.json`
- `analysis/feishu_meeting_document.md`
- `analysis/feishu_index_entry.md`
- `analysis/source_paths_for_feishu.md`
- `analysis/feishu_return_message.md`
- `analysis/feishu_return_manifest.json`

If writing to an existing Feishu document or index page, read the current document first and preserve existing reviewed content. The index should point to the single formal archive document, not to duplicated per-artifact docs.

If `finalize_route.py` or `return_to_feishu.py` reports a provenance/transcript gate failure, stop. Do not mark `review_approved`, do not create a return package, and do not send to Feishu until `source/meeting_transcript.md` is present and non-empty.

### 6. Optional: Publish As A Live Webpage (AirDrop)

Use this only when the user asks for the meeting output as a webpage — a shareable live URL, not just a local HTML file. Deploy reviewed HTML from the case `html/` directory with the AirDrop CLI (`@zh-ai/airdrop-cli`, global binary `airdrop`).

Authentication is a one-time human step, not something this skill runs: `airdrop login` is interactive (it prompts for an API token on stdin), and the token then persists in `~/.airdrop/config.json` (0600). Do not run `airdrop login` from the automated flow. Only check auth:

```bash
airdrop whoami       # confirm authentication; never print the token
```

If `whoami` reports "Not authenticated", stop and ask the user to run `airdrop login` once themselves (or to set `AIRDROP_TOKEN`); then continue.

Before deploying: confirm with the user (publishing is outward-facing and shareable), and re-scan the HTML for secret-like markers (see Validation) so no Feishu private links, signed media URLs, or tokens go public.

```bash
airdrop deploy "<case-dir>/html/report.html" --json          # a single HTML file
airdrop deploy "<case-dir>/html" --json                      # a directory or a .zip
airdrop deploy "<case-dir>/html" -p "<slug>" --json          # new version of an existing project
```

`deploy` accepts a single HTML file, a directory, or a ZIP. `--json` prints a result object; the public link is the `url` field (e.g. `https://airdrop.z-h-ai.com/p/<slug>`), and `slug` is the project id to pass back via `-p` for later versions. Record the `url` (and the `slug` for redeploys) in the case — for example in `analysis/feishu_return_message.md` or `analysis/feishu_index_entry.md` — so the Feishu archive can link to the live page. Record only the URL and slug, never the token.

## Validation

Before final handoff:

- If scripts changed, run Python compile checks and `python3 "$SKILL_DIR/scripts/selftest.py"`. The self-test covers the mandatory provenance gate, resolver negative provenance, return-package blocking, source path redaction, and output routing.
- For docs-only changes, inspect references and route/output terminology for drift.
- Scan generated public artifacts for secret-like markers:

```bash
rg -n "authcode|internal-api-drive-stream|app_secret|credentials|\\.env|secret|token=|<script" "<output-path>"
```

Report absolute paths to the transcript, case, analysis Markdown, HTML, and Feishu return manifest.
