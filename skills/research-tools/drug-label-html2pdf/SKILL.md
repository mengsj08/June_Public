---
name: drug-label-html2pdf
description: Fetch official drug labeling by drug name or authoritative URL, preserve the source artifact and provenance, and produce a local searchable HTML or PDF. Use for drug package inserts, prescribing information, DailyMed SPL labels, CDE/NMPA/EMA label links, or a saved legacy hospital-label HTML. Do not use to choose a medicine, provide dosing advice, or silently substitute a different jurisdiction, dosage form, strength, or manufacturer.
metadata:
  display_name: "药品说明书获取与 HTML/PDF 归档"
  version: "0.2.2"
  requires: "python3; Python packages: requests, beautifulsoup4, lxml, pymupdf"
---

# 药品说明书获取与 HTML/PDF 归档

从权威来源取得药品说明书，保存原始文件和来源证据，再按用户需要生成本地 HTML 或 PDF。源文件与派生产物必须区分；不得把重新排版的文件冒充官方原版。

## 先确认药品身份

至少确认地区和药名。已知时同时使用剂型、规格、给药途径、厂家、批准文号或 SETID。

在开始下载前还必须确认交付格式，让用户选择：

- `HTML`：生成可搜索的离线网页；
- `PDF`：保留或生成 PDF；
- `HTML + PDF`：仅当用户明确表示两者都要时选择。

用户尚未选择格式时必须询问，不得默认生成 `both`。原始来源文件仍按产物契约保存在 `source/` 或记录为官方原件，它不等于用户选择了额外交付格式。

- 同名候选超过一个时，先展示候选并让用户选择；不得仅按“最新”自动选中。
- 不得跨地区替换。例如美国的 esketamine 鼻喷剂不能替代中国的艾司氯胺酮注射液。
- 用户只说通用名而候选包含不同剂型或厂家时，检索可以自动进行，下载必须停在消歧环节。

### 显式样本测试

当用户明确说明是在测试 Skill，并授权“任选一个产品”时，可以在**指定地区内**选择一个候选完成端到端测试。该授权只适用于本次测试，不改变正常任务的消歧要求。

- 美国测试可先运行 `search-dailymed`，再用 `fetch-dailymed --query ... --select 1`；候选序号基于本次响应，产物 manifest 必须保留实际 SETID。
- 中国测试仍须使用可核验的中国官方监管附件或上市许可持有人/生产企业官网说明书；可通过 `fetch-url` 加 `--manufacturer`、`--approval-number` 记录产品身份。
- 不得为了“跑通”而把商业聚合页当作中国官方说明书，也不得跨地区拿美国标签替代中国标签。

## 来源路由

1. 美国药品：优先 DailyMed。它提供可检索的 SPL、官方 PDF、ZIP、SETID 和版本日期。
2. 中国药品：优先 CDE 上市药品信息中的说明书附件；用 NMPA 查询核对批准文号、通用名和企业。公共查询受验证码或反自动化保护时，要求用户提供官方结果页或 PDF 直链，不绕过保护。
3. 欧盟集中审批药品：使用 EMA EPAR 的 Product Information PDF。
4. 医院药嘱页或商业聚合页只能作为用户明确提供的兼容输入；不得升级为权威来源。
5. openFDA 可辅助结构化检索，不作为临床事实主源。

完整来源规则和限制见 [references/sources.md](references/sources.md)。

## 标准流程

使用装有依赖的 Python 3；`SKILL` 指向本 Skill 的实际目录：

```bash
PY=python3
SKILL=/absolute/path/to/drug-label-html2pdf
```

如果当前生态提供受管 Python，可把 `PY` 改为该解释器；先运行 `doctor` 确认依赖，不要静默安装依赖或修改系统 Python。

### 1. 环境检查

```bash
"$PY" "$SKILL/scripts/fetch_drug_label.py" doctor
```

### 2. DailyMed 检索与下载

先检索，不直接猜测候选：

```bash
"$PY" "$SKILL/scripts/fetch_drug_label.py" search-dailymed \
  --query "esketamine" --limit 10
```

使用用户确认的 SETID 下载。`both` 会保存官方 XML、ZIP、PDF，并生成派生 HTML：

```bash
"$PY" "$SKILL/scripts/fetch_drug_label.py" fetch-dailymed \
  --setid "<SETID>" --format both --out-dir "<输出目录>"
```

如果用药名直接下载，仅当结果唯一时才允许自动继续：

```bash
"$PY" "$SKILL/scripts/fetch_drug_label.py" fetch-dailymed \
  --query "<英文通用名或商品名>" --format pdf --out-dir "<输出目录>"
```

仅在用户明确授权任意样本测试时，可选择当前检索结果中的一个候选：

```bash
"$PY" "$SKILL/scripts/fetch_drug_label.py" fetch-dailymed \
  --query "<英文通用名>" --select 1 --format both --out-dir "<输出目录>"
```

### 3. 导入 CDE、NMPA、EMA 或其他明确授权的官方直链

```bash
"$PY" "$SKILL/scripts/fetch_drug_label.py" fetch-url \
  --url "<官方 HTTPS PDF 或 HTML 直链>" \
  --title "<药品名与剂型>" --jurisdiction cn \
  --manufacturer "<上市许可持有人或生产企业>" \
  --approval-number "<批准文号；未知可省略>" \
  --format both --out-dir "<输出目录>"
```

默认只允许维护过的官方域名。若用户明确提供了其他官方厂家域名，可增加一次性 `--allow-host example.com`；仍禁止 HTTP、localhost、私网 IP 和跨域重定向。

### 4. 兼容旧医院说明书 HTML

此模式只转换用户已经提供的文件，不声明内容权威或当前有效：

```bash
"$PY" "$SKILL/scripts/build_pdf_html.py" \
  --input "<源 HTML>" --out-dir "<输出目录>" \
  --title "<药品名与剂型>" --format both
```

## 产物契约

标准输出目录包括：

```text
source/                 官方原始 XML、ZIP、PDF 或 HTML
assets/                 从官方 SPL ZIP 安全提取的图片（需要时）
label.html              派生的离线 HTML（请求 HTML 时）
label.pdf               官方 PDF；只有源无 PDF 时才由 HTML 派生
manifest.json           来源、标识符、日期、URL、哈希和派生关系
verification.json       文件类型、哈希、页数、文字层和章节检查
```

- 官方 PDF 原样保存时，manifest 中 `derived=false`。
- 由 XML/HTML/PDF 文字层生成的 HTML 或 PDF 必须记录 `derived=true` 和 `derived_from`。
- 所有事实性状态只来自响应、文件或 manifest；无法核实的字段留空或标记 `unknown`。

## 验证与停止条件

```bash
"$PY" "$SKILL/scripts/verify_artifacts.py" "<输出目录>"
```

以下任一情况必须停止，不得换用非权威来源掩盖失败：

- 候选存在剂型、规格、厂家或地区歧义；
- 官方站要求验证码、登录或人工确认；
- 下载内容类型与文件签名不一致；
- 重定向离开允许的官方域名；
- XML 无可识别说明书章节，或 PDF 无法打开；
- 用户要的是当前批准版本，但只能找到未核实的缓存或医院页面。

本 Skill 只归档标签，不提供选药、诊断或剂量建议。
