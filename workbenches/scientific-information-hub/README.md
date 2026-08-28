# Scientific Information Hub

一个本地优先、可复现的科研与 AI 信息链参考实现：把公开 API、账号型来源、作者追踪、浏览器快照和历史数据统一转换成可审计事实，再经过可解释筛选，生成日报、静态网站和受控分发包。

> 当前版本：`0.1.0-reference`。默认只运行合成离线示例，不联网、不调用模型、不发送外部消息。

## 它解决什么问题

多数信息聚合工具只给出“抓到了什么”。本项目同时回答四个问题：

1. 这条信息从哪里来，本次是否真的访问了上游？
2. 它是新增、更新还是已经见过？
3. 为什么进入必看、速览、折叠或归档？
4. 哪一个事实池生成了日报、网站和外部内容包？

```text
source adapter
  -> artifact + manifest + health
  -> normalize + identity + freshness + dedup
  -> deterministic profile scoring + optional LLM triage
  -> daily_items.jsonl
  -> Markdown / static site / controlled sinks / public-content package
```

## 60 秒离线复现

需要 Python 3.10+，运行时无第三方 Python 依赖。直接运行下列脚本无需安装；如果执行
`pip install -e .`，标准隔离构建会按 `pyproject.toml` 获取 setuptools 构建工具。

```bash
cd workbenches/scientific-information-hub
python3 scripts/doctor.py
python3 scripts/run_demo.py --output-dir /tmp/sih-reference-demo
python3 -m unittest discover -s tests -v
python3 -m http.server 8872 --directory /tmp/sih-reference-demo/site
```

打开 <http://127.0.0.1:8872/>。离线示例只使用 `fixtures/synthetic/` 中的虚构记录。

## 三段链路

### 1. 数据源

| 组 | 公开能力 | 默认状态 |
|---|---|---|
| 公开 API / Feed | PubMed、arXiv、RSS/Atom、Hacker News | 实现；live 必须显式启用 |
| 期刊 | 通过 PubMed query 配置期刊集合 | 实现；live 必须显式启用 |
| 作者追踪 | OpenAlex author/work 查询 | 实验；需要使用者自己的 watchlist |
| 邮箱 | `.eml` 目录与通用 IMAP | 实验；IMAP 凭据只读环境变量 |
| Feishu/Lark | 标准化 JSON 导出读取 | 实验；不携带组织账号与 Base 配置 |
| Stork | 本地 JSONL/CSV inbox | 实验；不携带真实收件数据 |
| 浏览器登录来源 | 读取由使用者浏览器导出的规范化 snapshot | 实验；cookie/profile 永不进入本项目 |
| Legacy | JSONL/CSV 字段映射兼容层 | 实验；不把旧文件伪装成当天新数据 |

完整合同见 [`docs/data-sources.md`](docs/data-sources.md)。

### 2. 筛选

筛选是可配置的阅读优先级，不是论文质量或临床证据等级：

1. 稳定身份：PMID、DOI、arXiv ID、canonical URL；
2. 增量语义：`new / updated / seen`；
3. 日期规范化和时效门；
4. 跨源去重与版本归并；
5. 通用 profile 的关键词权重、来源权重和方法新颖度提示；
6. `must_read / skim / collapsed / archive` 四层阅读队列；
7. 可选 LLM triage 只增加结构化判断，不覆盖原始事实和确定性分数。

见 [`docs/selection-pipeline.md`](docs/selection-pipeline.md)。

### 3. 交付与推送

默认只生成本地文件：

- `daily_items.jsonl`：唯一内容事实池；
- `source_health.json`：来源与日级完整性；
- `daily_briefing.md`：人读日报；
- `site/index.html`：本地交互式阅读页面；
- `public_content_candidates.jsonl`：候选内容包，不等于发布。

网络 Sink 默认禁用。Webhook 需要同时满足：配置启用、命令传入 `--publish`、目标地址来自环境变量。真实发布动作应由下游平台工具再做一次人工确认。

见 [`docs/delivery-and-scheduling.md`](docs/delivery-and-scheduling.md)。

## 个性化但不暴露个人隐私

公开的是 profile 的结构和算法，不是任何真实用户的画像。使用者把自己的配置保存在公开仓库之外：

```bash
cp config/profile.example.json /path/outside/repo/my-profile.json
chmod 600 /path/outside/repo/my-profile.json
```

不要提交真实作者名单、邮箱、团队来源、收件人、浏览器快照、阅读历史、模型 trace 或内容发布账本。详见 [`PRIVACY.md`](PRIVACY.md)。

## CLI

```bash
PYTHONPATH=src python3 -m sih_ref.cli demo \
  --date 2026-01-15 \
  --output-dir /tmp/sih-demo

# 使用自己的配置；默认仍不允许外部发送
PYTHONPATH=src python3 -m sih_ref.cli run \
  --config /path/outside/repo/sources.json \
  --profile /path/outside/repo/profile.json \
  --output-dir /path/to/local/data
```

`--live` 才允许访问公开上游；`--llm` 才允许调用模型；`--publish` 才允许启用网络 Sink。三个开关互不隐含。

## 项目结构

```text
src/sih_ref/          核心、来源、画像/LLM、渲染与交付
config/               无隐私的示例配置
fixtures/synthetic/   完全虚构的离线输入
docs/                 架构、来源、筛选、交付和复现说明
automation/           launchd / cron 示例，不含个人路径
tests/                离线确定性与安全边界测试
demo/                 合成演示说明；真实输出不提交
```

## 边界

- 本项目是参考实现，不保证实时上游永不漂移。
- `topic_relevance` 是配置匹配度，不是学术质量评分。
- 登录、账号授权和凭据管理属于使用者自己的工具链。
- 浏览器 Connector 接收已导出的 snapshot，不读取浏览器 profile 或 cookie。
- 外部发送和公开发布必须在下游再次经过人工确认。
- 示例不包含真实论文全文、邮件、会议、客户资料或个人研究画像。

## 许可证与来源

本目录新写的参考实现采用 MIT License。外部 API 和网站内容仍受各自条款约束；本项目只保存合成 fixture，不再分发抓取页面。见 [`PROVENANCE.md`](PROVENANCE.md) 和 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
