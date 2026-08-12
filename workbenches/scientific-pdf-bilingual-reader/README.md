# Scientific PDF Bilingual Reader

在 macOS 本地运行的科研长 PDF 双语阅读工作台：上传英文 PDF（文本型或扫描版），
可靠文本页直接提取、扫描页按需走 PaddleOCR 生成可搜索文本层，再通过你本机已有的
Codex 或 Claude CLI 登录态翻译成中文，产出中文 PDF 与同页左右对照的双语 PDF。
全程本地：服务只监听 `127.0.0.1`，不需要 API Key，你的文件不离开你的机器。

## 适用 / 不适用

- 适用：科研论文、技术报告、历史扫描书等百页级英文 PDF 的中文阅读。
- 不适用：多语言扫描件、复杂公式重排、出版级版式复刻。
- 平台：**macOS（Apple Silicon 已验证）**。Windows 暂不支持。

## 快速开始

```bash
# 1. 环境自检（首次安装约占用 1.0–1.3 GB，受管运行时独立于系统 Python）
python3 scripts/bootstrap.py doctor
python3 scripts/bootstrap.py install --yes   # doctor 未就绪时

# 2. 启动本地工作台
python3 scripts/launch.py start --open
```

启动器优先使用 `127.0.0.1:8765`；端口已占用时会在 `8876–8895` 中选择首个
可用端口，并在终端打印实际 URL。也可用 `--port` 显式指定端口。

浏览器打开工作台后上传 PDF。扫描页首次需要 OCR 时，页面会请求确认安装约 1–2 GB 的
独立 PaddleOCR 运行时（英文 PP-OCRv5，安装一次离线复用）。

翻译使用你本机已登录的 `codex` 或 `claude` CLI——本项目不索取、不存储任何凭据。

## 产物

每个任务生成：中文 PDF、左右双语 PDF、可搜索原文 PDF（扫描页附不可见文本层）、
页面级 OCR JSON（坐标/置信度/告警）、确定性 QA 报告（`qa-alpha.json`）。
无法可靠翻译的段落保留英文原文并显式告警，不静默丢内容。

## 隐私与边界

- 服务只绑定 `127.0.0.1`；任务数据在 `~/.local/share/scientific-pdf-bilingual-reader/`。
- 安装器不读取、不导出任何凭据；翻译走本机 CLI 登录态。
- 详细技能约定见 `SKILL.md`，验收标准见 `references/acceptance.md`。

## 许可

AGPL-3.0（见 `LICENSE`）。第三方组件与许可见 `THIRD_PARTY_NOTICES.md`。
版本历史见 `CHANGELOG.md`。
