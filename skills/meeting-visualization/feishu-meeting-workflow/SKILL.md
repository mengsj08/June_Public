---
name: feishu-meeting-workflow
description: Use when Codex needs to analyze Feishu/Lark meeting notes, AI notes, Meeting transcript docs, local meeting transcripts, or meeting Markdown files; guide users through workspace selection, optional pre-consult/customer consultation skill setup, Lark CLI installation/configuration/profile selection, resolve AI notes to the original transcript, create a local meeting case, perform AI-based meeting analysis from the transcript, optionally route presales cases to the external skill_pre-consult full customer consultation flow, and render Markdown analysis into HTML.
---

# Feishu Meeting Workflow

Use this skill to run a repeatable meeting-analysis workbench. The AI guides the user through setup and decision points; scripts only verify local state, resolve sources, scaffold cases, and render HTML. The AI must personally read the transcript and write the actual analysis; do not use scripts to generate conclusions, risks, action items, or customer-facing wording.

## Core Boundary

- Treat the original `Meeting transcript` as the primary source.
- Treat AI notes as an entry point only. If given an AI notes docx, fetch it, extract the `Meeting transcript` docx link, then fetch the transcript.
- If given a transcript docx directly, fetch it directly.
- If given a local transcript or Markdown file, use it directly.
- Never print or copy app secrets, tokens, cookies, browser profiles, auth files, or raw private logs.
- Do not include Feishu doc/minute tokens or signed media URLs in customer-facing HTML.
- Do not hard-code the author's home directory or workspace paths. Resolve paths from user-provided directories, the current working directory, or the installed skill directory.
- Do not assume the pre-consult/customer consultation skill location. For presales routing, use a user-provided local skill path or GitHub repository URL. The default public source for the pre-consult route is `https://github.com/jeffzh0802/skill_pre-consult.git`.
- Do not treat setup as a black-box script. Guide the user through each decision node, then use commands to verify.

## AI-Led Setup Contract

Before fetching Feishu content, the AI should guide the user through these questions and only run verification commands after the needed choice is known:

1. **Where should outputs go?** Ask for or infer a working directory, normalize it to `WORK_DIR`, and keep runtime/cases under it.
2. **What is the input source?** Classify as Feishu AI notes docx, Meeting transcript docx, Feishu minutes token/link, local transcript, or local media.
3. **Is pre-consult needed?** If the meeting is presales or the user asks for customer consultation output, use the external `skill_pre-consult` flow. Accept either a local skill directory containing `SKILL.md` or a GitHub HTTPS repo URL. If none is provided, use `https://github.com/jeffzh0802/skill_pre-consult.git` for presales cases.
4. **Is `lark-cli` installed?** Check with `command -v lark-cli`. If missing, guide the user to install the official Lark CLI, then ask them to rerun the check. Do not continue Feishu fetch until it exists.
5. **Is a Lark app configured?** Use `lark-cli profile list`, `lark-cli config show`, and `lark-cli auth status` to verify. Do not read raw config files.
6. **If no app is configured, guide configuration.** Run or ask the user to run `lark-cli config init --new`. The user should get app credentials from the Feishu/Lark developer console and enter them into the CLI flow locally. Never ask the user to paste `app_secret`, tokens, or passwords into chat.
7. **If user auth is missing or scopes are insufficient, guide authorization.** Use the missing scope from CLI errors and ask the user to run `lark-cli auth login --scope "<scope>"`, or start the command and send the authorization link for the user to complete.
8. **For multiple organizations, avoid guessing.** Use profile checks and host routing when configured. If host routing is absent and more than one profile can work, either ask the user to choose a profile or let the resolver try readable profiles as fallback.

Load `references/guided_setup.md` when the user is installing/configuring Lark CLI, deciding where to put the pre-consult skill, or stuck at a permission/profile step.

## Path Handling

Before running scripts, set these shell variables for the current machine:

```bash
# The agent should fill this with the absolute path of this installed skill directory.
SKILL_DIR="<absolute-path-to-feishu-meeting-workflow>"

# Accept either an absolute or relative user workspace path, then normalize it.
WORK_DIR="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "<user-work-dir-or-.>")"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
```

Use `./meeting-runtime` and `./meeting-cases` under `WORK_DIR` by default, unless the user specifies other output directories.

## Workflow

### 1. Guide Setup And Input

Identify the source:

- Feishu AI notes docx URL
- Feishu Meeting transcript docx URL
- Feishu minutes URL/token
- Local transcript/Markdown file
- Local audio/video, only after user confirms upload is allowed

Ask only when necessary. If the user provides a URL or path, proceed through the setup contract above. Keep setup decisions in the case files when useful, but never include secrets.

### 2. Check Lark CLI And Profile

Use `lark-cli` for Feishu/Lark sources. If `lark-cli` is unavailable or not configured, guide the user to run:

```bash
command -v lark-cli
lark-cli config init --new
lark-cli auth login --recommend
```

For multi-organization setups, check profiles:

```bash
python3 "$SKILL_DIR/scripts/check_lark_profiles.py" \
  --source-ref "<feishu-url>" \
  --format table
```

Use the returned `recommended_profile` and `recommended_identity`. For user identity, add `--as user`; for bot fallback, add `--as bot`.

To customize organization routing, copy and edit:

```text
$SKILL_DIR/references/lark_profiles.example.json
```

The bundled example intentionally contains no personal profile names. For host-to-profile routing, create a user-local copy in `WORK_DIR` and pass `--config <your-json>`.

### 3. Resolve Source To Transcript

For Feishu docx or minutes sources, run:

```bash
python3 "$SKILL_DIR/scripts/resolve_meeting_source.py" \
  --source-ref "<ai-notes-or-transcript-docx-url, OR a /minutes/<token> link>" \
  --case-id "<YYYY-MM-DD-short-name>" \
  --runtime-dir "$WORK_DIR/meeting-runtime/<case-id>"
```

The resolver auto-detects the source kind:

- **docx** (`/docx/...` URL): fetched with `lark-cli docs +fetch`. AI notes are followed to the embedded `Meeting transcript` link.
- **minutes** (`/minutes/<token>` URL, or `minute_token:<token>`): fetched with `lark-cli vc +notes`, which writes artifacts under `source/minutes/<token>/`. The resolver auto-picks the most transcript-like artifact. If it picks wrong, re-run with `--minutes-artifact "<path-to-the-transcript-file>"`. AI notes that link to a minutes transcript are also followed into this path.

This writes:

- `source/meeting_transcript.md`
- `source/ai_notes.md`, only when the input was AI notes
- `source/source_resolution.json`

The printed JSON includes `source_kind` (`feishu_docx` or `feishu_minutes`) and `transcript_title`. Pass that same `source_kind` to `meeting_case.py` in the next step. If `--runtime-dir` is omitted, the script writes under `./meeting-runtime/<case_id>`.

### 4. Create Case

Create a case scaffold:

```bash
python3 "$SKILL_DIR/scripts/meeting_case.py" \
  --case-id "<case-id>" \
  --title "<meeting-title>" \
  --source-kind "<source_kind reported by resolve_meeting_source.py: feishu_docx | feishu_minutes>" \
  --source-ref "primary_transcript: <path-or-url>" \
  --input-file "<runtime-dir>/source/meeting_transcript.md" \
  --meeting-type auto \
  --customer-short-name "<short-name>" \
  --pre-consult-git-url "https://github.com/jeffzh0802/skill_pre-consult.git" \
  --case-root "$WORK_DIR/meeting-cases" \
  --runtime-root "$WORK_DIR/meeting-runtime"
```

Re-running case creation is safe: existing non-empty scaffold files (including any analysis you already wrote into `internal_brief.md` / `customer_material.md`) are preserved and reported as `skipped (exists)` on stderr. Pass `--force` only when you intentionally want to regenerate scaffolds and discard their current contents.

Use explicit `--meeting-type` when the user tells you the route:

- `internal`
- `presales`
- `customer_collaboration`
- `special`

If the user says to use the customer consultation or pre-consult skill, use `--meeting-type presales`. The preferred route is `skill_pre-consult` full flow: 会前 → 纪要 → 提问 → 成果 → 问卷. The script prepares the handoff only; the AI must read the external `crm` skill's `SKILL.md` and references before generating those artifacts.

Pre-consult dependency options:

- Local pre-consult skill: pass `--pre-consult-skill-path "<path-containing-SKILL.md>"`.
- GitHub pre-consult skill: pass `--pre-consult-git-url "https://github.com/<owner>/<repo>"`; add `--pre-consult-subdir "<subdir>"` if `SKILL.md` is not at the repo root.
- Default presales source: if no local path or Git URL is provided, the script clones `https://github.com/jeffzh0802/skill_pre-consult.git` into `<runtime-dir>/pre-consult/external-skills/`.
- Legacy `--crm-*` options are kept only for compatibility. New customer consultation cases should use the pre-consult route and `pre_consult_handoff.md`.

### 5. Analyze Manually From Transcript

Read `meeting_transcript.md` yourself. Write analysis artifacts in the case directory. Do not ask the script to decide the content.

Required outputs:

- `internal_brief.md`: internal judgment, risks, routing, next actions.
- `customer_material.md`: only facts, customer quotes, and customer-visible commitments.
- `collaboration_analysis.md` or a mode-specific analysis Markdown for HTML rendering.
- `pre_consult_handoff.md` for presales cases routed to the external pre-consult flow.

Use exact dates. Convert relative terms like “下周一” using the meeting date in the transcript.

Routing guidance:

- `internal`: internal recap, decisions, owners, action items. No customer page.
- `customer_collaboration`: cooperation context, confirmed items, joint actions, open confirmations. Customer page may be generated through this workflow.
- `presales`: use `skill_pre-consult` as an external dependency. Keep pre-consult inputs restricted to transcript-backed, customer-safe material plus explicit internal handoff notes. Do not copy Feishu private links, raw private excerpts, or internal sales judgment into customer-facing pre-consult outputs.
- `special`: create the case and question list; stop before producing downstream pages.

### 5.1 Pre-Consult Full Flow For Presales

For `customer_page_generator: pre_consult`, open `pre_consult_handoff.md` and use the external skill named `crm` from `pre_consult_skill_path`.

The five stages are:

1. `crm 会前`: build or backfill `agent_output/客户档案/<客户简称>.md` from `case.yaml`, known background, and meeting goals. If the meeting already happened, clearly treat this as a backfill step.
2. `crm 纪要`: use `meeting_transcript.md` plus `customer_material.md`; output customer-visible `纪要_<日期>.html`.
3. `crm 提问`: use the phase 2 minutes and archive; output consultant-only `作战手册_<日期>.html`.
4. `crm 成果`: use phase 2 minutes plus phase 3 notes or transcript-backed deep answers; output customer-visible `成果_<日期>.html`. If deep answers are missing, stop and ask for keywords instead of inventing a result page.
5. `crm 问卷`: use the archive, minutes, and result page; output customer-visible `问卷_<日期>.md`.

All pre-consult artifacts must be written under `pre_consult_workspace`, usually `<runtime-dir>/pre-consult/agent_output/`. Do not write customer artifacts into the external skill source directory.

### 6. Render HTML

Render the analysis Markdown:

```bash
python3 "$SKILL_DIR/scripts/render_meeting_html.py" \
  --input "<case-dir>/collaboration_analysis.md" \
  --case "<case-dir>/case.yaml" \
  --output "<runtime-dir>/html/report.html"
```

The current renderer is a simple standalone HTML renderer and remains a fallback for non-presales or collaboration reports. For presales customer consultation pages, prefer the external pre-consult full flow.

## HTML Quality Rules

- Use transcript-backed facts and evidence anchors.
- Prefer project-workbench layouts over generic reports: summary strip, timeline, action matrix, risk/decision modules, customer-visible section, evidence anchors.
- Do not show internal sales strategy, qualification labels, or private risk judgment in customer-visible sections.
- Do not embed Feishu signed image/media URLs; render them as source references or omit them.
- Keep generated HTML standalone unless the user asks for a web app.

## Local File Selection

If the user wants to use a local document instead of Feishu:

1. Ask for or infer the local file path.
2. If it is Markdown/text, read it directly.
3. If it is `.docx`, use an appropriate document extraction tool before analysis.
4. Never read `.env`, credentials, browser profiles, or token files.
5. Create the same case artifacts and render HTML if requested.

## Validation

Before final handoff:

- Run Python compile checks for edited scripts.
- Run the bundled offline self-test (no lark-cli or network needed). It covers transcript detection, AI-notes link extraction, meeting classification, the re-run no-clobber guarantee, and Feishu private-URL redaction:

```bash
python3 "$SKILL_DIR/scripts/selftest.py"
```

- Scan generated public artifacts for secret-like markers:

```bash
rg -n "authcode|internal-api-drive-stream|app_secret|credentials|\\.env|secret|token=|<script" "<output-path>"
```

Report absolute paths to the transcript, case, analysis Markdown, and HTML.
