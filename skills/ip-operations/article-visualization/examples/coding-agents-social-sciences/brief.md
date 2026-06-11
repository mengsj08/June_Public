# 案例:Coding Agents in the Social Sciences(通俗可视化)

## 决策(开工前定 / 渲染照此 / 改风格只改这块)
```yaml
平台: 长图 + 小红书
主题(data-theme): warm-popsci      # 当前渲染;数据偏多,重做可考虑 swiss-bold / indigo-porcelain
品牌色: 无
温度: 中性
受众气质: 不懂 AI 的人
```

- **源文**:https://www.anthropic.com/research/coding-agents-social-sciences
- **目标受众**:不了解 AI / 不清楚 AI4S 能做什么的人
- **目标**:看完页面就能理解"能自己写代码跑分析的 coding agent 到底能为科研做什么、谁在用、带来了什么变化"
- **产物**:`_runtime/task-workbenches/article-visualization/coding-agents-social-sciences/`
- **体裁差异**:与化学篇不同——这是一篇**调研报告**(统计数据为主),可视化重在"数据 + 鸿沟 + 张力",而非"能力演示"。

## 文章核心(用于可视化的事实清单)

- 调研:2026 年 2–3 月,1,260 位定量社会科学家;经济/政治/社会学各约 20%,另含管理、心理、公共卫生、教育、传播;40% 教授、25% 助理教授、30% 博士生。自选样本,偏向"对 AI 感兴趣"者。
- 什么是 coding agent:能自主"拿到研究想法+数据 → 写并运行分析代码 → 解读结果 → 自己迭代",把过去被视为不可替代的人类工作自动化。
- 采用率:81% 用过 AI 聊天工具;仅 20% 常用 coding agent(每周+);coding agent 用户中 86% 用 Claude Code、31% 用 Codex。
- 用途:97% 的 agent 用户用于生成/运行代码;非 agent 的 AI 用户也有 77% 生成代码;仅 33% 的 AI 用户用来起草论文文字。
- 鸿沟(最意外的发现):
  - 学科常用率:经济学 39% / 政治学 25% / 公共卫生 6% / 传播 6% / 教育 4%
  - 性别:男性化名字研究者采用率约为女性的 2×
  - 院校:Nature Index 前 25 高校采用率高约 40%
  - 资历:博士生/博后约 25% 在用,终身教授 <12%
- 产出(调研前 6 个月):
  - 早期:多启动约 25% 项目、多发约 50% 工作论文、更多基金/会议投稿,前期指标高产 10–75%
  - 最终:期刊投稿/重投**无差异**
- 心态:88% 认为 AI 提升论文生产力(≥5/10),50% 打 8 分以上;对个人乐观(约 70% 更看好个人 vs 领域),对领域担忧(拥堵、竞争、选择性报告)。
- 局限:自选样本偏向爱好者;描述性非因果;衡量数量非质量;仅命令行工具;时间可能太早。
- 金句:"The early adopters of coding agents may be more productive and otherwise different from non-adopters in many ways that we cannot measure directly."

## 设计取向

延续上篇中文科普风格与设计系统。用 tab 拆"研究早期阶段(加速) vs 最终发表(无差别)",长图自动展开堆叠;鸿沟用大数字卡(2× / +40% / 25% vs <12%);其余用条形图。
