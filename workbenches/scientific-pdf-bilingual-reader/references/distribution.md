# 分发与运行时边界

## 一份 Skill，两处发现目录

- Codex 个人 Skill：`~/.agents/skills/scientific-pdf-bilingual-reader/`
- Claude Code 个人 Skill：`~/.claude/skills/scientific-pdf-bilingual-reader/`
- 两处都是同一份 Skill 的独立副本，便于任一生态单独卸载或升级。
- 大型 Python 依赖不复制两份；Codex 与 Claude 共用翻译运行时，并按需共用一个与之隔离的 OCR 运行时。
- 强制升级时，旧版移到应用数据目录的 `skill-backups/<ecosystem>/`，不留在 Skill 发现目录中，避免备份被误识别为另一个 Skill。

## 受管运行时

macOS 默认位置：

`~/Library/Application Support/Scientific PDF Bilingual Reader/runtime-v1/`

其中包含固定版本的 uv、uv 管理的 Python 3.12、隔离 venv 和安装清单。安装成功后会清除可重建的 uv 下载缓存，避免重复占用近 1 GB；模型与字体由 BabelDOC 的校验机制预下载到用户缓存 `~/.cache/babeldoc/`。可用 `PDF_READER_RUNTIME_DIR` 覆盖运行时根目录。

扫描页首次使用且用户明确确认后，另建：

`~/Library/Application Support/Scientific PDF Bilingual Reader/ocr-runtime-v1/`

其中包含独立 Python 3.12、PaddlePaddle/PaddleOCR/PaddleX、英文 PP-OCRv5 模型和带哈希的模型资产清单。预计约 1–2 GB，可用 `PDF_READER_OCR_RUNTIME_DIR` 覆盖。文本型 PDF 不依赖也不触发该安装。

安装器不使用 `sudo`，不改 shell profile，不读取 Codex 或 Claude 的凭据。模型调用继续使用用户现有的本机登录态。

## 隐私与模型调用

- PDF、译文和任务状态保存在本机任务目录，不随 Skill 安装或升级复制。
- 选择 Codex 或 Claude 翻译/审阅时，完成任务所需的文字或页面截图会发送给相应模型服务；工作台不得表述为“原文不上传”。
- Codex 翻译与审阅运行在空白临时工作目录，并禁用 Shell、统一执行、应用、浏览器与多 Agent 工具；Claude 文本翻译禁用工具，截图审阅在空白临时目录中只开放 Read 两张复制图片，所有 Claude 调用均禁用会话持久化。
- 真实回归页面与 OCR 文本必须位于 Skill 目录之外；只有显式设置 `PDF_READER_PRIVATE_REGRESSION_DIR` 时才参与本机测试。

## 第三方底座

- PDFMathTranslate / pdf2zh 1.9.11，固定到提交 `44c4d5b332705797c1df17fadde2022e7c49f5de`，AGPL-3.0。
- BabelDOC 0.2.33，用于版面分析、字体和模型资产管理。
- PyMuPDF 1.25.2，用于 PDF 文本层、页面渲染和回填。
- Python 由 uv 下载的 python-build-standalone 发行版提供。
- PaddlePaddle 3.3.1、PaddleOCR 3.7.0、PaddleX 3.7.2，Apache-2.0；仅安装到独立 OCR venv。
- PDF.js / pdfjs-dist 6.1.200，Apache-2.0；固定版本与哈希见 `frontend-runtime-lock.json`，作为本机工作台的适宽阅读、可折叠缩略图和文本选择渲染层，不依赖外部 CDN。

对外分发前仍应由发布者确认本 Skill 自身采用的许可证和第三方告知文本；安装器只锁定并记录第三方来源，不替发布者作法律判断。
