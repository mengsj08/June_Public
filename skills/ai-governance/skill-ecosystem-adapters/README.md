# Skill Ecosystem Adapters

A self-contained, standard-library-only Python package for observing and controlling skill deployments without confusing assets, runtime state, and test evidence.

This package is also an installable skill; see `SKILL.md` for AI-assistant usage guidance and safety boundaries.

```python
from skill_ecosystem_adapters import BigAppleAdapter

adapter = BigAppleAdapter(home="./fixtures/bigapple-home")
for record in adapter.discover([]):
    print(record.name, record.actual_state_source)
```

For a source checkout without installation, set `PYTHONPATH=src` or install it into a virtual environment with `python3 -m pip install -e .`.

## Capability levels

| Level | Contract |
| --- | --- |
| `native` | Native API, CLI, config, or event source |
| `verified_fallback` | Non-native operation verified in isolation |
| `read_only` | Reliable observation, no mutation |
| `unsupported` | Not provided or intentionally forbidden |
| `unknown` | Not verified; callers must not assume support |

Every capability entry includes `verified_at` and `evidence_ref`. The references are portable receipt identifiers; consumers decide where receipts are stored.

## Native fact sources

- **Codex:** App Server `skills/list` and `skills/config/write`. Configure with constructor arguments or `CODEX_BIN` / `CODEX_HOME`.
- **Claude:** `claude plugin list --json`, scoped plugin commands, and settings under `CLAUDE_CONFIG_DIR` (default `~/.claude`). Standalone filesystem skills are discovery fallbacks, not native toggle targets.
- **WorkBuddy:** `settings.json`, `_skillhub_meta.json`, and the configured native CLI. Use `WORKBUDDY_CONFIG_DIR`, `WORKBUDDY_CLI`, and optionally `WORKBUDDY_NODE`.
- **BigApple:** local packages under `BIGAPPLE_HOME` (default `~/.bigapple`). This adapter is read-only and never publishes.
- **Other tools:** `GenericAdapter` scans explicitly configured filesystem roots. It reports only existence and scope; it has no native enable, install, uninstall, or publish control surface.

## Connect your own tool

Use the generic adapter for Cursor, Windsurf, or an internal tool that does not have a dedicated adapter. The paths below are placeholders; replace them with roots documented by your tool.

```python
from skill_ecosystem_adapters import GenericAdapter
adapter = GenericAdapter("cursor", [("~/.cursor/skills", "user", "configured skill root")])
print(adapter.discover())
```

## Drift checks and machine-to-machine comparison

Keep desired exposure in a small JSON file, export current observations, and compare them without guessing about missing records:

```python
from skill_ecosystem_adapters.intent import drift, export_observations, load_intent

observations = export_observations(adapters)
problems = drift(load_intent("intent.json"), observations)
```

For a migration, save the exported list on the old machine, export again on the new machine, then call `diff_observations(old, new)`. Its result separates `added`, `removed`, and `changed` records.

## Isolated verification

Never probe a real home when testing mutation. Point the ecosystem home variable at a temporary directory, create a fictional fixture, then perform discover → change → re-read. The scripts in `scripts/` accept explicit paths and only run a real CLI when invoked:

```bash
python3 scripts/claude_smoke.py --claude-bin claude
python3 scripts/codex_smoke.py --codex-bin codex
python3 scripts/workbuddy_smoke.py --workbuddy-cli codebuddy
```

Run unit tests independently:

```bash
python3 -m unittest discover
```

The `bigapple-listing/` directory contains offline listing materials only. Nothing in this package uploads or publishes.
