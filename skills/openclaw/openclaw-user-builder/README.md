# openclaw-user-builder

Status: archived reference.

Guided interview for drafting `USER.md`, the profile that tells an agent who it serves and how to work with that person.

## When To Use

- The user wants the agent to remember their role, context, preferences, and constraints.
- The user already has agent behavior files but wants to add a user profile.
- The user wants to update an existing `USER.md`.

## Quick Start For AI

```text
Use openclaw-user-builder. First ask whether an existing USER.md exists; if not, ask the profile questions one at a time and draft USER.md.
```

## Inputs

- Name or preferred address.
- Role and active projects.
- Communication preferences.
- Annoyances, constraints, and personal preferences.

## Output

- Concise `USER.md` Markdown draft.

## Safety

- Keep it short and fact-based.
- Do not include sensitive identity data unless the user explicitly wants it and understands the risk.
- Do not include passwords, account tokens, or private customer data.
