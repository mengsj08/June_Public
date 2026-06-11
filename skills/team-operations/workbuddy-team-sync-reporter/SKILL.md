---
name: workbuddy-team-sync-reporter
description: Set up and operate a reusable WorkBuddy daily team sync reporter on a teammate's macOS computer. Use when configuring a machine with WorkBuddy, GitHub access, Feishu/Lark access, and a Feishu bot to check prerequisites, mirror GitHub repositories, run Feishu/Wiki sync commands, generate "who did what" Chinese team reports, and schedule daily Feishu delivery.
---

# WorkBuddy Team Sync Reporter

## Purpose

Build a local execution station that syncs team GitHub and Feishu/Wiki sources into `~/Documents/TeamSpace`, generates a daily Chinese work summary, and sends it to Feishu through a teammate-owned bot.

Use the bundled script instead of rewriting shell glue:

```bash
python3 scripts/team_sync_reporter.py <command> [options]
```

## Operating Model

- Work only under the target machine's `~/Documents/TeamSpace`.
- Keep secrets in local ignored files or environment variables. Never print token, secret, webhook, cookie, password, chat id, or `.env` values.
- Treat GitHub commit author as a sync/source signal. For "who did what", prefer task-card fields such as `assignee`, `status`, `priority`, and `updated`.
- Separate GitHub repository changes from Feishu/Wiki source changes. If Feishu has no documents modified in the report window, explicitly say so.
- Do not confuse first-time local full sync volume with source-system changes in the report window.
- Default to generating a reviewable draft before enabling automatic send.

## Setup Workflow

1. Copy or use this skill on the teammate's computer.
2. Initialize the workspace:

```bash
python3 /path/to/workbuddy-team-sync-reporter/scripts/team_sync_reporter.py init \
  --root "$HOME/Documents/TeamSpace" \
  --repo-name "<local-repo-name>" \
  --repo-url "https://github.com/<org>/<repo>.git"
```

`--repo-name` and `--repo-url` must come from the user or teammate who owns the machine. Do not assume a default repository name, an organization name, or a repository URL from the skill author machine.

3. Edit:

```text
~/Documents/TeamSpace/config/team-sync-reporter.config.json
```

Required configuration:

- `github.repos`: repositories to mirror. Each repo needs a user-provided local `name`, clone `url`, and branch.
- `feishu.sync_commands`: optional commands that export Feishu/Wiki content locally.
- `feishu.state_files`: local state JSON files used to detect Feishu source document changes.
- `send`: either a Feishu bot webhook env var or a local send command.
- `env_files`: local env files to load before sync/report/send, usually `~/.config/team-sync-reporter/secrets.env`.
- `report.message_prompt_path`: editable prompt that tells WorkBuddy how to turn the raw test report into the final Feishu message.

Create the local secret file from the generated template:

```bash
mkdir -p ~/.config/team-sync-reporter
cp ~/.config/team-sync-reporter/secrets.example.env ~/.config/team-sync-reporter/secrets.env
chmod 600 ~/.config/team-sync-reporter/secrets.env
```

Then edit `secrets.env` locally. Do not paste real values into chat, skill files, commits, screenshots, or reports.

4. Run preflight:

```bash
python3 ~/Documents/TeamSpace/automation-control-plane/team_sync_reporter.py doctor \
  --config ~/Documents/TeamSpace/config/team-sync-reporter.config.json
```

5. Run without sending:

```bash
python3 ~/Documents/TeamSpace/automation-control-plane/team_sync_reporter.py run \
  --config ~/Documents/TeamSpace/config/team-sync-reporter.config.json
```

6. Inspect the draft in:

```text
~/Documents/TeamSpace/team-info-library/review-queue/
```

7. Edit the Feishu message prompt until the team likes the output:

```text
~/Documents/TeamSpace/config/feishu-message-prompt.md
```

The raw report is intentionally mechanical. Use this prompt to define the final Feishu format, tone, section order, "who did what" wording, and how to handle no-update Feishu/Wiki windows.

8. After the final message format looks good, send a test Feishu message:

```bash
python3 ~/Documents/TeamSpace/automation-control-plane/team_sync_reporter.py send \
  --config ~/Documents/TeamSpace/config/team-sync-reporter.config.json \
  --target test \
  --message-file <final-feishu-message.md>
```

9. After test delivery succeeds and the user confirms the group message is satisfactory, configure the WorkBuddy daily automation.

## WorkBuddy Automation

Generate a WorkBuddy prompt:

```bash
python3 ~/Documents/TeamSpace/automation-control-plane/team_sync_reporter.py workbuddy-prompt \
  --config ~/Documents/TeamSpace/config/team-sync-reporter.config.json
```

Paste the generated prompt into a daily WorkBuddy automation. Prefer daily 09:00 local time.

If WorkBuddy can run shell commands directly, use:

```bash
~/Documents/TeamSpace/automation-control-plane/run_team_sync_reporter_daily.sh
```

Do not enable automatic sending until:

- `doctor` passes,
- `run` succeeds without `--send`,
- the user has adjusted `feishu-message-prompt.md` based on test report output,
- the final message correctly separates GitHub and Feishu changes,
- a test Feishu message has been sent with `--target test`,
- the Feishu target is confirmed by the user.

## Report Requirements

The report must include:

1. Absolute report window dates in Asia/Shanghai.
2. Overall counts: GitHub commits and Feishu/Wiki source document changes.
3. "Who did what" grouped by task-card assignee.
4. Task id, task title, status, and priority when available.
5. GitHub/local Kanban changes separately from Feishu/Wiki source changes.
6. Next actions, capped at 3-5 items.

When there are no Feishu/Wiki changes in the window, write:

```text
本时间窗口内未检测到 Feishu/Wiki 源文档新增或修改。
```

## Message Format Iteration

The script's generated report is a data-backed raw report, not necessarily the final group-message style. For setup and early operation:

1. Run `team_sync_reporter.py run` without `--send`.
2. Read the raw draft and the JSON evidence file next to it.
3. Adjust `~/Documents/TeamSpace/config/feishu-message-prompt.md`.
4. Ask WorkBuddy to regenerate the final Feishu message from the raw draft using that prompt.
5. Repeat until the user says the result is acceptable.
6. Send to a test Feishu bot or test group with `--target test`.
7. Only after a successful test send, set the WorkBuddy automation to run daily and send the production message.

If a teammate wants fully deterministic messages without AI rewriting, they can send the raw draft directly with `team_sync_reporter.py run --send`, but the recommended path is to tune the message prompt first.

## Feishu Sync Variants

For a team with an existing Feishu export script, configure it under `feishu.sync_commands`.

For a team using `lark-cli`, first configure and validate the local Feishu account with the appropriate Lark/Feishu skill or CLI. Then put the tested export command into `feishu.sync_commands`.

This skill does not hardcode a specific organization's Feishu document tokens. Keep source IDs, app credentials, bot secrets, and webhook URLs in local config or env files only.

For GitHub credentials, prefer `gh auth login` or SSH deploy keys owned by the teammate. Do not store GitHub tokens in this skill. If a non-interactive runner needs env-based auth, put only the env variable reference in config and keep the actual value in `secrets.env`.

## Bundled Resources

- `scripts/team_sync_reporter.py`: deterministic control script for init, preflight, sync, draft, send, and WorkBuddy prompt generation.
- `assets/config.example.json`: editable configuration template.
- `assets/feishu-message-prompt.md`: editable prompt for final Feishu message generation.
- `assets/secrets.example.env`: local environment template for webhook and Feishu export secrets.
- `assets/workbuddy-daily-prompt.md`: daily WorkBuddy automation prompt template.
- `references/configuration.md`: configuration notes and security boundaries.
