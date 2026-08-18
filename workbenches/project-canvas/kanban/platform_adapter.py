#!/usr/bin/env python3
"""Small platform boundary for optional desktop and OS integrations.

The public core calls this module instead of invoking macOS commands directly.
Darwin keeps the existing Finder/Terminal behavior, Linux uses xdg-open and a
detached child process, and unsupported capabilities fail closed with one
diagnostic log line instead of taking down the server.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


class PlatformAdapter:
    name = "unsupported"

    def __init__(self, logger=None):
        self._logger = logger or self._default_logger
        self._logged = set()

    @staticmethod
    def _default_logger(message):
        print(f"[platform] {message}", file=sys.stderr)

    def _log_once(self, key, message):
        if key in self._logged:
            return
        self._logged.add(key)
        self._logger(message)

    def log_degradation(self, key, message):
        """Expose a deduplicated degradation log to capability-gating callers."""
        self._log_once(key, message)

    def capabilities(self):
        return {
            "desktop_open": False,
            "process_launch": False,
            "app_bundle_control": False,
            "system_proxy": False,
        }

    def _unavailable(self, capability, detail=""):
        message = detail or f"{capability} is unavailable on {self.name}"
        self._log_once(capability, message)
        return False, message

    def open_path(self, target):
        return self._unavailable(
            "desktop_open",
            f"桌面打开在 {self.name} 上不可用；请直接访问或打开该路径",
        )

    def launch_command(self, command, cwd):
        return self._unavailable(
            "process_launch",
            f"本地工具启动在 {self.name} 上不可用；该入口已降级隐藏",
        )

    def quit_app_bundle(self, bundle_id):
        ok, error = self._unavailable(
            "app_bundle_control",
            f".app bundle 控制仅支持 macOS；当前平台为 {self.name}",
        )
        return {"ok": ok, "error": error}

    def open_app_bundle(self, bundle_id, app_path=""):
        ok, error = self._unavailable(
            "app_bundle_control",
            f".app bundle 控制仅支持 macOS；当前平台为 {self.name}",
        )
        return {"ok": ok, "error": error}

    def system_proxy_output(self):
        ok, error = self._unavailable(
            "system_proxy",
            f"macOS 系统代理读取在 {self.name} 上不可用",
        )
        return ok, "", error

    def network_services(self):
        self._unavailable(
            "system_proxy",
            f"macOS networksetup 在 {self.name} 上不可用",
        )
        return []

    def disable_system_proxy(self):
        ok, error = self._unavailable(
            "system_proxy",
            f"macOS networksetup 在 {self.name} 上不可用",
        )
        return {"ok": ok, "services": 0, "failures": [], "error": error}


class DarwinPlatformAdapter(PlatformAdapter):
    name = "darwin"
    OPEN_BIN = Path("/usr/bin/open")
    OSASCRIPT_BIN = Path("/usr/bin/osascript")
    SCUTIL_BIN = Path("/usr/sbin/scutil")

    def capabilities(self):
        return {
            "desktop_open": self.OPEN_BIN.is_file(),
            "process_launch": self.OSASCRIPT_BIN.is_file(),
            "app_bundle_control": self.OPEN_BIN.is_file() and self.OSASCRIPT_BIN.is_file(),
            "system_proxy": self.SCUTIL_BIN.is_file(),
        }

    def open_path(self, target):
        if not self.OPEN_BIN.is_file():
            return self._unavailable("desktop_open", "/usr/bin/open 不存在；桌面打开已禁用")
        try:
            subprocess.Popen([str(self.OPEN_BIN), str(target)])
        except Exception as exc:
            error = f"打开失败: {type(exc).__name__}"
            self._log_once("desktop_open_failed", error)
            return False, error
        return True, ""

    def launch_command(self, command, cwd):
        if not self.OSASCRIPT_BIN.is_file():
            return self._unavailable("process_launch", "/usr/bin/osascript 不存在；Terminal 启动已禁用")
        shell_command = f"cd {shlex.quote(str(cwd))} && {command}"
        script = (
            'tell application "Terminal"\n'
            "  activate\n"
            f"  do script {json.dumps(shell_command)}\n"
            "end tell\n"
        )
        try:
            proc = subprocess.Popen(
                [str(self.OSASCRIPT_BIN)],
                stdin=subprocess.PIPE,
                text=True,
            )
            proc.communicate(script)
        except OSError as exc:
            error = f"Terminal 启动失败: {type(exc).__name__}"
            self._log_once("process_launch_failed", error)
            return False, error
        if proc.returncode != 0:
            error = "Terminal 启动失败: osascript returned non-zero"
            self._log_once("process_launch_failed", error)
            return False, error
        return True, ""

    def quit_app_bundle(self, bundle_id):
        if not self.OSASCRIPT_BIN.is_file():
            ok, error = self._unavailable("app_bundle_control", "/usr/bin/osascript 不存在；.app 控制已禁用")
            return {"ok": ok, "error": error}
        try:
            proc = subprocess.run(
                [str(self.OSASCRIPT_BIN), "-e", f'tell application id "{bundle_id}" to quit'],
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}
        # Preserve the pre-adapter contract: launching osascript successfully is
        # reported as success even when the target app was already closed.
        return {"ok": True}

    def open_app_bundle(self, bundle_id, app_path=""):
        if not self.OPEN_BIN.is_file():
            ok, error = self._unavailable("app_bundle_control", "/usr/bin/open 不存在；.app 控制已禁用")
            return {"ok": ok, "error": error}
        commands = (
            [str(self.OPEN_BIN), "-b", bundle_id] if bundle_id else [],
            [str(self.OPEN_BIN), "-a", app_path] if app_path else [],
        )
        for command in commands:
            if not command:
                continue
            try:
                proc = subprocess.run(command, capture_output=True, text=True, timeout=8)
            except Exception:
                continue
            if proc.returncode == 0:
                return {"ok": True, "method": command[1]}
        return {"ok": False, "error": "open failed"}

    def system_proxy_output(self):
        if not self.SCUTIL_BIN.is_file():
            ok, error = self._unavailable("system_proxy", "/usr/sbin/scutil 不存在；系统代理读取已禁用")
            return ok, "", error
        try:
            proc = subprocess.run(
                [str(self.SCUTIL_BIN), "--proxy"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as exc:
            error = f"系统代理读取失败: {type(exc).__name__}"
            self._log_once("system_proxy_failed", error)
            return False, "", error
        if proc.returncode != 0:
            error = "系统代理读取失败: scutil returned non-zero"
            self._log_once("system_proxy_failed", error)
            return False, proc.stdout or "", error
        return True, proc.stdout or "", ""

    def network_services(self):
        networksetup = shutil.which("networksetup")
        if not networksetup:
            self._unavailable("system_proxy", "networksetup 不存在；系统代理变更已禁用")
            return []
        try:
            proc = subprocess.run(
                [networksetup, "-listallnetworkservices"],
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception:
            return []
        return [
            line.strip()
            for line in (proc.stdout or "").splitlines()[1:]
            if line.strip() and not line.strip().startswith("*")
        ]

    def disable_system_proxy(self):
        networksetup = shutil.which("networksetup")
        if not networksetup:
            ok, error = self._unavailable("system_proxy", "networksetup 不存在；系统代理变更已禁用")
            return {"ok": ok, "services": 0, "failures": [], "error": error}
        services = self.network_services()
        commands = (
            ("-setwebproxystate", "http"),
            ("-setsecurewebproxystate", "https"),
            ("-setsocksfirewallproxystate", "socks"),
        )
        failures = []
        for service in services:
            for flag, channel in commands:
                try:
                    proc = subprocess.run(
                        [networksetup, flag, service, "off"],
                        capture_output=True,
                        text=True,
                        timeout=8,
                    )
                except Exception as exc:
                    failures.append({"service": service, "channel": channel, "error": type(exc).__name__})
                    continue
                if proc.returncode != 0:
                    failures.append({"service": service, "channel": channel, "error": "networksetup failed"})
        return {"ok": not failures, "services": len(services), "failures": failures}


class LinuxPlatformAdapter(PlatformAdapter):
    name = "linux"

    def capabilities(self):
        return {
            "desktop_open": shutil.which("xdg-open") is not None,
            "process_launch": True,
            "app_bundle_control": False,
            "system_proxy": False,
        }

    def open_path(self, target):
        opener = shutil.which("xdg-open")
        if not opener:
            return self._unavailable("desktop_open", "xdg-open 不存在；桌面打开已禁用")
        try:
            subprocess.Popen([opener, str(target)])
        except Exception as exc:
            error = f"打开失败: {type(exc).__name__}"
            self._log_once("desktop_open_failed", error)
            return False, error
        return True, ""

    def launch_command(self, command, cwd):
        try:
            subprocess.Popen(
                command,
                cwd=str(cwd),
                shell=True,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            error = f"本地工具启动失败: {type(exc).__name__}"
            self._log_once("process_launch_failed", error)
            return False, error
        return True, ""


def get_platform_adapter(platform_name=None, logger=None):
    name = str(platform_name or sys.platform).lower()
    if name == "darwin":
        return DarwinPlatformAdapter(logger=logger)
    if name.startswith("linux"):
        return LinuxPlatformAdapter(logger=logger)
    adapter = PlatformAdapter(logger=logger)
    adapter.name = name or "unknown"
    return adapter
