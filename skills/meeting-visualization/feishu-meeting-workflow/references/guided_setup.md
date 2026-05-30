# Guided Setup Decision Nodes

Use this reference when a user has not already configured the Feishu/Lark meeting workflow. The AI leads the setup; scripts are verification helpers, not the owner of the user-facing decisions.

## 1. Output Directory

Ask the user where this case should live. Accept either absolute or relative paths.

Recommended command after the user gives a directory:

```bash
WORK_DIR="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "<user-dir-or-.>")"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
```

Default layout:

- `meeting-runtime/`: fetched source material, source resolution JSON, HTML renders.
- `meeting-cases/`: case YAML, source index, internal brief, customer-safe material.

## 2. CRM Skill Dependency

Ask whether this meeting should use CRM.

If yes, ask the user to choose one:

- Local path: a directory containing `SKILL.md`.
- GitHub HTTPS URL: a repo that contains the CRM skill, optionally with a subdirectory.

Do not infer paths from the skill author's computer. Do not search random directories for CRM.

Case behavior:

- If the user provides `--crm-skill-path`, validate that the directory exists and contains `SKILL.md`.
- If the user provides `--crm-skill-git-url`, clone it into `WORK_DIR/external-skills` unless another install directory is specified.
- If the user has not provided either, create the case with `crm_skill_path: ""` and stop before invoking CRM.

## 3. Lark CLI Installed?

Verify:

```bash
command -v lark-cli
lark-cli --version
```

If missing, tell the user to install the official Lark CLI for their machine and rerun the check. If they need exact install instructions, consult the official Lark CLI documentation or the local Lark CLI skill instructions available in the current environment.

## 4. Lark App Configured?

Verify with commands that do not print secrets:

```bash
lark-cli profile list
lark-cli config show --profile "<profile>"
lark-cli auth status --profile "<profile>"
```

If no profile exists, guide the user:

```bash
lark-cli config init --new
```

The user should open the Feishu/Lark developer console, create or select an app, and copy the required app id / app secret into the CLI prompt locally. The user must not paste secrets into chat, docs, screenshots, or generated files.

## 5. User Authorization And Scopes

For user-owned docs and meeting notes, user identity is usually required.

Use CLI errors to identify missing scopes. Then guide the user to authorize only the needed scope:

```bash
lark-cli auth login --scope "<missing_scope>"
```

If the command prints an authorization URL, send that URL to the user and wait for them to complete the browser flow. Do not ask for auth codes, tokens, or cookies.

Common read-only needs:

- Docx fetch: `docx:document:readonly`
- Meeting search/record/notes: `vc:meeting.search:read`, `vc:record:readonly`, `vc:note:read`
- Minutes read/export: `minutes:minutes.search:read`, `minutes:minutes:readonly`, `minutes:minutes.transcript:export`

## 6. Multi-Organization Profile Choice

When a user has multiple organizations:

1. Run `check_lark_profiles.py --source-ref "<url>" --format table`.
2. If a configured host route matches, use the recommended profile.
3. If there is no host route and multiple profiles are usable, ask the user which organization owns the doc, or let `resolve_meeting_source.py` try available readable profiles as fallback.
4. If one profile fails with permission errors but another succeeds, record the successful profile in `source_resolution.json`.

## 7. Safety Rules

- Never read raw config files, browser profiles, cookies, tokens, or secret stores.
- Never copy app secrets, access tokens, refresh tokens, or auth codes into case files.
- Use scripts to verify status and fetch content; use AI judgment to explain next steps to the user.
- For local media upload, ask explicit approval before uploading anything to Feishu/Lark.
