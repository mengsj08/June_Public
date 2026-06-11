# 案例:Making Claude a Chemist(通俗可视化)

## 决策(开工前定 / 渲染照此 / 改风格只改这块)
```yaml
平台: 长图 + 小红书 + 公众号封面 + 推特短文
主题(data-theme): warm-popsci      # 通用科普,暖亲和
品牌色: 无
温度: 中性
受众气质: 不懂 AI / 不懂化学的人
```

- **源文**:https://www.anthropic.com/research/making-claude-a-chemist
- **目标受众**:不了解 AI / 不清楚 AI4S 能做什么的人
- **目标**:看完页面就能理解"今天用 Claude 能完成哪些科研任务/目标"
- **产物**:`_runtime/task-workbenches/article-visualization/claude-chemist/`
  - `index.html`(可交互网页)、`longimage.html`(长图源)、`claude-chemist-longimage.png`(分享长图)
- **本工作台的 base-template.html 即由本案例沉淀**

## 文章核心(用于可视化的事实清单)

- 背景痛点:同一分子有多种表示(手绘结构 / SMILES / 波谱读数 / 数据库名称),化学家日常要在它们之间"翻译";已编目 >2.9 亿种物质、每天新增约 1.5 万,人工跟不上;读错结构(如镜像)后果严重——以"反应停(thalidomide)"为例。
- 两项被验证的能力:
  - **正向预测**(分子→波谱):读 SMILES,预测 NMR 峰位置、分裂样式、亚峰间距;支持多种溶剂(DMSO-d₆ / CDCl₃ / D₂O)。
  - **反向推断/结构解析**(波谱→分子):仅凭分子式 + 一维波谱,提出候选结构并按置信度排序;无需二维核磁或付费授权软件。
- 实测(20 个训练截止后才发表的化合物,4 类骨架;对比 ChemDraw、MestReNova):
  - 氢谱误差 ±0.079 ppm(合格线 ±0.20);碳谱 ±1.37 ppm(合格线 ±1.0)
  - 亚峰间距预测命中(±0.5 Hz)约 80% vs 传统软件 26–35%
  - 结构解析 15 题:简单 8 个 100% 三次全中;复杂 7 个中 4 个三次全中、其余 3 次中 2 次(给起始原料提示)
  - 模型梯度:Opus 4.7 最强 > Opus 4.6 居中 > Sonnet 4.6 最弱
- 未来四关:① 看懂图中分子 ② 反应与合成路线推理 ③ 机理解释 ④ 化学文献理解
- 诚实局限:仅 20 化合物/4 类骨架、单一结构、排除二维实验与立体化学、溶剂仅 3 种、未含复杂天然产物;理想评测应覆盖数百化合物、20–30 类骨架。
- 金句:"Claude is starting to meaningfully assist chemists with the daily translation, recall, and integration work that complements their judgment."

## 设计取向

全中文科普语气;术语(SMILES/NMR)配蓝色"名词解释"框 + 类比;数字滚动、滚动渐入、CSS 条形图;两项能力做成可点击 tab(长图版自动展开堆叠)。
