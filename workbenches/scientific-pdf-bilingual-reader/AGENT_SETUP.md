# Agent-assisted setup

This is the installation entry point for a local coding agent such as Codex or Claude.
It is not a replacement for [`SKILL.md`](SKILL.md). Read that file completely before
installing or starting the workbench.

## Objective

Prepare and start the Scientific PDF Bilingual Reader on the user's Mac, using the
repository's managed runtime and the user's existing Codex or Claude CLI login. The user
should not need to copy commands manually.

## Required reading order

1. This file.
2. [`SKILL.md`](SKILL.md) for runtime behavior and safety boundaries.
3. [`references/distribution.md`](references/distribution.md) for installation locations,
   download sizes and pinned dependencies.
4. [`references/acceptance.md`](references/acceptance.md) only when performing product or
   release acceptance beyond ordinary installation.

Run all relative commands from the directory containing this file.

## Preconditions

- Supported release target: macOS; Apple Silicon is the verified platform.
- The bootstrap command requires `python3` 3.10 or newer. The application runtime itself is
  an isolated, managed Python 3.12 environment.
- At least one of `codex` or `claude` must be available on `PATH` and already usable through
  the user's normal local login. Do not request an API key or inspect authentication files.
- Initial translation-runtime installation needs network access and about 1.0–1.3 GB of
  persistent disk space. OCR is a separate, deferred installation of about 1–2 GB.

If a precondition is missing, report the exact missing item and stop. Do not use `sudo`,
modify shell startup files, install into system Python, or work around provider login by
reading credentials.

## Installation flow

### 1. Read-only preflight

```bash
uname -s
uname -m
python3 --version
command -v codex || true
command -v claude || true
python3 scripts/bootstrap.py doctor
```

`doctor` returning `ready: false` on a new machine is expected. Explain the reported gap to
the user. Before a large download, state the expected persistent disk use and obtain an
explicit confirmation.

### 2. Choose the installation shape

Direct use from the clone is the default and does not require copying the package into an AI
tool's Skill directory. Provision only the shared runtime:

```bash
python3 scripts/bootstrap.py install --yes
```

If the user explicitly wants the package registered for future Skill discovery, select only
the ecosystem they use:

```bash
python3 scripts/setup.py --targets codex --yes
python3 scripts/setup.py --targets claude --yes
python3 scripts/setup.py --targets both --yes
```

Run only one of those `setup.py` commands. If the selected destination already exists, stop
and compare it with this package. Never add `--force` merely to make installation succeed;
use it only after the user has reviewed the difference and explicitly approved the backed-up
replacement.

### 3. Verify and start

```bash
python3 scripts/bootstrap.py doctor
python3 scripts/launch.py start --open
```

Keep the server process alive. The launcher prints the actual loopback URL; it normally uses
`127.0.0.1:8765` and automatically falls back to `8876`–`8895` when needed. Do not bind to a
public interface.

After startup, request `GET /api/health` from the printed URL and verify:

- `pdf2zh` is present;
- the server is running under the managed Python environment;
- at least the user's chosen provider is detected;
- the URL remains on `127.0.0.1` or `localhost`.

Report the actual URL, selected provider, runtime-doctor result and any remaining warning.
A successful install command alone is not completion.

## Deferred OCR rule

Do not install PaddleOCR during ordinary setup. Only when an uploaded PDF is classified as
containing OCR pages may the workbench or agent explain the additional 1–2 GB requirement and
ask for confirmation. After approval, use:

```bash
python3 scripts/bootstrap.py ocr-install --yes
python3 scripts/bootstrap.py ocr-doctor --check-assets
```

Cancelling OCR installation must leave the task recoverable and must not damage the normal
text-PDF runtime.

## User prompt

The user can hand this repository to an agent with:

> Read `AGENT_SETUP.md` completely, then inspect, install and start the workbench for me.
> Perform safe checks yourself. Ask before large downloads, replacing an existing Skill, or
> installing OCR. Do not read credentials or expose my PDFs.
