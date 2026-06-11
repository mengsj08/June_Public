# 案例:Vibe Physics — The AI Grad Student(通俗可视化)

## 决策(开工前定 / 渲染照此 / 改风格只改这块)
```yaml
平台: 长图 + 小红书
主题(data-theme): warm-popsci      # 叙事案例,暖亲和
品牌色: 无
温度: 中性
受众气质: 不懂 AI / 不懂物理的人
```

- **源文**:https://www.anthropic.com/research/vibe-physics
- **目标受众**:不了解 AI / AI4S 的人
- **目标**:看完理解"在专家带领下,Claude 今天能完成到什么程度的科研(理论物理),强在哪、会在哪翻车"
- **产物**:`_runtime/task-workbenches/article-visualization/vibe-physics/`

## 核心事实清单

- 主角:哈佛物理教授 Matthew Schwartz + Claude Opus 4.5。把一个二年级研究生级(G2)量子色动力学计算,从单干 3–5 个月压到 **2 周**(约 10×;若带真人研究生需 1–2 年)。
- 问题:resumming the Sudakov shoulder in the C-parameter(有成熟方法、执行复杂的结构化问题)。论文已发 arXiv(2601.02484, 2026-01-05),含一个少见的新因子化定理,r/physics 上热议。
- 规模数据:270 个会话、51,248 条消息、约 2750 万输入 token / 860 万输出 token、110 个论文草稿版本、约 40 CPU 小时模拟、人工监督 50–60 小时。
- Claude 擅长:不知疲倦地迭代(110 版)、基础数学(建积分/换元/展开/核对系数)、写代码(Python/Fortran/Mathematica 都能跑)、文献综合、回归与拟合统计。
- Claude 短板(关键诚实点):会"自欺/造假"——调参数让图好看而非找真错;说"已验证"其实没查;编造论文里没有的系数;留下被遗忘的"僵尸段落";被逼深究时会给"你想要的答案";守不住非标准约定(退回教科书默认);找到第一个错就停;多步问题易迷失;不会调图的美观。
- 专家如何驾驭:树状任务结构(102 个任务 / 7 个阶段,每阶段 15–35 分钟);三模型交叉验证(GPT 5.2 + Gemini 3.0 互查,抓出三方各自漏掉的错);在 CLAUDE.md 写"诚实协议"(不许用"于是变成/为一致性"跳步,要么算要么说不知道);反复追问"再查一遍"。
- 能力阶梯:G1 一年级(课程,约 2025-08 达成)→ G2 二年级(结构化技术项目,2025-12 达成)→ G3+ 创造性开放研究(外推约 2027-03)。
- 缺的东西:**taste(品味)**——判断哪个方向有前途的直觉;LLM 有创造力但缺这种判断。
- 金句:"If I forced it to think deeply, after a while it would give me the answer I seemed to want, even if unjustified."

## 设计取向

延续中文科普风格。用 tab 拆"Claude 擅长什么 / Claude 会怎么翻车"(长图自动展开堆叠);能力阶梯用时间线;加速用大数字;诚实短板要如实呈现,这是文章灵魂。
