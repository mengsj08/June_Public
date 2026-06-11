# Configuration Notes

## Files

Default target layout:

```text
~/Documents/TeamSpace/
  automation-control-plane/
    team_sync_reporter.py
    run_team_sync_reporter_daily.sh
  workflows/
  team-info-library/
    raw/
    normalized/
    derived/
    review-queue/
  config/
    team-sync-reporter.config.json
    feishu-message-prompt.md
```

## GitHub

The repository list is user-owned configuration. The skill must not assume a default organization or repository.

Example:

```json
{
  "github": {
    "repos": [
      {
        "name": "example-repo",
        "url": "https://github.com/example-org/example-repo.git",
        "branch": "main"
      }
    ]
  }
}
```

Use `gh auth login --git-protocol https` or SSH deploy keys before running the reporter. The reporter checks access with `git ls-remote` and mirrors repositories under:

```text
$INFO_LIBRARY_ROOT/raw/github/<repo-name>
```

The `name` must be a local directory-safe short name, not a URL. The `url` must be the real HTTPS or SSH clone URL provided by the user.

## Secrets

The generated config includes:

```json
{
  "env_files": ["~/.config/team-sync-reporter/secrets.env"]
}
```

The script loads this file before `doctor`, `sync`, `send`, and `run`. It only reports whether env names are present and their lengths; it does not print values.

Create it from:

```bash
~/.config/team-sync-reporter/secrets.example.env
```

Typical values:

```bash
FEISHU_BOT_WEBHOOK=...
FEISHU_BOT_SECRET=...
```

For Feishu export commands, put only local environment variables required by that command in the env file. For GitHub, prefer `gh auth login` or deploy keys; avoid PAT values unless the team explicitly accepts that local secret-management tradeoff.

## Feishu/Wiki

Feishu sync differs by organization. Put a tested export command in `feishu.sync_commands`; the command should write local files and a state JSON.

The reporter can read state JSON shaped like:

```json
{
  "wikis": {
    "wiki_id": {
      "doc_token": {
        "title": "Document title",
        "latest_modify_time": 1780718849,
        "obj_edit_time": 1780718849,
        "latest_modify_user": "optional",
        "path": "/local/path/doc.md"
      }
    }
  }
}
```

## Sending

Supported send modes:

- `webhook`: reads `FEISHU_BOT_WEBHOOK` and optional `FEISHU_BOT_SECRET` from environment.
- `webhook` test mode: `--target test` reads `FEISHU_TEST_BOT_WEBHOOK` and optional `FEISHU_TEST_BOT_SECRET` when configured.
- `command`: runs a local command such as `python3 send_feishu_text.py {message}`.

Keep credentials outside skill files.

## Message Prompt

The generated raw report can be too mechanical for a team chat. The file below is intentionally user-editable:

```text
~/Documents/TeamSpace/config/feishu-message-prompt.md
```

Use it to define:

- section order,
- tone,
- how to summarize "who did what",
- how much detail to include,
- whether to include owner/status/priority,
- how to phrase Feishu/Wiki no-change windows.

Recommended rollout:

1. Run `team_sync_reporter.py run` without `--send`.
2. Let WorkBuddy read the raw report plus `feishu-message-prompt.md`.
3. Generate `final-feishu-message.md`.
4. Revise `feishu-message-prompt.md` until the output is satisfactory.
5. Send a test message:

```bash
python3 ~/Documents/TeamSpace/automation-control-plane/team_sync_reporter.py send \
  --config ~/Documents/TeamSpace/config/team-sync-reporter.config.json \
  --target test \
  --message-file <final-feishu-message.md>
```

6. After test delivery succeeds, configure WorkBuddy's daily automation for production delivery.
