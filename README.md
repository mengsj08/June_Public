# June Public

Public skill collection.

## Skills

- `skills/research-tools/scientific-pdf-bilingual-reader/`
  科研长 PDF 双语阅读工作台（macOS，本地运行）：文本页直提、扫描页 PaddleOCR，经本机 Codex/Claude CLI 登录态翻译，产出中文 PDF 与同页左右双语 PDF。AGPL-3.0，v0.1.0。

- `skills/ip-operations/xiaohongshu-skills/`
  小红书自动化技能集合：认证、搜索、发布、互动、复合运营，以及 topic2feishu 采集写入飞书 Base。

- `skills/ip-operations/article-visualization/`
  文章/论文科普可视化：把研究论文、技术博客或长文章重新设计成外行可读的长图、小红书图文卡、公众号封面和短文素材。

## Safety

This repository contains only code, skill instructions, tests, examples, and selected extension source. It does not include local account state, cookies, Feishu app secrets, user tokens, bot tokens, fetched meeting transcripts, generated runtime workspaces, or collected output data.

For `xiaohongshu-skills`, account sessions, cookies, Feishu Base credentials, and collected content must stay in each user's own local config or environment files.

For `article-visualization`, generated case folders, screenshots, downloaded article images, runtime HTML, and unpublished drafts must stay outside this public repository unless they are intentionally synthetic examples.
