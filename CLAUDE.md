# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`June_Public` (remote `github.com/mengsj08/June_Public`) is a **public skill-publishing repository**. It holds skill packages — instructions, scripts, tests, fixtures, and selected extension source — that anyone can drop into their own AI tool's skills directory and run on their own machine. It is the *published* copy of skills developed elsewhere; it is not a workspace for live operations.

The hard rule that defines this repo: **nothing private may ever live here.** No account state, cookies, login sessions, Chrome profiles, Feishu/Lark `.lark-cli` profiles, app secrets, user/bot tokens, fetched meeting transcripts, collected/采集 output, publish drafts, or runtime workspaces. `.gitignore` already excludes the common runtime caches (`.topic2feishu-runtime/`, `.lark-cli/`, `.env`, `*.log`, `.venv/`, `.pytest_cache/`). Each consumer connects their *own* account/profile locally. When you must reference a secret, refer to it by path, never by value.

## Repository layout

Everything lives under `skills/`, grouped by domain. Each domain dir has its own `README.md`:

- `skills/ip-operations/` — 内容运营 / IP 运营 / 多平台分发. Contains `xiaohongshu-skills/` (小红书 browser-automation skill collection, has its own nested `CLAUDE.md`) and `mj-adapt/` (multi-platform content adaptation: 公众号 HTML, 小红书 长图, social short-form).
- `skills/meeting-visualization/feishu-meeting-workflow/` — 飞书/Lark 会议工作流: resolve AI notes → transcript, scaffold a local meeting case, AI-write the analysis, render customer-safe HTML.
- `skills/openclaw/` — **Archived** OpenClaw onboarding/config skills (七个 `openclaw-*` builder skills). Kept for historical reference only; do not promote or extend for new workflows.

Note: the root `README.md` lists a `landing/` directory of HTML pages that is not currently present in the tree — treat those links as aspirational, not authoritative.

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
- `mj-adapt/` (Node, `package.json` + puppeteer/cheerio): `npm run generate`, `generate:xhs`, `generate:cover`. No test suite.
- `openclaw/*` (archived): markdown-only, no commands.

## Working in nested skills

`skills/ip-operations/xiaohongshu-skills/` has its **own `CLAUDE.md`** covering its git workflow (branch + PR, never push `main` directly), its `scripts/` (Python engine) ↔ `skills/` (SKILL.md definitions) two-layer architecture, the CLI subcommand ↔ MCP tool mapping, code conventions, and safety constraints (publish actions require user confirmation, absolute paths only, sensitive content passed via file not inline args). **Defer to that file** when editing under that tree rather than duplicating its guidance here.

## Before publishing or editing

- Confirm no real account/runtime data is being committed (scan for tokens, cookies, profiles, transcripts, 采集 results).
- Keep fixtures synthetic.
- Commit/push only when the user explicitly asks; for `xiaohongshu-skills` follow its branch-then-PR rule.
