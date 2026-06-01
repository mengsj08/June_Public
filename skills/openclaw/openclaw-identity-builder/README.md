# openclaw-identity-builder

Status: archived reference.

Guided interview for drafting `IDENTITY.md`, the display profile and presentation metadata for an OpenClaw agent.

## When To Use

- The user wants to name an agent.
- The user wants to define display style, tone, signature marker, or avatar.
- The user only wants to update `IDENTITY.md`.

## Quick Start For AI

```text
Use openclaw-identity-builder. Ask one question at a time, then draft IDENTITY.md for review.
```

## Inputs

- Agent name.
- Short self-description or essence.
- Tone and display style.
- Signature marker.
- Avatar path or URL.

## Output

```markdown
- Name: ...
- Essence: ...
- Vibe: ...
- Marker: ...
- Avatar: ...
```

## Safety

- Use workspace-relative avatar paths when possible.
- Do not download or embed private images without user approval.
- Do not apply settings to a live workspace until the user approves the draft.
