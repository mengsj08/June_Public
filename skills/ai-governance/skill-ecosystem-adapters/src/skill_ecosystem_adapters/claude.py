"""Claude adapter using the native plugin CLI and isolated config home."""
from __future__ import annotations
import json, os, subprocess, time
from pathlib import Path
from typing import Any, Callable
from .capabilities import capability
from .local_ecosystem import LocalSkillRecord, read_json, skill_records, state_payload

STAMP = "2026-07-12T00:00:00+08:00"
REF = "evidence/claude-isolated-smoke.json"

class ClaudeAdapterError(RuntimeError): pass

class ClaudeAdapter:
    ecosystem = "claude"
    CAPABILITIES = {name: capability(level, REF, STAMP) for name, level in {
        "discover":"native", "read_state":"native", "set_enabled":"native",
        "install":"unknown", "uninstall":"unknown", "publish":"unsupported",
        "refresh_events":"unsupported", "resolve_plugin_parent":"native"}.items()}

    def __init__(self, home: Path | str | None = None, claude_bin: str | None = None, timeout: float = 10,
                 runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.home = Path(home or os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser()
        self.claude_bin = claude_bin or os.environ.get("CLAUDE_BIN", "claude")
        self.timeout, self.runner = timeout, runner

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ); env["CLAUDE_CONFIG_DIR"] = str(self.home)
        try: return self.runner([self.claude_bin, *args], capture_output=True, text=True, timeout=self.timeout, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc: raise ClaudeAdapterError(f"Claude CLI failed: {exc}") from exc

    def _plugins(self) -> list[dict[str, Any]]:
        result = self._run(["plugin", "list", "--json"])
        if result.returncode: raise ClaudeAdapterError(result.stderr.strip() or "claude plugin list failed")
        try: value = json.loads(result.stdout)
        except json.JSONDecodeError as exc: raise ClaudeAdapterError("claude plugin list returned invalid JSON") from exc
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def discover(self, context_roots: list[str] | None = None) -> list[LocalSkillRecord]:
        roots = [(self.home/"skills", "user", "filesystem-fallback")]
        roots += [(Path(root)/".claude"/"skills", "project", "filesystem-fallback") for root in context_roots or []]
        records = skill_records(self.ecosystem, roots)
        for plugin in self._plugins():
            if plugin.get("id") and plugin.get("installPath"):
                records.append(LocalSkillRecord(str(plugin["id"]).split("@",1)[0], str(Path(plugin["installPath"]).expanduser()), str(plugin.get("scope") or "unknown"), "enabled" if plugin.get("enabled") is not False else "disabled", "native-cli", str(plugin["id"]), self.ecosystem))
        return records

    def read_state(self, native_id: str | None = None, context_roots: list[str] | None = None) -> dict[str, Any]:
        plugins = self._plugins(); matched = next((x for x in plugins if x.get("id") == native_id), None)
        payload = state_payload(self.ecosystem, self.discover(context_roots), self.CAPABILITIES)
        payload["settingsSource"] = "native-config"; payload["enabledPlugins"] = read_json(self.home/"settings.json").get("enabledPlugins", {})
        if native_id: payload.update(native_id=native_id, actual_state=("enabled" if matched and matched.get("enabled") is not False else "disabled" if matched else "unknown"), actual_state_source="native-cli" if matched else "native-cli-unmatched")
        return payload

    def set_enabled(self, native_id: str, enabled: bool, scope: str = "user") -> dict[str, Any]:
        before = next((x for x in self._plugins() if x.get("id") == native_id), None)
        if before is None: raise ClaudeAdapterError(f"native Claude plugin not found: {native_id}")
        old = before.get("enabled") is not False
        if old == enabled: return self._receipt(native_id, scope, old, enabled, False)
        result = self._run(["plugin", "enable" if enabled else "disable", native_id, "--scope", scope])
        if result.returncode: raise ClaudeAdapterError(result.stderr.strip() or "Claude toggle failed")
        after = next((x for x in self._plugins() if x.get("id") == native_id), None)
        if after is not None and (after.get("enabled") is not False) == enabled: return self._receipt(native_id, scope, old, enabled, True)
        raise ClaudeAdapterError(f"Claude enabled-state verification failed for {native_id}")

    @staticmethod
    def _receipt(native_id: str, scope: str, before: bool, after: bool, changed: bool) -> dict[str, Any]:
        return {"ecosystem":"claude", "operation":"set_enabled", "nativeId":native_id, "scope":scope, "before":{"enabled":before}, "after":{"enabled":after}, "changed":changed, "verification":"verified", "completedAt":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
