# xiaohongshu-skills

小红书自动化 skill 包。它通过本项目的 Chrome 扩展和 `python scripts/cli.py` 操作使用者自己已登录的小红书账号。

## Skills

| Skill | Use it when | Main commands |
| --- | --- | --- |
| `xhs-auth` | 登录、检查登录状态、清除登录 | `check-login`, `get-qrcode`, `wait-login`, `send-code`, `verify-code`, `delete-cookies` |
| `xhs-explore` | 搜索、首页推荐、笔记详情、用户主页 | `search-feeds`, `list-feeds`, `get-feed-detail`, `user-profile` |
| `xhs-publish` | 图文、视频、长文发布或只填预览 | `fill-publish`, `fill-publish-video`, `publish`, `publish-video`, `click-publish`, `long-article` |
| `xhs-interact` | 评论、回复、点赞、收藏 | `post-comment`, `reply-comment`, `like-feed`, `favorite-feed` |
| `xhs-content-ops` | 竞品分析、热点追踪、创作发布、互动管理 | 组合调用搜索、详情、发布、互动命令 |
| `topic2feishu-xhs` | 小红书关键词采集、分析改写、写入飞书 Base | `topic2feishu` plus `lark-cli base` |

## Quick Start For AI

先读取根目录 `SKILL.md`，再按任务读取对应子 skill 的 `SKILL.md`。

示例提示词：

```text
使用 xiaohongshu-skills，检查我当前小红书登录状态。
```

```text
使用 xhs-explore，搜索“AI 教育”最近一周的图文笔记，按最多点赞排序，整理前 5 条。
```

```text
使用 topic2feishu-xhs，搜索关键词“AI for science”，采集 5 条笔记，分析改写后写入我提供的飞书 Base。
```

## Setup

前置条件：

- Python 3.11 或更高版本。
- `uv`。
- Google Chrome。
- 已加载本项目 `extension/` 目录下的 XHS Bridge 扩展。
- 使用者自己的小红书账号已在 Chrome 中登录。
- 如需写入飞书 Base，使用官方 `lark-cli` 配置自己的 profile。

初始化：

```bash
uv sync
python scripts/cli.py check-login
```

验证飞书 Base 权限：

```bash
lark-cli --profile "<profile-name>" base +field-list \
  --base-token "<base-token>" \
  --table-id "<table-id>" \
  --as user
```

## CLI Boundary

所有小红书操作只能通过：

```bash
python scripts/cli.py <subcommand>
```

不要混用其他 MCP、小红书第三方工具、Go CLI 或历史项目脚本。

## Safety

- 发布和评论必须经过用户明确确认。
- 批量搜索、详情抓取、点赞、收藏、评论都要控制频率。
- 不迁移 cookies、token、Chrome profile、`.lark-cli` profile 或 app secret。
- CLI 输出中的账号和内容信息只用于当前任务，不写入公开 README 或提交记录。
