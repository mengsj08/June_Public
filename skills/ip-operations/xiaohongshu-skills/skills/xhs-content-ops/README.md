# xhs-content-ops

小红书复合内容运营 skill，用于把搜索、详情分析、创作、发布、互动串成完整运营流程。

## When To Use

- 竞品分析：找爆款笔记并总结选题、标题、封面、正文结构。
- 热点追踪：按关键词跟踪近期热门内容。
- 内容创作：先研究同类内容，再生成草稿并发布。
- 互动管理：筛选目标笔记并制定评论、点赞、收藏策略。

## Quick Start For AI

示例提示词：

```text
使用 xhs-content-ops，分析“小红书 AI 教育”这个关键词下 5 条高互动图文笔记，总结选题和标题规律。
```

```text
使用 xhs-content-ops，先研究“企业 AI 培训”热门笔记，再帮我生成一条小红书草稿，发布前必须让我确认。
```

## Workflow

常见流程：

```text
确认目标 -> 搜索笔记 -> 读取详情 -> Markdown 表格分析 -> 生成建议 -> 用户确认 -> 可选发布或互动
```

## Commands Used

这个 skill 会组合调用：

- `search-feeds`
- `list-feeds`
- `get-feed-detail`
- `user-profile`
- `fill-publish` / `publish` / `click-publish`
- `post-comment` / `like-feed` / `favorite-feed`

全部命令仍必须通过：

```bash
python scripts/cli.py <subcommand>
```

## Output

- Markdown 表格分析。
- 选题建议、标题建议、内容结构建议。
- 可确认的发布草稿或互动建议。

## Safety

- 每一步向用户报告进度。
- 发布和评论必须用户确认。
- 控制搜索、详情读取和互动频率。
- 不混用外部小红书工具。
