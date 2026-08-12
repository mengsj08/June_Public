# Comma Review Studio Alpha 测试指南

## 环境要求

- macOS 优先。DOCX 中的 TIFF 图片会优先用 macOS 自带 `sips` 转成 PNG；其它平台或单图转换失败时会自动降级为图注占位，导入不会因此中断。
- Python 3.10+，只使用标准库运行本地 Review Studio 后端。
- Node.js 与 npm；首次运行前需要在仓库根目录执行 `npm install`。
- Codex CLI 或 Claude CLI 已安装并登录。两者都不可用时，编辑、导入、手动批注、版本历史仍可用，AI Review、快速解释、选区讨论、生成摘要和文章总览会提示先安装并登录 CLI。

## 三步启动

1. 安装依赖：
   ```bash
   npm install
   ```
2. 启动本地 Review Studio：
   ```bash
   ./start-review-studio.sh
   ```
3. 打开启动日志显示的本机地址，默认是：
   ```bash
   http://127.0.0.1:8891
   ```

启动脚本会先运行 doctor，检查 Python、Node、npm 依赖和 Codex/Claude CLI 状态；通过后会启动本机服务并尝试打开浏览器。

## 用什么稿子测

本仓**不附带真实论文**。首次打开时载入的是一份合成样例稿（`paper.md`，含公式、表格、代码，仅供快速看界面）。**请从页头「导入主稿」导入你自己的 Word 或 Markdown 论文**在真实内容上测试；导入的文稿、批注、版本和讨论只存在你本机 `apps/review-studio/data/` 下，不上云、不进仓库、不会回传给任何人。

## 核心功能速览

- 导入主稿 / 切换文档：从 Word、Markdown 创建新的本地主稿；页头文件名菜单可在已有 Markdown 主稿之间切换。
- AI Review 三级落位：APR 首轮生成操作预览；确认后进入主评审批注；后续复审根据预检结果走查看最近、增量复审或全文复审。
- 选区讨论：选中正文后可快速解释，或围绕引用启动 Codex/Claude 多轮讨论；只有显式点击写回才会变成批注。
- 参考资料 PDF：可添加带文本层 PDF 作为 EvidenceSource；添加不会自动调用 AI，生成摘要或纳入讨论/评审都需要显式确认。
- 版本历史：自动快照、命名版本、差异查看、历史恢复和冲突草稿恢复都保存在本机。

## 已知限制

- PDF 参考资料不做 OCR；扫描件或图片型 PDF 只会显示文本不可用或部分可用。
- Web 检索关闭；AI 只基于本机文稿、批注、参考资料和当前提示工作。
- 当前版本是单机单用户工作台，不处理多人实时协作。
- 本地数据不上云；默认数据目录是 `apps/review-studio/data/`，可用 `COMMA_REVIEW_DATA_ROOT` 指向自己的本地目录。
- 图片、公式、复杂表格和 PDF 转换保真度仍需人工核对。

## 反馈渠道

- TODO(June): 填写 alpha 测试反馈渠道。
