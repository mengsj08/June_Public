# Feishu Message Generation Prompt

你要把 `team_sync_reporter.py run` 生成的原始测试报告改写成适合发送到团队飞书群的消息。

## 目标

- 让团队成员快速看懂：谁做了什么、哪些完成了、哪些需要验收、哪些还在推进。
- GitHub 仓库变更和 Feishu/Wiki 源系统变更必须分开写。
- 如果 Feishu/Wiki 在统计窗口内没有源文档变化，必须明确写：本时间窗口内未检测到 Feishu/Wiki 源文档新增或修改。
- 不要把首次全量同步入库数量写成当天 Feishu 源新增。

## 推荐结构

团队工作更新摘要（YYYY-MM-DD）

一、总体情况
- GitHub 提交数
- Feishu/Wiki 源系统变更数
- 今日主线

二、谁做了什么
- 按负责人分组
- 每条写任务编号、任务名、状态、实际推进动作
- done / review / in-progress / todo 分开表达

三、Feishu/Wiki 变更
- 有变更则列文档标题、知识库、修改时间、修改人（如果有）
- 无变更则明确说明无变更

四、需要确认或下一步
- 只列 3-5 条

## 风格

- 中文、简洁、可直接发群。
- 不要贴 commit hash。
- 不要贴路径，除非路径本身是团队需要点击或定位的交付物。
- 不要写调试过程。
- 不要写 token、secret、webhook、cookie、chat id 或任何凭据。
