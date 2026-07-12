"""Codex App Server adapter with configurable binary and isolated home."""
from __future__ import annotations
import json, os, queue, subprocess, threading, time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from .capabilities import capability

STAMP="2026-07-12T00:00:00+08:00"; REF="evidence/codex-isolated-smoke.json"
class CodexAdapterError(RuntimeError): pass

@dataclass(frozen=True)
class NativeSkillRecord:
    name:str; path:str; enabled:bool; scope:str; description:str=""; native_parent_id:str|None=None
    def as_dict(self)->dict[str,Any]:return asdict(self)

class AppServerClient:
    def __init__(self,codex_bin:str|None=None,codex_home:Path|str|None=None,timeout:float=15)->None:
        self.codex_bin=codex_bin or os.environ.get("CODEX_BIN","codex"); raw=codex_home or os.environ.get("CODEX_HOME"); self.codex_home=Path(raw).expanduser() if raw else None; self.timeout=timeout; self._next=1; self._responses:queue.Queue[dict[str,Any]]=queue.Queue(); self._notifications:queue.Queue[dict[str,Any]]=queue.Queue(); self._process:subprocess.Popen[str]|None=None
    def __enter__(self)->"AppServerClient":
        env=dict(os.environ)
        if self.codex_home:env["CODEX_HOME"]=str(self.codex_home)
        try:self._process=subprocess.Popen([self.codex_bin,"app-server","--stdio"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,env=env)
        except OSError as exc:raise CodexAdapterError(f"cannot start Codex App Server: {exc}") from exc
        threading.Thread(target=self._read,daemon=True).start(); self.request("initialize",{"clientInfo":{"name":"skill-ecosystem-adapters","version":"1"}}); return self
    def __exit__(self,*_:object)->None:
        if self._process:self._process.terminate(); self._process.wait(timeout=3)
    def _read(self)->None:
        if not self._process or not self._process.stdout:return
        for line in self._process.stdout:
            try:message=json.loads(line)
            except json.JSONDecodeError:continue
            if isinstance(message,dict):(self._responses if "id" in message else self._notifications).put(message)
    def request(self,method:str,params:dict[str,Any])->dict[str,Any]:
        if not self._process or not self._process.stdin:raise CodexAdapterError("App Server is not running")
        request_id=self._next; self._next+=1; self._process.stdin.write(json.dumps({"id":request_id,"method":method,"params":params})+"\n"); self._process.stdin.flush(); deadline=time.monotonic()+self.timeout
        while time.monotonic()<deadline:
            try:message=self._responses.get(timeout=max(.05,deadline-time.monotonic()))
            except queue.Empty as exc:raise CodexAdapterError(f"request timed out: {method}") from exc
            if message.get("id")==request_id:
                if message.get("error"):raise CodexAdapterError(f"{method} failed: {message['error']}")
                return message
        raise CodexAdapterError(f"request timed out: {method}")
    def poll_notifications(self,timeout:float=0)->list[dict[str,Any]]:
        found=[]; deadline=time.monotonic()+timeout
        while True:
            try:found.append(self._notifications.get(timeout=max(0,deadline-time.monotonic()) if not found else 0))
            except queue.Empty:return found

class CodexAdapter:
    ecosystem="codex"
    CAPABILITIES={name:capability(level,REF,STAMP if level!="unknown" else None) for name,level in {"discover":"native","read_state":"native","set_enabled":"native","refresh_events":"unknown","resolve_plugin_parent":"unsupported","install":"unknown","uninstall":"unknown","publish":"unsupported"}.items()}
    def __init__(self,client_factory:Callable[[],Any]|None=None,codex_bin:str|None=None,codex_home:Path|str|None=None)->None:
        self.client_factory=client_factory or (lambda:AppServerClient(codex_bin,codex_home))
    def discover(self,context_roots:list[str]|None=None,force_reload:bool=True)->list[NativeSkillRecord]:
        with self.client_factory() as client:response=client.request("skills/list",{"cwds":context_roots or [],"forceReload":force_reload})
        records=[]
        for group in response.get("result",{}).get("data",[]):
            for row in group.get("skills",[]):
                if row.get("name") and row.get("path"):
                    path=Path(str(row["path"])).expanduser(); path=path.parent if path.name.lower()=="skill.md" else path
                    records.append(NativeSkillRecord(str(row["name"]),str(path),bool(row.get("enabled",True)),str(row.get("scope") or "unknown"),str(row.get("description") or "")))
        return records
    def read_state(self,native_id:str,context_roots:list[str]|None=None)->dict[str,Any]:
        row=next((x for x in self.discover(context_roots) if x.name==native_id),None); return {"ecosystem":self.ecosystem,"native_id":native_id,"actual_state":"enabled" if row and row.enabled else "disabled" if row else "unknown","actual_state_source":"native-api" if row else "native-api-unmatched","capabilities":self.CAPABILITIES}
    def set_enabled(self,name:str,enabled:bool,path:str|None=None,context_roots:list[str]|None=None)->dict[str,Any]:
        before=next((x for x in self.discover(context_roots) if x.name==name and (not path or Path(x.path).resolve()==Path(path).expanduser().resolve())),None)
        if before is None:raise CodexAdapterError(f"native Codex skill not found: {name}")
        if before.enabled==enabled:return self._receipt(name,path,before.enabled,enabled,False)
        with self.client_factory() as client:client.request("skills/config/write",{"name":name,"path":path,"enabled":enabled})
        after=next((x for x in self.discover(context_roots) if x.name==name),None)
        if after and after.enabled==enabled:return self._receipt(name,path,before.enabled,enabled,True)
        raise CodexAdapterError(f"Codex enabled-state verification failed for {name}")
    @staticmethod
    def _receipt(name:str,path:str|None,before:bool,after:bool,changed:bool)->dict[str,Any]:return {"ecosystem":"codex","operation":"set_enabled","nativeId":{"name":name,"path":path},"before":{"enabled":before},"after":{"enabled":after},"changed":changed,"verification":"verified","completedAt":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
