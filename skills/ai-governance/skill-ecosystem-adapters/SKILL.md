---
name: skill-ecosystem-adapters
description: 当用户询问某个 skill 在哪些工具中已安装、是否启用、如何安全启停，或需要跨工具盘点 skill 时使用。
---

# Skill Ecosystem Adapters

使用本目录中的 Python 包读取各工具的原生事实，不要把“发现了文件”当成“已启用”，也不要把运行状态当成长期采纳决定。

## 能力与事实源

| 生态 | 发现 | 读取启停状态 | 原生启停 | Adapter 与方法 | 事实源 |
| --- | --- | --- | --- | --- | --- |
| Codex | 支持 | 支持 | 支持 | `CodexAdapter.discover()`、`read_state()`、`set_enabled()` | Codex App Server 的 `skills/list` 与 `skills/config/write`；位置由 `CODEX_HOME` 或构造参数指定 |
| Claude | 支持 | 支持 | 支持（插件） | `ClaudeAdapter.discover()`、`read_state()`、`set_enabled()` | `claude plugin list --json`、带 scope 的插件命令、`CLAUDE_CONFIG_DIR` 下的 settings；独立目录 skill 仅作发现 fallback |
| WorkBuddy | 支持 | 支持 | 未验证，不得使用 | `WorkBuddyAdapter.discover()`、`read_state()` | `WORKBUDDY_CONFIG_DIR` 下的 `settings.json`、`_skillhub_meta.json` 与配置的原生 CLI |
| BigApple | 支持 | 支持（只读） | 不支持 | `BigAppleAdapter.discover()`、`read_state()` | `BIGAPPLE_HOME` 下的本地包 |
| 其他工具（Cursor、Windsurf、自研工具等） | 支持（文件盘点） | 仅存在性与 scope | 不支持 | `GenericAdapter.discover()`、`read_state()` | 构造时显式传入的目录；不推断原生启停状态 |

## 使用剧本

### 1. 跨生态盘点

逐个 adapter 执行 `discover()`，再以每条记录的原生标识执行 `read_state()`；保留生态、原生 ID、scope、状态来源和观测结果，最后汇总成表格。某生态不可用时标为 stale 或 unavailable，不要猜测绿色状态。

```python
from skill_ecosystem_adapters import (
    BigAppleAdapter, ClaudeAdapter, CodexAdapter, WorkBuddyAdapter,
)

adapters = {
    "codex": CodexAdapter(),
    "claude": ClaudeAdapter(),
    "workbuddy": WorkBuddyAdapter(),
    "bigapple": BigAppleAdapter(),
}

rows = []
for ecosystem, adapter in adapters.items():
    try:
        for record in adapter.discover([]):
            native_id = getattr(record, "native_id", None) or getattr(record, "name", None)
            rows.append({
                "ecosystem": ecosystem,
                "native_id": native_id,
                "state": adapter.read_state(native_id, []),
            })
    except Exception as error:
        rows.append({"ecosystem": ecosystem, "status": "unavailable", "error": str(error)})

print("| ecosystem | native_id | state |")
print("| --- | --- | --- |")
for row in rows:
    print(f"| {row['ecosystem']} | {row.get('native_id', '')} | {row.get('state', row.get('status'))} |")
```

### 2. 安全启停

启停会改变工具的运行状态，执行前必须提醒用户并取得当前任务授权。仅操作 Codex 或 Claude；严格按“先读 → 写入 → 回读核验”执行，并保存返回 receipt。不要调用 WorkBuddy 或 BigApple 的写能力。

```python
from skill_ecosystem_adapters import ClaudeAdapter, CodexAdapter

# Codex：name 必填；同名 skill 有多个路径时同时传 path。
adapter = CodexAdapter()
before = adapter.read_state("example-skill", [])
receipt = adapter.set_enabled("example-skill", False, context_roots=[])
after = adapter.read_state("example-skill", [])
assert after != before or receipt["changed"] is False

# Claude：native_id 应为插件的原生 ID，scope 明确写出。
claude = ClaudeAdapter()
before = claude.read_state("example-plugin", [])
receipt = claude.set_enabled("example-plugin", True, scope="user")
after = claude.read_state("example-plugin", [])
assert after != before or receipt["changed"] is False
```

### 3. 隔离验证

真实 home 之外先验证。`scripts/` 中的冒烟脚本会建立临时 home，并执行“发现 → 修改 → 重读”；只有显式传入 CLI 时才运行真实 CLI。

```bash
cd packages/skill-ecosystem-adapters
python3 scripts/codex_smoke.py --codex-bin codex
python3 scripts/claude_smoke.py --claude-bin claude
python3 scripts/workbuddy_smoke.py --workbuddy-cli codebuddy
```

也可在 Python 中显式使用临时 home：

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from skill_ecosystem_adapters import BigAppleAdapter

with TemporaryDirectory() as temporary_home:
    home = Path(temporary_home)
    adapter = BigAppleAdapter(home=home)
    assert adapter.discover([]) == []
```

### 4. 漂移检查与换机对账

意图文件是 `{"生态/原生-id": "default|on-demand|disabled"}`。缺失观测会报告为 `missing`，不会猜测状态。

```python
import json
from skill_ecosystem_adapters.intent import diff_observations, drift, export_observations, load_intent

current = export_observations(adapters)
print(drift(load_intent("intent.json"), current))

old = json.loads(open("old-observations.json", encoding="utf-8").read())
print(diff_observations(old, current))  # added / removed / changed
```

### 5. 接入你自己的工具

没有专用 adapter 时，用三行代码做如实的文件盘点。以下 Cursor 路径只是通用占位示例，应替换成工具文档或本机配置确认过的根目录。

```python
from skill_ecosystem_adapters import GenericAdapter
adapter = GenericAdapter("cursor", [("~/.cursor/skills", "user", "configured skill root")])
print(adapter.discover())
```

## 边界

- BigApple `publish` 是真实对外发布动作，本 skill 永不代做。
- WorkBuddy 写能力尚未验证；只允许发现和读取，不得启停。
- GenericAdapter 只报告文件存在性与 scope，不代表目标工具已经发现或启用；它没有原生控制面。
- 永不读取、复制或展示凭据文件。只读取上表列出的运行状态事实源。
- 不替用户决定长期采纳、发布、安装或删除；adapter 只报告或在明确授权后调整原生运行状态。
