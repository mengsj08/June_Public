# openclaw-onboarding-wizard

Status: archived reference.

One conversational setup wizard that drafts five OpenClaw workspace files: `USER.md`, `IDENTITY.md`, `SOUL.md`, `AGENTS.md`, and `HEARTBEAT.md`.

## When To Use

- A user wants a complete first-pass OpenClaw workspace configuration.
- The user prefers one guided interview instead of five separate setup flows.
- The AI should produce reviewable Markdown drafts, not silently install them.

## Quick Start For AI

```text
Use openclaw-onboarding-wizard. Start with Quick/Deep mode selection, ask one question at a time, then draft the five configuration files for review.
```

## Inputs

- User role and context.
- Preferred agent name and display style.
- Communication preferences and red lines.
- Permission boundaries.
- Proactive check or routine needs.

## Outputs

- `USER.md`
- `IDENTITY.md`
- `SOUL.md`
- `AGENTS.md`
- `HEARTBEAT.md`

## Safety

- Ask one question at a time.
- Keep drafts concise and reviewable.
- Do not include secrets or private account data.
