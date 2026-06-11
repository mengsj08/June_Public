# Team Operations Skills

面向团队协作、日报同步、执行站配置和轻量运营自动化的公开 skill 集合。

## Skills

| Skill | When to use | Main output |
| --- | --- | --- |
| `workbuddy-team-sync-reporter/` | 需要把团队成员的 Mac 配成 WorkBuddy 日报执行站，同步指定 GitHub 仓库和 Feishu/Wiki 变更 | 本地 TeamSpace 控制层、可审阅日报草稿、WorkBuddy 自动化提示词、测试发送流程 |

## Quick Start

示例提示词：

```text
使用 workbuddy-team-sync-reporter，帮我在这台电脑上配置团队同步日报。仓库名和 GitHub 地址由我提供，先跑 doctor 和本地 draft，不要直接发正式群。
```

```text
使用 workbuddy-team-sync-reporter，检查当前 TeamSpace 配置是否可以生成 WorkBuddy 每日同步 prompt。
```

## Account And Secret Boundary

这些公开副本只包含代码和说明，不包含账号状态或凭据：

- 不包含 GitHub token、Feishu bot webhook、sign secret、app secret。
- 不包含 WorkBuddy trace、运行日志、团队日报生成结果。
- 不包含真实仓库地址、真实飞书文档 token、真实群聊信息。

每个使用者必须在自己的机器上配置自己的 GitHub 登录、Feishu/Wiki 导出命令、飞书机器人和本地环境变量。
