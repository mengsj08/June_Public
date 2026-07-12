"""WorkBuddy adapter using native config discovery and optional CLI toggle."""
from __future__ import annotations
import json, os, subprocess, time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from .capabilities import capability
from .local_ecosystem import LocalSkillRecord, read_json, skill_records, state_payload

STAMP="2026-07-12T00:00:00+08:00"; REF="evidence/workbuddy-isolated-smoke.json"
class WorkBuddyAdapterError(RuntimeError): pass
class WorkBuddyAdapter:
    ecosystem="workbuddy"
    CAPABILITIES={name:capability(level,REF,STAMP) for name,level in {"discover":"native","read_state":"native","set_enabled":"verified_fallback","install":"unknown","uninstall":"unknown","publish":"unsupported","refresh_events":"unknown","resolve_plugin_parent":"native"}.items()}
    def __init__(self, home:Path|str|None=None, cli:str|None=None, node_bin:str|None=None, timeout:float=15, runner:Callable[...,subprocess.CompletedProcess[str]]=subprocess.run)->None:
        self.home=Path(home or os.environ.get("WORKBUDDY_CONFIG_DIR","~/.workbuddy")).expanduser(); self.cli=cli or os.environ.get("WORKBUDDY_CLI","codebuddy"); self.node_bin=node_bin or os.environ.get("WORKBUDDY_NODE"); self.timeout=timeout; self.runner=runner
    def _enabled(self)->dict[str,bool]:
        value=read_json(self.home/"settings.json").get("enabledPlugins",{}); return {str(k):bool(v) for k,v in value.items()} if isinstance(value,dict) else {}
    def _run(self,args:list[str])->subprocess.CompletedProcess[str]:
        command=([self.node_bin,self.cli] if self.node_bin else [self.cli])+args; env=dict(os.environ); env.update(WORKBUDDY_CONFIG_DIR=str(self.home),CODEBUDDY_CONFIG_DIR=str(self.home))
        try:return self.runner(command,capture_output=True,text=True,timeout=self.timeout,env=env)
        except (OSError,subprocess.TimeoutExpired) as exc:raise WorkBuddyAdapterError(f"WorkBuddy CLI failed: {exc}") from exc
    def discover(self,context_roots:list[str]|None=None)->list[LocalSkillRecord]:
        roots=[(self.home/"skills","user","native-config"),(self.home/"skills-marketplace"/"skills","marketplace","native-config"),(self.home/"connectors"/"skills","connector","native-config")]; enabled=self._enabled(); records=skill_records(self.ecosystem,roots)
        output=[]
        for row in records:
            meta=read_json(Path(row.path)/"_skillhub_meta.json"); plugin=meta.get("pluginName") or meta.get("plugin"); market=meta.get("marketplaceName") or meta.get("marketplace"); parent=f"{plugin}@{market}" if plugin and market else None
            output.append(replace(row,native_parent_id=parent,actual_state="enabled" if enabled.get(parent or "") is True else "disabled" if enabled.get(parent or "") is False else "unknown"))
        return output
    def read_state(self,native_id:str|None=None,context_roots:list[str]|None=None)->dict[str,Any]:
        payload=state_payload(self.ecosystem,self.discover(context_roots),self.CAPABILITIES); enabled=self._enabled(); payload["enabledPlugins"]=enabled
        if native_id:payload.update(native_id=native_id,actual_state="enabled" if enabled.get(native_id) is True else "disabled" if enabled.get(native_id) is False else "unknown",actual_state_source="native-config")
        return payload
    def set_enabled(self,native_id:str,enabled:bool,scope:str="user")->dict[str,Any]:
        before=self._enabled()
        if native_id not in before:raise WorkBuddyAdapterError(f"native WorkBuddy plugin not found: {native_id}")
        old=before[native_id]
        if old==enabled:return self._receipt(native_id,scope,old,enabled,False)
        result=self._run(["plugin","enable" if enabled else "disable",native_id,"-s",scope])
        if result.returncode:raise WorkBuddyAdapterError(result.stderr.strip() or "WorkBuddy toggle failed")
        if self._enabled().get(native_id)==enabled:return self._receipt(native_id,scope,old,enabled,True)
        raise WorkBuddyAdapterError(f"WorkBuddy enabled-state verification failed for {native_id}")
    @staticmethod
    def _receipt(native_id:str,scope:str,before:bool,after:bool,changed:bool)->dict[str,Any]:return {"ecosystem":"workbuddy","operation":"set_enabled","nativeId":native_id,"scope":scope,"before":{"enabled":before},"after":{"enabled":after},"changed":changed,"verification":"verified","completedAt":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
