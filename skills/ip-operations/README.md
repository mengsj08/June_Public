# IP Operations Skills

面向内容运营、IP 运营和多平台分发的公开 skill 集合。

## Skills

| Skill | When to use | Main output |
| --- | --- | --- |
| `xiaohongshu-skills/` | 需要操作小红书账号：登录、搜索、详情、发布、互动、采集入库 | 浏览器自动化操作结果、JSON、飞书 Base 记录 |
| `article-visualization/` | 需要把文章、研究博客或论文重新设计成外行可读的科普图文 | 科普长图、小红书卡片、公众号封面、短文素材 |

## How To Use

把需要的 skill 目录放入目标 AI 工具的 skills 目录，然后让 AI 读取对应目录下的 `SKILL.md`。

示例提示词：

```text
使用 xiaohongshu-skills，帮我搜索“小红书 AI 教育”相关笔记，整理 5 条高互动内容的选题结构。
```

```text
使用 article-visualization，把这篇论文做成给外行看懂的小红书图文卡和公众号封面。先给我 Page Plan，不要直接渲染。
```

## Account And Secret Boundary

这些公开副本只包含代码和说明，不包含账号状态：

- 不包含 Chrome profile、cookies、登录态。
- 不包含 `.lark-cli` profile、飞书 token、app secret。
- 不包含本地采集结果、发布草稿、运行缓存。
- 不包含真实 case 运行目录、下载图片、未发布截图或客户/内部素材。

每个使用者必须在自己的机器上连接自己的小红书账号、浏览器扩展和 Feishu/Lark CLI profile。
