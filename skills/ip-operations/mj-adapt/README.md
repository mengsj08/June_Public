# mj-adapt

把已经完成的长文适配成多个发布平台可用的素材。它适合“文章已经写好，只需要分发适配”的场景，不负责重新选题或大幅改写原文。

## When To Use

- 把 Markdown 文章转成微信公众号可粘贴的 HTML。
- 把长文拆成小红书多页图文素材。
- 同一篇文章需要保持统一视觉风格后发布到多个平台。

不适合：

- 从零创作文章。
- 未经用户确认就压缩、改写或改变原文观点。
- 自动登录或发布到任何平台。

## Quick Start For AI

先读取本目录的 `SKILL.md`，再按用户目标选择输出。

示例提示词：

```text
使用 mj-adapt，把 /abs/path/article.md 适配成微信公众号 HTML 和小红书图片素材。保持原文观点，不要擅自删改。
```

```text
使用 mj-adapt，只生成小红书多页图文素材，输出到 /abs/path/output。
```

## Inputs

- 一篇完整 Markdown 文章，或用户直接粘贴的完整正文。
- 可选：输出目录、目标平台、slug、日期。
- 可选：小红书图文希望强调的标题和封面重点。

## Outputs

常见输出包括：

- `output/{date}-{slug}-wechat.html`：微信公众号 HTML。
- `output/{date}-{slug}/xhs-slides.html`：AI 生成的小红书多页 HTML。
- `output/{date}-{slug}-1.png`、`-2.png` 等：小红书图片素材。

## Useful Command

当 AI 已经生成 `xhs-slides.html` 后，可用脚本截图：

```bash
node generate-xhs-slides.js /abs/path/xhs-slides.html /abs/path/output-prefix
```

## Rules

- 默认保持原文结构、观点和事实，不主动做内容重写。
- 小红书图片素材由 AI 先生成 HTML slide，再由脚本稳定截图。
- 输出文件写到用户指定目录或项目 `output/`，不要写入 skill 源码目录中的私有临时内容。
- 详细执行规则以 `SKILL.md` 为准。
