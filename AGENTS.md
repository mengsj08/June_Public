# AGENTS.md — June_Public

> doc_type: rule · owner: June · last_verified: 2026-06-18

This file is the canonical rule source for Codex, Claude Code, and other local execution agents working in this repository. `CLAUDE.md` is a one-line `@AGENTS.md` import stub (Claude Code only auto-loads CLAUDE.md); edit rules here, not in a second copy.

## Local safety boundary

This independent Git root may not inherit the parent workspace agent rules. Act without asking only when goal and target are explicit, scope is user-named, the action is reversible, no external system or other person's work is affected, and the result can be verified locally. External, irreversible, publishing, deleting, cross-workspace, or history-rewriting actions require explicit authorization. A plan, a started command, a successful tool return, or a partial check is not completion: claim completion only when every deliverable exists and relevant verification has passed, state unverified parts explicitly, and never expose credentials or private material.

## What this repository is

`June_Public` (remote `github.com/mengsj08/June_Public`) is a **public skill-publishing repository**. It holds skill packages — instructions, scripts, tests, fixtures, and selected extension source — that anyone can drop into their own AI tool's skills directory and run on their own machine. It is the *published* copy of skills developed elsewhere; it is not a workspace for live operations.

The hard rule that defines this repo: **nothing private may ever live here.** No account state, cookies, login sessions, Chrome profiles, Feishu/Lark `.lark-cli` profiles, app secrets, user/bot tokens, fetched meeting transcripts, collected/采集 output, publish drafts, or runtime workspaces. `.gitignore` already excludes the common runtime caches (`.topic2feishu-runtime/`, `.lark-cli/`, `.env`, `*.log`, `.venv/`, `.pytest_cache/`). Each consumer connects their *own* account/profile locally. When you must reference a secret, refer to it by path, never by value.

## Repository layout

Everything lives under `skills/`, grouped by domain. Each domain dir has its own `README.md`:

- `skills/ip-operations/` — 内容运营 / IP 运营 / 多平台分发. Contains `xiaohongshu-skills/` (小红书 browser-automation skill collection, has its own nested `CLAUDE.md`) and `article-visualization/` (article/paper to layperson-friendly visual assets: long images, Xiaohongshu cards, WeChat covers, short copy).
- `skills/meeting-visualization/feishu-meeting-workflow/` — 飞书/Lark 会议工作流: resolve AI notes → transcript, scaffold a local meeting case, AI-write the analysis, render customer-safe HTML.
- `skills/team-operations/workbuddy-team-sync-reporter/` — WorkBuddy 团队同步日报执行站: mirror user-provided GitHub repos, run local Feishu/Wiki export commands, generate reviewable Chinese reports, then hand off scheduled sends to WorkBuddy.
- `skills/openclaw/` — **Archived** OpenClaw onboarding/config skills (七个 `openclaw-*` builder skills). Kept for historical reference only; do not promote or extend for new workflows.

The `landing/` directory contains public static landing pages. Keep landing pages paired with active promoted skills and remove or archive pages for skills that are no longer promoted.

## Skill-package convention

A skill is a self-contained directory. Where to add a new one and what it must contain:

- **Placement:** create the new skill directory under the appropriate `skills/<domain>/` group (or a new domain group with its own `README.md`).
- **`SKILL.md` is the contract.** Every skill (and every sub-skill) has a `SKILL.md` with YAML frontmatter — at minimum `name` and `description` (the description is the trigger text the AI matches against; write it as "当用户要求 … 时触发" / "Use when …"). Richer skills add `version` and `metadata.openclaw` (declaring `requires.bins`, `os`, `emoji`, `homepage`). The body tells the AI *how* to invoke the skill's scripts.
- **`README.md`** is the human-facing entry: when-to-use table and example prompts.
- **Supporting files** as needed: `scripts/` (the automation engine), `assets/`, `fixtures/` (sample inputs/outputs — keep these synthetic, never real captured data), `references/`, plus spec docs (e.g. `XHS_HTML_SPEC.md`), and `SOURCE.md` to credit upstream.
- **Nesting:** a skill collection can contain a `skills/` subdir of sub-skills, each with its own `SKILL.md` (see `xiaohongshu-skills/skills/xhs-*`).

There is **no repo-wide build/test runner.** Skills are markdown + script packages; each carries its own toolchain. Run commands from inside the specific skill directory:

- `xiaohongshu-skills/` (Python, `uv` + `pyproject.toml`): `uv sync`, `uv run ruff check .`, `uv run ruff format .`, `uv run pytest`. Code style: line length 100, full type hints with `from __future__ import annotations`, exceptions subclass `XHSError`, user-facing messages in 中文, JSON `ensure_ascii=False`.
- `feishu-meeting-workflow/` (Python, no package manager): offline self-test `python3 scripts/selftest.py` (exit 0 = pass) — verifies scripts don't clobber analysis files and don't embed Feishu private URLs.
- `article-visualization/` (Node scripts, no package manager in the public copy): run `node --check scripts/*.js` for syntax checks. Runtime case folders, downloaded images, screenshots, rendered HTML, and unpublished drafts must stay outside this public repo.
- `workbuddy-team-sync-reporter/` (Python standard library): `python3 scripts/team_sync_reporter.py --help` and `python3 -m py_compile scripts/team_sync_reporter.py`.
- `openclaw/*` (archived): markdown-only, no commands.

## Working in nested skills

`skills/ip-operations/xiaohongshu-skills/` has its **own `CLAUDE.md`** covering its git workflow (branch + PR, never push `main` directly), its `scripts/` (Python engine) ↔ `skills/` (SKILL.md definitions) two-layer architecture, the CLI subcommand ↔ MCP tool mapping, code conventions, and safety constraints (publish actions require user confirmation, absolute paths only, sensitive content passed via file not inline args). **Defer to that file** when editing under that tree rather than duplicating its guidance here.

## Tool routing

Codex = the main local execution tool (code, scripts, verification); Claude = strategy / review / research reasoning / retrospective. Rules are edited once here in `AGENTS.md`; `CLAUDE.md` is an `@AGENTS.md` import stub.

## Before publishing or editing

- Confirm no real account/runtime data is being committed (scan for tokens, cookies, profiles, transcripts, 采集 results).
- Keep fixtures synthetic.
- Commit/push only when the user explicitly asks; for `xiaohongshu-skills` follow its branch-then-PR rule.
