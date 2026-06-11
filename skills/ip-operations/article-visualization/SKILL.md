---
name: article-visualization
description: 把一篇文章/研究博客/论文,分析后做成给「不懂该领域的人」也能看懂的可视化素材——科普长图、小红书图文卡、公众号封面、推特短文。判断(分析/规划/写内容)交给 AI,确定性(渲染/截图/密度测量)交给本机脚本。触发词:把文章做成可视化、科普长图、长图、小红书图文/卡片、公众号封面、文章配图、解读这篇论文/博客做成图、article to visualization、explain this paper/article for laypeople、turn article into infographic/cards。需要本机 Node≥21 + Google Chrome(无头渲染);单 HTML 无外部 CDN,可离线。
---

# article-visualization · 文章 → 多平台科普可视化

把一篇文章/论文/博客,提炼成给外行也能看懂的可视化素材。**一次分析,多路复用**:读文提炼一次 → 分流出长图 / 小红书 / 公众号封面 / 短文。

**人机分工**:Claude 做需要判断的活(读文、定决策、规划、写内容);脚本做确定性的活(渲染、整页/逐卡截图、密度测量)。关键节点(Page Plan、主题)留给用户确认。

## 何时用 / 不用
- ✅ 把一篇文章/研究/博客做成**通俗可视化**(长图 / 小红书卡 / 公众号封面 / 短文)。
- ✅ 面向「不懂该领域的人」的科普表达。
- ❌ 生产级 Web App、SEO 网站、需后端的系统 → 用别的 skill。
- ❌ 忠实「逐字搬运排版」(那应交给逐字排版工具);本 skill 是**重新设计成科普表达**。

## 工作流

### 第 0 步 · 决策块(每篇先做,意图唯一事实源)
在 `<caseDir>/brief.md` 顶部填一段 yaml,**渲染照此、改风格只改这块**;用户没给意图则按内容领域定并写进去:
```yaml
平台: 小红书 + 公众号封面
主题(data-theme): cool-clinical    # 按内容/品牌选,见 references/themes.md
品牌色: 无                          # 用户给了就记色值,并在 xhs-card.css 加一组自定义主题
温度: 安静                          # 大胆/中性/安静——一批别全落安静极简
受众气质: 不懂 AI / 不懂临床的人
```

### 第 1 步 · 分析提炼
读原文(**聚合摘要/截断文本不够时,回原文或数据源取全文**)→ 写 `brief.md`:核心事实清单 + 决策块。涉及具体产品/数据先核实,**不靠记忆编造**。按需 `curl` 原文配图到 `<caseDir>/assets/`(记 `SOURCES.md`);取不到图就不嵌(图步骤可选)。

### 第 2 步 · 分流产出
**A. 科普长图**(完整连续页,不分页)
```bash
cp templates/base-template.html <caseDir>/index.html   # 改写成本篇内容,保留可复用钩子
node scripts/build-longimage.js <caseDir>              # → longimage.html
node scripts/shoot.js <caseDir>                        # → <slug>-longimage.png (2×)
```
长图钩子:`.reveal`(滚动渐入)、`.num[data-to]`(数字滚动)、`.fill[data-w]`(进度条)、`.tab[data-tab=X]↔.panel#panel-X`(长图自动展开堆叠所有面板)。

**B. 小红书图文**(与长图**分流**:从 brief **重新规划**,一卡一观点,不切长图)
```bash
cp templates/xhs-card.css <caseDir>/xhs-card.css
# 读 brief → 按 references/xhs-recipes.md 出文字 Page Plan → 用户确认
# 写 <caseDir>/xhs-cards.html:<html data-theme="决策块里的主题">,每张 .shot.xhs-card[data-name=xhs-NN]
node scripts/shoot-cards.js <caseDir>/xhs-cards.html <caseDir>/xhs   # → 1080×1440 (2×=2160×2880)
node scripts/measure-cards.js <caseDir>                              # 密度检查
```

**C. 公众号封面** `covers.html`(popsci 风,2.35:1 + 1:1)→ `shoot-cards.js`。
**D. 推特/短文** `twitter.txt`(≤140 字 + 200–500 字两版,只出文字)。

### 第 3 步 · 复核(省 token)
渲染后把多张缩略**拼成一张** `_contact.html` 再 `shoot.js` 截全页,**单次查看**;绝不逐张读大图。

## 配色主题(11 套,别写死)
配色不锁死——按内容/品牌/意图在 `<html data-theme="…">` 切换(定义在 `templates/xhs-card.css` 顶部,清单见 `references/themes.md`):
`warm-popsci`(默认/通用) · `cool-clinical`(医学) · `indigo-porcelain`/`swiss-bold`(技术·数据) · `forest-ink`(自然) · `kraft-paper`(手作) · `ink-classic`/`ink-editorial`(评论·报告) · `midnight-ink`(暗色·游戏影像) · `safety-orange`(风险警示) · `neo-brutalism`(黑白硬核,带粗描边样式)。
- **别无脑默认暖色**;按领域选,温度上别一批全落安静极简(数据/风险/媒体主动选大胆款)。
- 用户给品牌色 → 复制一组 `[data-theme="brand-x"]{ … }` 自定义。

## 小红书配方库(R1–R12)+ 密度自适应
- 角色卡 R1–R8(封面/问题/对比/清单/数据条/步骤/金句/结尾)+ 数据卡 R9–R12(大数字 Hero / KPI 塔 / H-bar / 矩阵)。详见 `references/xhs-recipes.md`。
- **一卡一观点;填充 ≥75%**(数字卡放宽到 ~68%)。偏空 → **回原文补真实细节**(`measure-cards.js` 量化);超高 → 精简/裁图。

## 红线(必守)
- **不编造**:没有的数据/图就留诚实占位,绝不造看起来像数据的假数字(尤其医学/科学)。
- **反 AI slop**:不堆无用数字/图标/渐变;每个元素都要 earn its place。
- **一卡一观点**:补内容是补同一观点的支撑,不引入第二观点。
- **重新表达,不逐字搬**:压缩文案、做视觉论点。
- 不把密钥/私有日志写进任何产物。

## 依赖
- Node ≥ 21(内置 `WebSocket`/`fetch`);本机 Google Chrome(路径见 `scripts/shoot.js` 顶部 `CHROME`,按机器改)。
- 单 HTML、无外部 CDN,可离线打开。脚本均以 `<caseDir>` 为参数,可在任意输出目录运行。

## 参考与示例
- `references/xhs-recipes.md` — 配方库 + 硬规则 + 密度自适应 + Page Plan 模板
- `references/themes.md` — 11 套主题库 + 选主题规则 + 意图输入
- `docs/flow.png` — 工作流全景;`docs/theme-gallery.png` — 11 主题同卡对比
- `examples/<slug>/brief.md` — 6 个真实案例的 brief(看决策块怎么填):Anthropic 博客 4 篇(warm-popsci)+ 生物医学预印本 2 篇(cool-clinical)
