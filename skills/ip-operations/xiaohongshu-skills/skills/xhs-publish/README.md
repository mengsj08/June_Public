# xhs-publish

小红书内容发布 skill，支持图文、视频、长文和分步预览发布。

## When To Use

- 用户要发布小红书图文笔记。
- 用户要发布小红书视频笔记。
- 用户要填写发布页但先不发布。
- 用户要发布长文并选择排版模板。

## Quick Start For AI

推荐分步发布：先填表单，让用户在浏览器里确认，再点击发布。

```text
使用 xhs-publish，把这篇内容填写到小红书发布页，但先不要发布，等我确认。
```

```text
使用 xhs-publish，发布这条图文笔记。标题、正文和图片如下，发布前先让我确认最终预览。
```

## Commands

```bash
python scripts/cli.py fill-publish \
  --title-file /abs/path/title.txt \
  --content-file /abs/path/content.txt \
  --images "/abs/path/image1.jpg" "/abs/path/image2.jpg"

python scripts/cli.py click-publish
```

视频：

```bash
python scripts/cli.py fill-publish-video \
  --title-file /abs/path/title.txt \
  --content-file /abs/path/content.txt \
  --video "/abs/path/video.mp4"
```

## Inputs

- 标题。
- 正文。
- 图片绝对路径或图片 URL，图文发布必需。
- 视频绝对路径，视频发布必需。
- 可选：标签、定时发布时间、可见性、原创标记。

## Rules

- 发布前必须让用户确认标题、正文和图片或视频。
- 用户只要求“预览、填好、不发布”时，只能运行 `fill-*`，不能运行 `click-publish`。
- 图文和视频不可混合。
- 标题长度按 `SKILL.md` 的 UTF-16 规则控制在 20 单位以内。
- 需要确认创作服务平台登录状态，不只看社区登录状态。

## Safety

- 控制发布频率。
- 不使用相对路径。
- 不手动下载图片 URL，脚本会处理 URL 图片。
- 不使用本项目外的小红书发布工具。
