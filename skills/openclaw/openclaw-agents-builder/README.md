# openclaw-agents-builder

Status: archived reference.

Guided interview for drafting `AGENTS.md`, including workflow rules and permission boundaries.

## When To Use

- The user wants to define what an OpenClaw agent may do.
- The user needs a red/yellow/green permission model.
- The user wants operational workflow rules in one Markdown file.

## Quick Start For AI

```text
Use openclaw-agents-builder. Ask one question at a time, then draft AGENTS.md with workflow, permissions, and memory rules.
```

## Inputs

- Daily workflow.
- Tasks the agent may do freely.
- Tasks the agent may do and then notify.
- Tasks requiring explicit approval first.

## Output

- Reviewable `AGENTS.md` Markdown draft.

## Safety

- Make destructive actions and external communication “ask first” by default unless the user explicitly says otherwise.
- Do not include secrets or private credentials.
