# 案例:Long-Running Claude for Scientific Computing(通俗可视化)

## 决策(开工前定 / 渲染照此 / 改风格只改这块)
```yaml
平台: 长图 + 小红书
主题(data-theme): warm-popsci      # 当前渲染;技术/科学计算,重做可考虑 swiss-bold / indigo-porcelain
品牌色: 无
温度: 中性
受众气质: 不懂 AI 的人
```

- **源文**:https://www.anthropic.com/research/long-running-Claude
- **目标受众**:不了解 AI / AI4S 的人
- **目标**:看完理解"让 Claude 连续自主工作几天、自己写科学软件,是怎么做到的,能做到什么程度"
- **产物**:`_runtime/task-workbenches/article-visualization/long-running-claude/`

## 核心事实清单

- 范式转变:过去人们是"对话式"一步步盯着 AI;现在模型能**自主完成跨天、长周期任务**。适合目标清晰、有明确成功标准的活:重写数值求解器、迁移遗留代码、调试大型代码库。
- 招牌例子:Claude Opus 4.6 用 JAX **从零实现一个可微的宇宙学 Boltzmann 求解器**(预测宇宙微波背景 CMB 的统计性质),耗时数天。
  - 成功标准:与参考实现 CLASS 功能对齐、全程可微、精度目标 0.1%(对标 CLASS/CAMB 的一致性)。
  - 结果:与 CLASS 达到亚百分比(<1%)一致;过程"有点笨拙"(初期测试覆盖不足、犯过规范约定等低级错、长时间追 bug),非全场景生产级,但证明了可行。
- 另一例:Anthropic 内部用约 **2000 个会话**让 Claude 造出一个能编译 Linux 内核的 C 编译器。
- 让长时自主跑起来的 5 个关键部件(全文的"方法"核心):
  1. **CLAUDE.md**——主指令文件:高层目标与设计决策,常驻上下文,AI 会自己更新。
  2. **CHANGELOG.md**——可移植的长期记忆:像实验室笔记,记进展、已完成、**失败的尝试及原因**(防止重走死路)。例:"试了 Tsit5 解扰动 ODE,太刚性,改用 Kvaerno5。"
  3. **Test Oracle**——进度标尺:参考实现/测试套件,让 AI 自主衡量对错(这里用 CLASS 的 C 源码当参照)。
  4. **Git**——协调与留痕:每完成一块就提交,可回溯、不丢进度。
  5. **HPC 执行循环**——在计算节点用 SLURM 提交作业 + tmux 里跑 Claude Code,挂起后远程重连、用手机看 GitHub 提交即可了解进度。
- 编排模式:**Ralph loop**——用 for 循环反复追问"还没完成就继续",治"智能体偷懒/提前收工"。类似还有 GSD、Claude Code 的 `/loop`。
- 局限:轨迹笨拙、初期测试覆盖不足、低级错误、非全场景生产级;更适合"单智能体顺序推进 + 按需派生子智能体",而非大规模并行。
- 金句:"The commit log reads like lab notes from a fast, hyper-literal postdoc." / "Every night you don't have agents working for you is potential progress left on the table."

## 设计取向

延续中文科普风格。核心是"5 个部件"的方法论——用 grid 卡片 + 编号呈现;用 tab 拆"过去:盯着一步步做 vs 现在:定目标放手跑几天"(长图自动展开);Boltzmann 例子用大数字/精度。把"闲置算力=机会成本"作为收尾金句。
