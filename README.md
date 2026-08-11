# June Public

Public skill collection and the AI4LifeScience site.

## Site

Published via GitHub Pages from [`docs/`](docs/): **https://mengsj08.github.io/June_Public/**

- **Source Atlas** ([`docs/index.html`](docs/index.html)) — curated, browsable map of
  AI4LifeScience information sources (companies, discovery tools, venues, datasets,
  guidelines). Data in [`docs/sources.json`](docs/sources.json).
- **Author Literature Map** ([`docs/author-map.html`](docs/author-map.html)) — landing page
  for the evidence-gated per-author literature map toolkit.
- [Bookmark provenance note](docs/bookmark-provenance-2026-05-28.md) — how the atlas was derived.

Migrated from `mengsj08/AI4LifeScience_Public` on 2026-08-11; that repository is archived.

## Skills

- `skills/research-tools/scientific-pdf-bilingual-reader/`
  科研长 PDF 双语阅读工作台（macOS，本地运行）：文本页直提、扫描页 PaddleOCR，经本机 Codex/Claude CLI 登录态翻译，产出中文 PDF 与同页左右双语 PDF。AGPL-3.0，v0.1.0。

- `skills/research-tools/author-literature-map/`
  作者文献地图工具包：为单个作者构建每条论断都可追溯到可验证记录的文献地图，证据门控。MIT 许可。

- `skills/ip-operations/xiaohongshu-skills/`
  小红书自动化技能集合：认证、搜索、发布、互动、复合运营，以及 topic2feishu 采集写入飞书 Base。

- `skills/ip-operations/article-visualization/`
  文章/论文科普可视化：把研究论文、技术博客或长文章重新设计成外行可读的长图、小红书图文卡、公众号封面和短文素材。

## Safety

This repository contains only code, skill instructions, tests, examples, and selected extension source. It does not include local account state, cookies, Feishu app secrets, user tokens, bot tokens, fetched meeting transcripts, generated runtime workspaces, or collected output data.

For `xiaohongshu-skills`, account sessions, cookies, Feishu Base credentials, and collected content must stay in each user's own local config or environment files.

For `article-visualization`, generated case folders, screenshots, downloaded article images, runtime HTML, and unpublished drafts must stay outside this public repository unless they are intentionally synthetic examples.
