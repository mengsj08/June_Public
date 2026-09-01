# 药品说明书权威归档

> 按地区和具体产品取得药品说明书，保留官方原件与来源证据，并生成用户选择的 HTML、PDF 或两者。

[![Python 3](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![DailyMed](https://img.shields.io/badge/US-DailyMed-2563eb)](https://dailymed.nlm.nih.gov/)
[![Source Available](https://img.shields.io/badge/license-source--available-7c3aed)](LICENSE)

同一个通用名可能对应不同国家、剂型、规格和厂家。本 Skill 把产品身份确认放在下载之前：候选不唯一时让用户选择，不跨地区替换，也不把商业聚合页冒充成官方说明书。

## 能做什么

- 美国：检索 DailyMed SPL，保存官方 XML、ZIP、PDF 和 SETID；
- 中国：归档 CDE/NMPA 官方附件或上市许可持有人、生产企业官网说明书；
- 欧盟：归档 EMA EPAR Product Information；
- 兼容输入：把用户已有的旧医院说明书 HTML 转成可搜索 HTML/PDF，但明确标注其权威性未经监管来源核验；
- 为每次归档生成 `manifest.json` 与 `verification.json`，记录来源 URL、文件哈希、派生关系、页数和文字层检查。

它只负责说明书检索与归档，不提供诊断、选药或剂量建议。

## 先安装依赖

建议使用独立虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install requests beautifulsoup4 lxml pymupdf
python scripts/fetch_drug_label.py doctor
```

Skill 不会静默安装依赖，也不会修改系统 Python。

## 交给 Agent 使用

```text
完整阅读 SKILL.md。帮我获取草酸艾司西酞普兰片的中国说明书；先核对候选产品，
然后问我需要 HTML、PDF 还是两者。只接受可核验的官方监管或厂家来源，并保留 manifest。
```

下载前必须明确选择：

- `HTML`：可搜索离线网页；
- `PDF`：官方 PDF，或在没有官方 PDF 时生成派生 PDF；
- `HTML + PDF`：只有用户明确选择两者时才生成。

## 命令行示例

检索 DailyMed：

```bash
python scripts/fetch_drug_label.py search-dailymed \
  --query "escitalopram" --limit 10
```

按已经确认的 SETID 下载 PDF：

```bash
python scripts/fetch_drug_label.py fetch-dailymed \
  --setid "<SETID>" --format pdf --out-dir "/absolute/output/label"
```

归档已确认的官方链接：

```bash
python scripts/fetch_drug_label.py fetch-url \
  --url "<OFFICIAL_HTTPS_URL>" \
  --title "<药品名与剂型>" --jurisdiction cn \
  --manufacturer "<上市许可持有人或生产企业>" \
  --format both --out-dir "/absolute/output/label"
```

完整来源规则见 [`references/sources.md`](references/sources.md)。

## 验证

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/fetch_drug_label.py doctor
```

测试 fixture 是合成药品内容，不包含患者资料、真实说明书或账号信息。真实下载文件、运行日志和生成结果必须保存在本仓库之外。

## 安全边界

- 仅允许 HTTPS、维护过的官方域名和用户显式追加的官方厂家域名；
- 拒绝 localhost、私网 IP、URL 内凭据和跨域重定向；
- 不绕过验证码、登录墙或监管网站的反自动化保护；
- 外部 HTML 按不可信输入清理脚本、表单、iframe 和事件属性；
- 原始官方文件与派生文件分开记录，不把重新排版文件冒充官方原版。

## 许可证

源代码公开供查看与评估；未授予通用复制、修改、再分发或商用许可。详见 [LICENSE](LICENSE)。药品说明书本身属于各自来源方，不包含在本仓库中。
