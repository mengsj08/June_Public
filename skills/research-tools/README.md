# Research Tools

面向科研信息整理、证据追踪与可复核研究投影的 Skill / 工具集合。这里强调的不是“搜得
更多”，而是把身份判断、来源、纳入排除与最终展示拆开，让每个结论都有回查路径。

## 当前工具

### [药品说明书权威归档](drug-label-html2pdf/)

按地区、剂型、规格与厂家确认具体产品，再从 DailyMed、CDE/NMPA、EMA 或官方厂家来源取得说明书。保存官方原件、来源 URL、哈希与派生关系，并按用户明确选择输出 HTML、PDF 或两者。

适合：

- 临床研究、药物情报与注册资料中的说明书归档；
- 中美或多地区产品说明书分别取证，避免跨地区替代；
- 将官方 PDF 转为可搜索 HTML，同时保留原件；
- 对用户已有的旧说明书 HTML 做受限兼容转换。

快速检查：

```bash
cd drug-label-html2pdf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install requests beautifulsoup4 lxml pymupdf
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/fetch_drug_label.py doctor
```

### [Author Literature Map](author-literature-map/)

从使用者已经确认的作者 ID 与文献 CSV 出发，构建一个单一事实账本，再渲染为静态作者
文献地图。它不会把同名作者自动判成同一个人，也不会把来源不明的记录塞入主结果。

适合：

- 为研究者、PI 或团队成员建立可核验的发表记录页面；
- 合并 OpenAlex 主清单与 PubMed / Semantic Scholar 补充来源；
- 显式区分已纳入、待人工复核与同名排除记录；
- 发现输入文件变化后提示页面已经陈旧，需要重建。

30 秒离线试跑：

```bash
cd author-literature-map
python3 scripts/build_author_map_verdict.py --run-dir example --author "Jane Doe (example)"
python3 scripts/render_author_map.py --run-dir example --author "Jane Doe (example)"
open example/index.html
```

完整输入格式、身份门与在线补充命令见 [`author-literature-map/README.md`](author-literature-map/README.md)。

## 共同原则

1. 身份不自动定调：同名风险必须进入人工确认。
2. 账本先于页面：计数、来源与状态只在一个事实文件中计算。
3. 展示不制造事实：HTML 是账本的投影，不是第二份事实源。
4. 允许不确定：待复核与排除记录应保留可审计数量，而不是被静默删除。
5. 输入可复查：记录来源标识与文件哈希，证据变化后能检测漂移。
6. 医药资料不做跨产品替代：地区、剂型、规格或厂家不一致时必须回到人工确认。
