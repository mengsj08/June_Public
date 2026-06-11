# workbuddy-team-sync-reporter

把团队成员自己的 Mac 配成一个轻量 WorkBuddy 日报执行站：同步用户指定的 GitHub 仓库，运行本机 Feishu/Wiki 导出命令，生成“谁做了什么”的中文日报，并在测试确认后交给 WorkBuddy 每天发送。

## When To Use

| Scenario | Use this skill |
| --- | --- |
| 团队想让某台成员电脑每天拉取 GitHub 和 Feishu/Wiki 变化 | Yes |
| 需要先生成本地审阅稿，再决定是否发送到飞书群 | Yes |
| 想把日报格式交给 WorkBuddy prompt 反复调试 | Yes |
| 只想保存真实 webhook、token、cookie 或飞书文档 token | No |

## What It Installs

- `scripts/team_sync_reporter.py`：负责 `init`、`doctor`、`sync`、`run`、`send` 和 `workbuddy-prompt`。
- `assets/config.example.json`：本地配置模板。
- `assets/feishu-message-prompt.md`：最终飞书消息的可编辑 prompt。
- `assets/workbuddy-daily-prompt.md`：WorkBuddy 每日任务提示词模板。
- `references/configuration.md`：配置项和安全边界说明。

## Example Prompts

```text
使用 workbuddy-team-sync-reporter，在这台电脑上初始化 TeamSpace。仓库名是 <local-repo-name>，GitHub 地址是 <repo-url>。只做本地配置，不发送消息。
```

```text
使用 workbuddy-team-sync-reporter，读取 TeamSpace 配置，运行 doctor，然后生成昨天的本地日报草稿。
```

```text
使用 workbuddy-team-sync-reporter，基于已有草稿生成 WorkBuddy 每日自动化 prompt。确认测试群成功前不要启用正式发送。
```

## Safety Boundary

公开仓库只保存模板和脚本。真实配置必须留在使用者本机：

- GitHub 仓库名和仓库地址必须由使用者提供。
- Feishu/Wiki 导出命令必须在本机配置和测试。
- Webhook、sign secret、app secret、cookie、token、chat id、`.env` 内容不能写进 skill、README、报告或聊天。
- 第一次全量同步数量不能被写成当天 Feishu/Wiki 源新增。

更多配置细节见 [`references/configuration.md`](references/configuration.md)。
