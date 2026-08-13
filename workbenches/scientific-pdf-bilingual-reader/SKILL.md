---
name: scientific-pdf-bilingual-reader
description: 在 macOS 本地启动长 PDF 双语阅读工作台，上传文本型或扫描版英文 PDF；可靠文本页直接提取，扫描页按需用 PaddleOCR 生成可搜索文本层，再通过用户已有的 Codex 或 Claude 订阅翻译为中文 PDF，并提供同页左右对照、任务留存和文件导出；支持长 PDF、较高质量翻译与长尾问题 AI 半自动修复。适用于科研论文、技术报告、百页级英文 PDF 的中文阅读；不适用于多语言扫描件、复杂公式重排或要求出版级版式复刻的任务。
---

# 长 PDF 双语阅读器

Implementation status (2026-08-13): Stage 0–3 的代码路径已经实现，包括 Comment/逐条 AgentReview、整篇级进度与跨页批量送审、批准修复池、RepairBatch/PagePatch、逐页纳入以及最终候选的失败回滚安装。真实 WCPFC 任务已验证跨页 Comment 汇总与选择；扫描页 clean/overlay 决定和 fallback 已进入正式 page-plan 与 QA。Stage 4 经验候选仍未实现；混合 PDF 的文本主链、扫描翻译缓存语义与部分旧修复入口仍按已知限制处理。

## 工作方式

1. 先运行 `python3 scripts/bootstrap.py doctor`，只报告平台、路径、受管 Python 3.12、PDF 引擎和预下载资产的可用性，不读取密钥。
2. 若受管运行时未就绪，向用户说明首次安装长期约占用 1.0–1.3 GB，得到确认后运行 `python3 scripts/bootstrap.py install --yes`。安装器固定 uv、Python、PDF 引擎提交和关键依赖，预下载实际使用的版面模型、字体和 tokenizer，并清理临时安装缓存；不得使用 `sudo` 或修改 shell 配置。
3. 环境通过后运行 `python3 scripts/launch.py start --open`。必须由该启动器把工作台放进受管 Python，避免系统 Python 缺少 PyMuPDF 导致 AI 诊断或修复失败。
4. 若用户拿到的是待安装分发包，运行 `python3 scripts/setup.py --targets both`；它把同一 Skill 分别安装到 Codex 的 `~/.agents/skills/` 和 Claude Code 的 `~/.claude/skills/`，两者共用一套大型运行时。已有安装不得静默覆盖；审阅后才可使用 `--force` 备份替换。
5. 让用户在本地页面上传英文 PDF、选择 Codex（主验收）或 Claude（兼容验收）并开始处理。上传后先用 PyMuPDF 做逐页只读预检：可靠文本层走原提取链；无文本或稀疏文本且大面积为图像的页面走 OCR；纯空白页原样保留。用户可用页码列表强制整页 OCR；文本页检测到的嵌入图片在任务卡中按“页码 + 图片序号”单独触发 OCR，并只把不可见文本回填到该图片矩形。
6. 只有确实出现 OCR 页且独立 OCR 运行时未就绪时，页面才可显示约 1–2 GB 的明确确认。用户确认后由 `python3 scripts/bootstrap.py ocr-install --yes` 安装固定 Python 3.12、PaddlePaddle、PaddleOCR 和英文 PP-OCRv5 模型到独立 `ocr-runtime-v1/`；取消时任务保留为等待状态，不得静默下载。
7. OCR 子进程以 220 dpi 渲染目标页，执行文档方向校正、去畸变、文本行方向识别、检测与英文识别；逐页结果写入 `ocr-results.json`。OCR 页使用校正后的页面图像和不可见英文文本层生成 `searchable-original.pdf`，非 OCR 页复制原 PDF 内容；原始 `original.pdf` 永不改写。
8. 翻译前后使用 `scripts/page_router.py` 生成逐页策略：正文常规翻译；目录与缩略语进入结构化通道；列数和复杂度适中的矢量文本表格逐单元格翻译，并把邻近表题、表注、来源说明和续表标记交给 AI 判断归属后按原坐标翻译；超宽或高密数据表锁定数据区并只采用译文表题。
9. 使用 `scripts/dual_pdf.py` 把原文与中文逐页合成一份横向左右并排 PDF；网页预览和默认导出均使用该文件，同时保留单独中文 PDF。
10. 使用 `scripts/qa_alpha.py` 对最终中文 PDF 做全量文本层与96dpi渲染层确定性检查；严重问题将任务标为 `NEEDS_REVIEW`，下载按钮明确标记为草稿，不得冒充已完成。
11. 使用 `scripts/qa_repair_harness.py` 处理已确认的问题页：先在任务内缓存并去重翻译项，以稳定 ID 分批调用 AI；再按问题族执行目录语义重排、局部漏译覆盖或“恢复原网格后逐格回填”。`--full` 只重建目标页，其他页面直接复制当前译文，并把完整修复版写入隔离 staging。
12. 人工抽检 staging 中的目录、表格、旋转页和表单页；通过后使用 `scripts/install_repaired_outputs.py` 备份旧下载文件并原子安装中文 PDF、双语 PDF、逐页计划和 QA 报告。全篇 QA 仍有 critical 时任务必须保留 `NEEDS_REVIEW`。
13. 翻译期间保留原文件、状态、逐页策略、`qa-alpha.json` 和日志；通过或复核后在页面中预览、下载双语 PDF 或单独中文 PDF。
14. 用户可在“查看 QA”中按页选择具体问题：先点击“让 AI 分析”，只把该页原文/译文截图、QA 证据、指标和用户补充交给本机 Codex 或 Claude；模型只返回结构化诊断、修复范围、风险和消耗等级，不得在诊断阶段修改 PDF。
15. 用户确认诊断后才运行页面级修复 harness。候选中文/双语 PDF 写入任务内 `repairs/<repair-id>/candidate/`，重新跑全篇确定性 QA；严重问题数增加时自动阻止验收。用户接受后备份旧版本并原子替换当前下载文件，拒绝则保持当前文件不变。
16. 用户可在任意页保存 Comment，或立即提交给本机 Agent 只读审阅；也可从整篇进度卡跨页批量提交待审 Comment。只保存只写本地对象，不检查 Claude/Codex CLI。同页多个 Comment 必须按 `comment_id` 分别返回 AgentReview，缺失、重复或串线时整批失败关闭；AgentReview 只追加意见和人工裁定历史，不直接修改 PDF。
17. 用户对告警的“忽略/恢复待复核”、诊断、候选版本状态、Comment、AgentReview 队列和裁定事件分别写入 `review-state.json`、`repairs/` 与 `review-cycle/`；不得改写原始 `qa-alpha.json`。若失败，先读取页面显示的可核对错误，再看任务目录中的 `task.json`；不要把原文、日志或凭据复制到聊天或提交中。

## 硬边界

- 仅监听 `127.0.0.1`，不创建公网服务。
- UI 提供“退出程序”；仍有排队或运行任务时必须拒绝退出，避免损坏翻译任务；active AgentReview job 也会阻止退出，queued AgentReview 可在重启后恢复。
- 当前只接受英文 PDF。文本页和扫描页可混合；v1 不接受独立 JPG/PNG/HEIC，也不宣称支持中文或多语言 OCR。
- 文本页中的普通嵌入图片默认不自动 OCR；用户可把整页加入“强制 OCR 页”。v1 不提供任意矩形框选 OCR。
- OCR 与翻译运行时必须隔离；跨边界只传 PDF、PNG 和 JSON 路径。OCR 低置信或空识别必须写入可见 warning；不得静默输出空白页，也不得因为 warning 阻断其余页面翻译。
- 单文件上限 500 MB；试用阶段建议先用 30 页以内文件验收。
- 单任务默认最长运行 12 小时，可用 `PDF_READER_JOB_TIMEOUT_HOURS` 调整；百页任务不得使用短时硬截止伪装失败。
- Codex 是主路径，Claude 仅做兼容路径；两者都使用用户本机已有登录态，不索取 API Key。
- PDF 与任务产物留在本机；选择 Codex/Claude 时会把完成翻译或审阅所需的文字/页面截图发送给相应模型服务，界面和文档不得声称“原文不上传”。Codex 文本翻译必须使用空白临时工作区并禁用执行、应用、浏览器和多 Agent 工具；Claude 文本翻译禁用工具，截图审阅只开放临时目录内两张图片的 Read，并禁用会话持久化。
- 可稳定识别为 2–8 列、2–30 行的矢量文本表格可逐单元格翻译；金额、数字、编号和网格必须保持。超宽表格继续保护数据区，只翻译表题、图例或脚注。
- 表格邻近文字必须先按距离和横向重叠收集候选，再由 AI 分类为表题、表注、来源、续表标记或无关正文；只写回确认属于表格的内容，低置信度或排版失败时保留原文并记录 QA warning。
- Gate 1c-alpha 不调用视觉模型，不自动修复；只负责全量标红文本覆盖、控制字符/重复字、旋转方向、区域占用、网格漂移和静默回退风险。文本层与渲染层证据冲突时进入 `NEEDS_REVIEW`。
- AI 诊断和候选修复必须是两个独立的用户动作。诊断只读；修复仅限用户选择的单页与问题族，不得自动扩展到其他页面或整份 PDF。
- 每个候选版本必须可预览、接受或拒绝。接受前不得覆盖当前下载文件；接受时必须把旧中文 PDF、双语 PDF、QA 和逐页计划备份到 `versions/`。
- 删除本地任务默认移入应用专用废纸篓，并记录 Comment、AgentReview、human-review、repair 和 PageManifest 对象数量；永久删除必须带独立确认。
- 问题页修复 harness 属于 Gate 1c-beta 实验面：只有“目标数=成功回填数、失败无损回退、修后 critical 不增加、人工视觉复核通过”同时满足时，策略才可考虑接入工作台。
- 修复翻译必须使用任务级缓存、去重和稳定 ID 批处理；默认每轮最多 12 次 AI 请求，缺失 ID 只允许一次成组重试。达到预算后保留原文并报告，禁止逐条无限重试。
- 旋转页只回填高置信表格单元格；表外文字坐标系无法可靠对应时保留英文原位。少翻译可以接受，竖排、越界或错格覆盖不可接受。
- 大型依赖只能在用户确认预计下载量后由 `scripts/bootstrap.py` 安装到应用专用目录。禁止静默下载、写入系统 Python、使用 `sudo` 或索取 API Key。

## 验收顺序

按 `references/acceptance.md` 执行。文本型最小链是：启动页面 → 上传 PDF → Codex 翻译 → 生成中文 PDF → 左右同页切换 → 下载并能找到文件。OCR 链还必须通过页面路由、可搜索原文、页级 JSON、无静默空页和 CER 量化门禁。

Windows 当前仍是实验适配面，公开版本不提供原生 Windows 安装入口，也不能宣称已经支持 Windows。WSL2 或 Conda 单独通过不等于原生 Windows 支持。

## 文件与数据

- UI 静态资源位于 `assets/app/`。
- 后端入口是 `scripts/workbench.py`。
- 全篇 Comment 审校、可选人工参与、立即/批量 Agent 审阅和批量候选的目标设计见 `references/review-cycle-design.md`；该文档明确区分已实现能力与待实现设计。
- 用户入口是 `scripts/launch.py`；首次安装入口是 `scripts/setup.py`，运行时入口是 `scripts/bootstrap.py`。
- 默认任务数据位于 `~/.local/share/scientific-pdf-bilingual-reader/tasks/`，可用 `PDF_READER_DATA_DIR` 改写。
- 受管运行时默认位于 macOS 的 `~/Library/Application Support/Scientific PDF Bilingual Reader/runtime-v1/`，可用 `PDF_READER_RUNTIME_DIR` 改写。
- 按需 OCR 运行时默认位于同级 `ocr-runtime-v1/`，可用 `PDF_READER_OCR_RUNTIME_DIR` 改写；模型缓存包含在该目录中。
- 翻译引擎可用 `PDF_READER_PDF2ZH` 指定；默认只使用受管运行时或当前 PATH 中可执行的 `pdf2zh`。
- 分发、第三方来源和双生态目录见 `references/distribution.md`；翻译与 OCR 锁定输入分别见 `references/runtime-lock.json` 和 `references/ocr-runtime-lock.json`。
