# Skill Intake Process for June_Public

This document defines how to collect, evaluate, import, and publish third-party skills in the public `June_Public` repository.

The default principle is: collect first, evaluate second, import only when the skill is useful, clean, and appropriate for public sharing.

## 1. Asset Types

Use three levels of commitment.

### Collected skill

A skill that is interesting but not yet verified.

Keep it only in an index, usually:

```text
skills/collected-skills/README.md
```

Do not copy source code into this repository yet.

### Imported skill

A skill that is useful and can be publicly shared as a source copy.

Place it under a category directory, for example:

```text
skills/ip-operations/mj-adapt/
```

Each imported external skill should include a `SOURCE.md` file.

### Forked or adapted skill

A skill that has been changed into a local version.

Keep the source attribution in `SOURCE.md`, and document meaningful local changes in the skill README or git history.

## 2. Collection Index

Use `skills/collected-skills/README.md` to track skills before import.

Recommended table:

```markdown
| Skill | Source | Category | Status | License | Notes |
|---|---|---|---|---|---|
| mj-adapt | https://skills.makerjackie.com/ | 内容适配/小红书 | Imported | TODO: verify | 已导入 `skills/ip-operations/mj-adapt` |
```

Allowed status values:

```text
Watching
Evaluating
Imported
Forked
Rejected
Archived
```

Status meanings:

- `Watching`: only bookmarked; no validation yet.
- `Evaluating`: installed or inspected locally, but not ready for public import.
- `Imported`: copied into this repository with source attribution.
- `Forked`: copied and materially adapted into a local version.
- `Rejected`: evaluated and intentionally not adopted.
- `Archived`: kept for history, not actively used.

## 3. Import Criteria

Only import source code when all of the following are true:

- The purpose is clear.
- The skill has a `SKILL.md` or equivalent agent-readable entrypoint.
- It can run locally, or at least passes a minimal static check.
- It does not include private credentials or local runtime state.
- The license allows public redistribution, or the limitation is clearly documented.
- The repository owner is willing to maintain the copied version.

Do not import source code just because a skill is interesting. Use the collection index first.

## 4. Privacy and Cleanup Rules

Before copying a skill into `June_Public`, exclude local runtime and private state.

Must not be committed:

```text
.git/
.venv/
node_modules/
.env
cookies
tokens
Chrome profile
.lark-cli
output/
dist/
cache/
```

Also scan for:

```text
api_key
client_secret
access_token
refresh_token
Authorization
Bearer
password
phone
cookie
token
secret
```

Matches are not automatically disqualifying, because docs and code often mention these words. Inspect matches and confirm that no real secret or account-specific value is present.

## 5. SOURCE.md Template

Every imported external skill should include a source file like this:

```markdown
# Source

- Name: mj-adapt
- Original source: https://skills.makerjackie.com/
- Original install command: npx skills add makerjackie/skills --skill mj-adapt
- Imported into: skills/ip-operations/mj-adapt
- Imported at: 2026-05-28
- License: TODO: verify from upstream
- Local changes: see git history
- Privacy review: no local credentials, profiles, cookies, tokens, or generated runtime state included
```

For skills imported from GitHub, include both the repository URL and the original path when available.

## 6. Standard Intake Flow

Follow this sequence for each new skill.

1. Collect source information.

   Confirm the original URL, skill name, install command, intended use, license, and whether it depends on private accounts or local browser state.

2. Register first.

   Add the skill to `skills/collected-skills/README.md` with status `Watching` or `Evaluating`.

3. Try locally.

   Install or inspect the skill in the local skill area, not directly in the public repository. Confirm that it has an agent-readable entrypoint and a minimal runnable workflow.

4. Choose the import outcome.

   Use the index only for bookmarks. Use a source copy plus `SOURCE.md` for useful reusable skills. Use a forked/adapted version when the local workflow materially changes the upstream skill.

5. Clean before import.

   Exclude runtime folders, credentials, generated outputs, caches, and personal configuration.

6. Verify before push.

   Run at least a structure check, privacy scan, README/SKILL readability check, and the available tests or static checks.

## 7. Cross-Agent Trigger Prompt

Use this single instruction to start the intake process in Codex, Claude, Cursor, opencode, or another agent:

```text
请按我的 June_Public skill intake 流程评估并纳入这个 skill：<来源地址或安装命令>。先登记来源和状态，检查许可证、隐私信息、可运行性和目录归类；只有适合公开分享时，才复制源码到对应 skills 分类目录，并附带 SOURCE.md、README 更新和最小验证结果。
```

Example for `mj-adapt`:

```text
请按我的 June_Public skill intake 流程评估并纳入这个 skill：https://skills.makerjackie.com/。它的安装命令是 npx skills add makerjackie/skills --skill mj-adapt。先登记来源和状态，检查许可证、隐私信息、可运行性和目录归类；只有适合公开分享时，才复制源码到 skills/ip-operations/mj-adapt，并附带 SOURCE.md、README 更新和最小验证结果。
```

## 8. mj-adapt Example

`mj-adapt` is treated as an imported skill, not just a bookmark.

Known facts:

- Source site: `https://skills.makerjackie.com/`
- Install command: `npx skills add makerjackie/skills --skill mj-adapt`
- Local category: `skills/ip-operations/`
- Imported path: `skills/ip-operations/mj-adapt/`
- Purpose: adapt long-form content into WeChat and Xiaohongshu-ready assets

Recommended follow-up for this imported skill:

- Add `skills/ip-operations/mj-adapt/SOURCE.md`.
- Verify upstream license and replace `TODO: verify` when confirmed.
- Keep generated output folders out of version control unless they are intentional fixtures.
