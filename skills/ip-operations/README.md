# IP Operations Skills

This directory contains reusable skills for Xiaohongshu/IP operations workflows.

## Included skills

- `xiaohongshu-skills/`: full Xiaohongshu browser-operation skill package, including the Chrome bridge extension, CLI scripts, publishing/search/interact flows, tests, and onboarding docs.
- `topic2feishu-xhs/`: standalone task skill for collecting Xiaohongshu notes by topic and writing structured results to Feishu Base. The executable implementation is in `xiaohongshu-skills/`.
- `mj-adapt/`: content adaptation skill for turning long-form material into Xiaohongshu-style visual posts and assets.

## Privacy boundary

These public skill copies intentionally exclude local runtime state and private credentials:

- no Chrome profile or browser login state
- no `.lark-cli` profile data
- no cookies, tokens, app secrets, or API keys
- no virtual environments or dependency caches

Each user must connect their own Xiaohongshu account, browser extension, and Feishu/Lark CLI profile locally before running account-bound workflows.
