# PROVENANCE

> KAN-1751 Phase 1-1 逐文件来源清单。审计条目使用固定报告的行号标识（`AUDIT-L<n>`）。

## 快照边界

- 源仓 `kanban-personal` 基线提交：`d205445c33111587d92e845084aaabe237144440`。
- 源仓 `canvas-studio` 基线提交：`ac2a20cfcab377fe2af0d5b0be8c7d9ff45cbd62`。
- 搬运对象取自 2026-08-18 的源仓工作树；两个源仓当时均有未提交改动，因此这里记录的是工作树快照，不宣称等同于上述提交。源仓未被修改。
- 交叉审计：`TaskSpace/_runtime/opensource-audit-20260817/OPENSOURCE_PRIVACY_AUDIT.md`，SHA-256：`31bb3fc0fdd9f4049b47b5b1786742e333928043372c8cce51a08e3f1654d876`。
- `待改写` 表示该源文件至少命中一条 Phase 0 审计记录；按本卡要求仅登记，留待 Phase 1-2/1-3 清除或参数化。本清单不把“已登记”误报为“风险已解决”。

## 开源首轮运行面收窄（KAN-1758）

公开首轮不携带个人 ACP 二级控制面、晨启治理批处理或旧项目索引入口。`Project Canvas`
及 `kanban/static/kanban/modules/render-projects.js` 是保留的主页/项目工作面；本卡删除的是
`render-board-duty.js` 中已被 Project Canvas 取代的旧 `renderProjects()` 索引实现，避免按旧文件名
误删当前项目画布。

逐文件处置：

| 文件 | KAN-1758 处置 |
|---|---|
| `kanban/static/kanban/modules/render-runtime.js` | **removed@KAN-1758**；运行中心视图与装配删除，Git 历史可找回 |
| `kanban/static/kanban/ai-runtime.css` | **removed@KAN-1758**；运行中心专属样式删除，Git 历史可找回 |
| `kanban/static/kanban/modules/automation-schedule.js` | **removed@KAN-1758**；个人自动化档期辅助模块删除，Git 历史可找回 |
| `kanban/morning_batch.py` | **removed@KAN-1758**；晨启批处理删除，Git 历史可找回 |
| `kanban/test_runtime_component_projection.py` | **removed@KAN-1758**；仅覆盖已删运行中心组件投影 |
| `kanban/test_automation_control_plane.py` | **removed@KAN-1758**；仅覆盖已下线 ACP 控制端点 |
| `kanban/test_morning_batch.py` | **removed@KAN-1758**；仅覆盖已删晨启实现、菜单与端点 |

装配与端点同步下线：菜单不再含「更多入口」「运行中心」「项目索引」「本地工具」「晨启」
或动态入口注入位；`/api/automations/schedule`、`/api/automations/{preflight,run,toggle}`、
`/api/morning-batch` 从中央路由表移除，旧端点统一落 JSON 404；`#runtime` 在前端清理 hash
后留在项目主页，不再发出任务详情请求。

### KAN-1758 验证回执（2026-08-18）

- 固定顺序 `本机 pytest -q -rs`：**597 passed, 27 skipped, 0 failed**（32.90 秒）。
- 模块图契约包含在全量 pytest 中并通过；仓内 21 个非构建产物 `.js` 逐文件 `node --check` 全过，`git diff --check` 通过。
- `./start.sh --no-open --port 18995`：Canvas Studio **475 modules** 构建通过，demo 服务 ready。
- HTTP 三面冒烟：主页 `/`、项目画布数据 `/api/project-maps?scope=project:literature-review`、card 画布及其 `/api/canvas` 数据均为 **200**；`literature-review`、`data-analysis` 与 `kanban.canvas/v1` fixture 均解析成功。
- 已下线的 5 条 ACP/晨启路由实测均为 **404 + application/json + {"ok": false, "error": "Not Found"}**；主页 HTML 的 8 类菜单/资源残项复扫为 0。
- 当前环境无可用 in-app/extension browser 实例，且 pytest 明示可选 Playwright 未安装；因此本回执不冒充真实浏览器截图。Claude 的三页旅程、全量浏览器 4xx/5xx 监听与菜单截图仍是独立最终验收门。

## Phase 1-2 身份、actor 与 demo 回销（KAN-1752）

本节只回销 Phase 0 报告中已进入冷启动仓的身份、人名、actor 与真实 fixture 风险；路径/provider/平台参数化仍留 Phase 1-3。计数以固定审计报告行号和其中展开后的源位置为准：**73 条必须清除记录、547 个源位置、70 个仓内文件，已清除 @1-2**。

| 子类 | 审计记录 | 源位置 | 仓内文件 | 回销 |
|---|---:|---:|---:|---|
| owner/persona 与硬编码 actor | 70 | 543 | 70 | 已清除 @1-2；公共核心改为配置驱动的 `owner/operator/reviewer`，交互式画布 actor 从认证会话解析，验收同时记录 `accepted_role` 与配置 actor |
| 真实 person fixture / 邮箱身份位 | 3 | 4 | 2 | 已清除 @1-2；真实 fixture 删除或匿名化，测试邮箱仅使用保留示例域 |
| **合计** | **73** | **547** | **70** | **与 Phase 0 审计对账一致** |

逐条审计记录：`AUDIT-L189`, `AUDIT-L190`, `AUDIT-L191`, `AUDIT-L192`, `AUDIT-L193`, `AUDIT-L203`, `AUDIT-L257`, `AUDIT-L258`, `AUDIT-L259`, `AUDIT-L262`, `AUDIT-L264`, `AUDIT-L266`, `AUDIT-L273`, `AUDIT-L275`, `AUDIT-L276`, `AUDIT-L280`, `AUDIT-L281`, `AUDIT-L286`, `AUDIT-L287`, `AUDIT-L289`, `AUDIT-L290`, `AUDIT-L291`, `AUDIT-L292`, `AUDIT-L293`, `AUDIT-L294`, `AUDIT-L295`, `AUDIT-L296`, `AUDIT-L297`, `AUDIT-L298`, `AUDIT-L299`, `AUDIT-L300`, `AUDIT-L301`, `AUDIT-L302`, `AUDIT-L304`, `AUDIT-L306`, `AUDIT-L309`, `AUDIT-L310`, `AUDIT-L311`, `AUDIT-L312`, `AUDIT-L313`, `AUDIT-L314`, `AUDIT-L316`, `AUDIT-L317`, `AUDIT-L319`, `AUDIT-L320`, `AUDIT-L321`, `AUDIT-L322`, `AUDIT-L323`, `AUDIT-L325`, `AUDIT-L326`, `AUDIT-L327`, `AUDIT-L328`, `AUDIT-L329`, `AUDIT-L334`, `AUDIT-L335`, `AUDIT-L336`, `AUDIT-L337`, `AUDIT-L338`, `AUDIT-L348`, `AUDIT-L349`, `AUDIT-L350`, `AUDIT-L351`, `AUDIT-L352`, `AUDIT-L353`, `AUDIT-L354`, `AUDIT-L355`, `AUDIT-L356`, `AUDIT-L357`, `AUDIT-L358`, `AUDIT-L359`, `AUDIT-L386`, `AUDIT-L395`, `AUDIT-L396` — **全部已清除 @1-2**。其中 `AUDIT-L329` 对应的公开测试文件已改名为 `kanban/test_owner_action_ledger.py`。

deny 模块移交数字为旧 persona 品牌 token **35 处 / 5 文件**；对冷启动仓做仓级复扫后，实际发现旧品牌 token **284 次 / 19 文件**。本卡按更严格的实测范围清理：未搬入模块仍视为不存在，morning batch 摘除了 reminder、pending digest、自动代审与周回顾调用；代码、配置、UI 与测试统一使用中性的 `attention gate` / `人闸`。旧品牌词仅在本段保留来源说明，品牌保留或改名仍由项目 owner 决定。

虚构 fixture 已落 `demo/`：**2 个项目、8 张任务卡、1 个画布**；`.kanban.config.example.json` 的成员和 actor 均来自 roles 配置，`scan_dirs` 仅指向两个 demo 项目目录。所有 demo 人名、机构、标识、日期、结果与路径均声明为虚构。

不在本卡回销范围：Phase 0 第 1 节的路径/provider/平台位置，以及第 2 节 21 条“建议处理”的上游组织/衍生权属记录（95 个位置）；这些不是本卡的个人身份/actor 清除项，继续留给 Phase 1-3 / D1 许可核对。

### Phase 1-2 验证回执（2026-08-18）

- `pytest -q -rs`：**579 passed, 26 skipped, 0 failed**（27.64 秒）。
- 身份复扫：个人 owner 名、个人 handle、已知真实名模式全仓 **0 命中**；旧品牌 token 复扫 **0 命中**(具体 token 串见私有审计文档)；文件名复扫同样无个人身份或旧品牌名。
- fixture 计数：`project.json=2`、任务 Markdown `=8`、canvas JSON `=1`；example config JSON、canvas JSON、Python 编译与 `git diff --check` 均通过。
- `canvas-studio/src/services/canvasApi.ts` 定向 ESLint 通过；全量 `npm run build` 在打包前因 Phase 1-1 未搬入的 `src/components/SystemAlertBadge` 停止，属于冷启动仓既有缺失能力，不是本卡 identity/actor 改动产生，留后续选择性搬仓卡处理。
- 源仓只读边界复核：本卡没有向两个源仓发出写命令；收口时只读 `status --porcelain` 分别显示 66 与 5 条当前工作树状态，因此不把源仓误报为 clean，也不在本卡处置；新仓仍无 remote。
- Claude Code 2.1.206 只读抽查 10 位：**10/10 pass，0 finding**；回执 session `07dcb12d-12e7-4125-9495-f5f01db0343b`。抽查覆盖 roles、example config、Canvas actor、session actor、accepted_by、morning batch、attention gate、real-project authority、demo 数量/虚构声明与本节审计计数/grep。

26 个 skip（逐项）：

1. `test_detail_overlay.py` — 可选 Playwright 未安装。
2. `test_documents_doctor_trial_tools.py` — 未搬入 `governance/scan_governance.py`。
3. `test_e2e_task_detail_flow.py` — 可选 Playwright 未安装。
4. `test_git_hygiene.py` — 未搬入 `governance/git_hygiene.py`。
5. `test_governance_healthcheck_chain.py` — 未搬入 `governance/run_governance_healthcheck_chain.py`。
6. `test_governance_probe.py` — 未搬入 `governance/scan_governance.py`。
7. `test_governance_result_card.py` — 未搬入 `governance/governance_result_card.py`。
8. `test_markdown_styling.py` — 可选 Playwright 未安装。
9. `test_outbound_gate.py` — 未搬入 `governance/outbound_gate.py`。
10. `test_provenance_probe.py` — 未搬入 `governance/provenance_probe.py`。
11. `test_source_anchor_lint.py` — 未搬入 `governance/anchor_lint.py`。
12. `test_subagent_manifest_lint.py` — 未搬入 `governance/subagent-manifest/manifest_lint.py`。
13. `test_team_kanban_sync.py` — 依赖未搬入的 `governance/outbound_gate.py`。
14. `test_frontend_dynamic_surfaces.py:636` — 冷启动仓无真实 bootstrap task。
15. `test_frontend_dynamic_surfaces.py:707` — 未搬入归档 `render-governance.js`。
16. `test_frontend_dynamic_surfaces.py:808` — 已归档 governance surface 的既有显式 skip。
17. `test_frontend_dynamic_surfaces.py:866` — 已归档治理健康块的既有显式 skip。
18. `test_frontend_dynamic_surfaces.py:944` — 已归档治理 inline flow 的既有显式 skip。
19. `test_frontend_dynamic_surfaces.py:993` — 已归档值守段运行时的既有显式 skip。
20. `test_frontend_dynamic_surfaces.py:1116` — 已归档 owner duty runtime 的既有显式 skip。
21. `test_frontend_dynamic_surfaces.py:1234` — 已归档 attention-gate duty runtime 的既有显式 skip。
22. `test_governance_matrix.py:51` — 未搬入 `governance/matrix.json`。
23. `test_public_entry.py:30` — 未搬入 `landing/cockpit-landing.html`。
24. `test_public_entry.py:49` — 未搬入 `landing/cockpit-landing.html`。
25. `test_public_entry.py:60` — 未搬入 `landing/cockpit-landing.html`。
26. `test_task_endpoint.py:268` — 未搬入可选 `kanban/system_alerts.py`。
- 原源仓 Git 历史、remote、gitignored 运行态与 deny 目录均未迁入。

## Phase 1-3 路径、可选星座与冷启动回销（KAN-1753）

本节覆盖固定审计报告中已经进入冷启动仓的路径/provider/平台位置。逐文件表保留 Phase 1-1 搬仓时的原始判定；本节是其后的当前回销状态。公共默认现在只依赖仓内 `demo/`、`kanban/` 与 `canvas-studio/dist`：`repo_root`、`workspace_root`、`data_root`、扫描根、可信打开根和 Canvas dist 均由部署配置解析；外部目标不存在时返回空能力，不产生重复报错。

| 子类 | 审计记录 | 回销 |
|---|---:|---|
| 个人绝对路径、home/Documents 布局、固定应用目录 | 28 | **已清除 @1-3**；代码与配置不再含个人绝对路径，默认根收敛到仓内，`plan_batch` 和 workdir 均支持配置/环境变量 |
| skills、兄弟仓与各私有工作区等星座耦合 | 56 | **已清除 @1-3**；统一改为显式 `integrations.*.enabled` + 路径/provider，未启用或路径不存在时 API 返回空能力且 UI 不渲染入口 |
| 公开可信根 | 2 | **已清除 @1-3**；example 默认只开放仓根与 `demo/`，扩展根必须显式 opt-in |
| macOS 专属调用 | 11 | **已处理 @1-4**；业务主路径不再直调 open/osascript/scutil/networksetup，darwin/linux/unsupported 由薄 platform adapter 分流 |

路径与固定布局逐条：`AUDIT-L95`, `AUDIT-L97`, `AUDIT-L98`, `AUDIT-L99`, `AUDIT-L100`, `AUDIT-L101`, `AUDIT-L102`, `AUDIT-L103`, `AUDIT-L104`, `AUDIT-L105`, `AUDIT-L106`, `AUDIT-L114`, `AUDIT-L118`, `AUDIT-L129`, `AUDIT-L131`, `AUDIT-L134`, `AUDIT-L141`, `AUDIT-L166`, `AUDIT-L169`, `AUDIT-L171`, `AUDIT-L172`, `AUDIT-L173`, `AUDIT-L174`, `AUDIT-L175`, `AUDIT-L176`, `AUDIT-L179`, `AUDIT-L181`, `AUDIT-L182` — **全部已清除 @1-3**。

可选星座/provider 逐条：`AUDIT-L526`, `AUDIT-L528`, `AUDIT-L529`, `AUDIT-L534`, `AUDIT-L535`, `AUDIT-L536`, `AUDIT-L537`, `AUDIT-L538`, `AUDIT-L539`, `AUDIT-L540`, `AUDIT-L541`, `AUDIT-L542`, `AUDIT-L543`, `AUDIT-L544`, `AUDIT-L545`, `AUDIT-L551`, `AUDIT-L556`, `AUDIT-L557`, `AUDIT-L564`, `AUDIT-L569`, `AUDIT-L573`, `AUDIT-L574`, `AUDIT-L575`, `AUDIT-L576`, `AUDIT-L589`, `AUDIT-L608`, `AUDIT-L609`, `AUDIT-L613`, `AUDIT-L614`, `AUDIT-L615`, `AUDIT-L616`, `AUDIT-L617`, `AUDIT-L619`, `AUDIT-L620`, `AUDIT-L621`, `AUDIT-L622`, `AUDIT-L623`, `AUDIT-L624`, `AUDIT-L642`, `AUDIT-L643`, `AUDIT-L645`, `AUDIT-L646`, `AUDIT-L647`, `AUDIT-L648`, `AUDIT-L649`, `AUDIT-L660`, `AUDIT-L672`, `AUDIT-L673`, `AUDIT-L674`, `AUDIT-L683`, `AUDIT-L684`, `AUDIT-L685`, `AUDIT-L686`, `AUDIT-L696`, `AUDIT-L697`, `AUDIT-L698` — **全部已清除 @1-3**。保留在 example/test 中的外部系统名称只作为默认关闭的配置键或 opt-in 契约，不再是运行时隐式依赖。

可信根逐条：`AUDIT-L740`, `AUDIT-L741` — **全部已清除 @1-3**。

macOS 隔离逐条：`AUDIT-L709`, `AUDIT-L710`, `AUDIT-L715`, `AUDIT-L716`, `AUDIT-L717`, `AUDIT-L719`, `AUDIT-L721`, `AUDIT-L727`, `AUDIT-L729`, `AUDIT-L732`, `AUDIT-L733` — **已处理 @1-4**；逐条处置见下一节。

### Phase 1-3 验证回执（2026-08-18）

- `pytest -q -rs`：**589 passed, 27 skipped, 0 failed**（27.01 秒）；新增 10 个 optional-integration/path/provider direct contract 回归。
- `canvas-studio npm run build`：**通过**（475 modules）；补入调用方所需的 `SystemAlertBadge.tsx`，`studio_dist_dir` 默认改为仓内 `canvas-studio/dist`。
- 临时 HOME 冒烟：`HOME=<mktemp> ./start.sh --no-open --port 18993` 一条命令完成依赖检查、前端构建与服务启动；API 返回 **8 tasks / 2 projects**，未配置集成 `[]`、四类可选 UI flags 均为 `false`，demo Canvas 返回 **4 nodes**；启动日志无个人绝对路径、Traceback 或 FileNotFoundError。
- 路径复扫：除本来源账外，代码/配置层本机用户绝对路径、`~/Documents`、`~/skills`、隐式 `../brainloop-lite` 均 **0 命中**。
- 源仓边界：本卡只读取得补拷文件和审计账，不向 `kanban-personal` / `canvas-studio` 源仓写入；冷启动仓仍无 remote。

## Phase 1-4 跨平台启动层回销（KAN-1754）

`kanban/platform_adapter.py` 是公开核心唯一的 OS 桌面边界：darwin 保留
`/usr/bin/open`、AppleScript Terminal 和只读系统代理行为；Linux 使用
`xdg-open` 与脱离当前会话的子进程启动；其他平台或缺失命令时返回可读错误、
记录一次 `[platform]` 日志，并隐藏可选本地工具/网络入口。Linux 分支只有 mock
单测，**未在真实 Linux 主机验证**。Windows 原生不支持，只声明 WSL 路径。

| 审计位 | Phase 0 指向 | Phase 1-4 回销 |
|---|---|---|
| `AUDIT-L709` | `project_conversations.py` 的 AppleScript/Terminal 类型命中 | **已处理 @1-4**：该文件只保留跨平台的可执行后缀拒绝规则，不含 OS 调用；`.app` 明确为 darwin-only 非主路径 |
| `AUDIT-L710` | `scan-docs.py` Terminal/osascript | **已处理 @1-4**：桥接启动改走 `PLATFORM_ADAPTER.launch_command`；darwin Terminal 行为保留，Linux 直启子进程 |
| `AUDIT-L715` | `scan-docs.py` macOS 网络/系统命令 | **已处理 @1-4**：scutil/networksetup 全部收进 darwin adapter；非 darwin 网络入口隐藏，系统代理读取降级不抛异常 |
| `AUDIT-L716` | 源仓 example config 的 app bundle 字段 | **已处理 @1-4**：该私有字段未搬入公开模板；公开配置无 `.app` 主路径 |
| `AUDIT-L717` | 源仓 `kanban.sh` 的 open/Finder | **已处理 @1-4**：该私有 wrapper 未搬入；公开 `start.sh` 分流 macOS `open` / Linux `xdg-open`，缺失时仅提示 |
| `AUDIT-L719` | `scan-docs.py` open/Finder/app bundle | **已处理 @1-4**：路径打开和 app bundle 控制均经 adapter；Linux 用 `xdg-open`，app bundle 仅 darwin 实现 |
| `AUDIT-L721` | 源仓部署文档的 Keychain/截图包装 | **已处理 @1-4**：该私有内容未搬入；公开 README/DEPLOYMENT 明示不提供 `.app`、codesign、launchd 包装 |
| `AUDIT-L727` | 自动化测试中的 launchd 文案 | **已处理 @1-4**：fixture 改为平台中性的“调度 tick”，公开主路径无 launchd 安装器 |
| `AUDIT-L729` | team sync 测试直 mock scutil | **已处理 @1-4**：测试改 mock adapter 的 `system_proxy_output` 契约 |
| `AUDIT-L732` | network status 测试的 `.app` 进程路径 | **已处理 @1-4**：fixture 改为平台中性二进制路径，macOS 系统状态只经 adapter |
| `AUDIT-L733` | open API 测试直断言 `/usr/bin/open` | **已处理 @1-4**：API 测试断言 adapter 调用；darwin 精确命令行为移入 adapter 单测 |

`.app`/codesign/launchd 回销边界：仓内没有 codesign 或 launchd 运行路径；仅在安全
拒绝列表、adapter 的 darwin-only `.app` 方法以及本来源说明/部署声明中出现相关
名词。公开版不承诺这些 macOS 启动器包装能力。

### Phase 1-4 验证回执（2026-08-18）

- 全量 `本机 pytest -q -rs`：**599 passed, 27 skipped, 0 failed**（28.80 秒）；相对 Phase 1-3 基线新增 10 个 adapter、Linux mock、降级隐藏与启动脚本契约测试。
- darwin 一键启动冒烟：临时 HOME 下执行 `./start.sh --no-open --port 18994`；Canvas Studio **475 modules** 构建通过，服务 ready；API 返回 **8 tasks / 2 projects**、`local_integrations=[]`、四类 optional UI flags 均为 `false`，DEMO-001 关联 Canvas 返回 **4 nodes**；无 Traceback 或 FileNotFoundError。
- 跨平台静态门：`bash -n start.sh`、`git diff --check` 通过；`scan-docs.py` 与其他业务 Python/shell 文件对 `/usr/bin/open`、`/usr/bin/osascript`、`/usr/sbin/scutil`、`networksetup` 的直接调用为 **0**，命令只存在于 `platform_adapter.py`；Python/shell/JSON 运行路径对 launchd/codesign 为 **0**。
- 11 个 `AUDIT-L*` 均存在独立 `已处理 @1-4` 回销。Linux 结论仅来自 mock 单测，未宣称实机验证。
- 仓库边界：冷启动仓 `remote=0`；本卡未对源仓执行写操作。收口只读观察源仓 HEAD 仍为 `kanban-personal=d205445`、`canvas-studio=ac2a20c`；两边既有工作树分别为 72 与 5 条状态，本卡不处置也不宣称 clean。

## Phase 1-5 安全默认 v1 回销（KAN-1755）

本节逐条回销 Phase 0 审计第 6 节。公共运行时保持 local-first；任何非 loopback
监听都必须显式设置 `bind_host` 与 `allowed_hosts`，启动时输出高风险警告，但这不
代表远程部署已经安全。远程真实认证、TLS `Secure` cookie、CSRF/反代验证仍是发布
前独立门槛，本阶段明确不支持、不误报为已解决。

| 审计位 | Phase 1-5 回销 |
|---|---|
| `AUDIT-L739` | **已清除 @1-5**：固定答案 quiz 不再是默认；首次安全登录生成随机 token，写入 gitignored 的仓内普通文件并强制 `0600`，比较使用 `compare_digest`；quiz 仅保留显式旧兼容模式 |
| `AUDIT-L740`, `AUDIT-L741` | **已清除 @1-3、复核 @1-5**：可信根默认仅仓根与 `demo/`；打开文件和 AI workdir 越界统一 403，并写 `[security] denied` |
| `AUDIT-L742` | **已清除 @1-2、复核 @1-5**：Canvas 保存 actor 来自认证会话/角色配置，无个人 actor 回流 |
| `AUDIT-L743` | **远程门禁 @1-5**：loopback 会话保持 `HttpOnly` + `SameSite=Strict`；远程 TLS/Secure cookie/CSRF 未实现，因此 README/DEPLOYMENT 明确禁止把当前 profile 直接用于公网 |
| `AUDIT-L744` | **已锁定 @1-5**：`bind_host=127.0.0.1` 为代码和 example/demo 双重默认；非 loopback 只能显式配置并触发警告 |
| `AUDIT-L745`, `AUDIT-L747`, `AUDIT-L753` | **已锁定 @1-5**：example 的 `local_bypass=false`、`autologin=false`；tracked demo 的 bypass 带显眼风险注释且只绑定 loopback；fallback 无过期只存在于该显式 opt-in 路径 |
| `AUDIT-L746`, `AUDIT-L750` | **已加固 @1-5**：全部普通 GET 先校验 Host（含逗号/畸形 Host）；POST/PUT/DELETE 统一走 Host/Origin guard；无 Origin 仅保留给 loopback CLI，不充当认证 |
| `AUDIT-L748`, `AUDIT-L749` | **已加固 @1-5**：webhook 是唯一同源 guard 例外且仍强制 HMAC；只读取 `X-Hub-Signature-256`、只接受 SHA-256，SHA-1 兼容已移除 |
| `AUDIT-L751`, `AUDIT-L752` | **未迁入 / 无运行位 @1-5**：两个源仓 actor 契约测试不在冷启动仓；当前 Canvas 服务代码和已迁测试无个人 actor |
| `AUDIT-L754`, `AUDIT-L755` | **已声明 @1-5**：受支持拓扑是 loopback 后端同源托管 `/canvas/` 与 `/api/`；Canvas README 明示 dev proxy 不是安全边界，独立/远程部署不在本阶段支持范围 |

端口移交账同时回销：`/api/health` 提供稳定产品指纹；`start.sh` 只有在指纹精确匹配
时才复用已占用端口，否则报错退出。single-instance 集成测试显式注入独立
`KANBAN_REPO_ROOT` / `KANBAN_CONFIG` 并使用随机端口；pytest 每例清理内存态，另将
`_ai_runs` 半成品状态按 running 容错，消除了顺序污染。

### Phase 1-5 验证回执（2026-08-18）

- 最终全量随机顺序三连跑（`pytest-random-order`，seed `1755` / `1756` / `1757`）：每轮 **608 passed, 27 skipped, 0 failed**，分别 29.51 / 29.59 / 29.25 秒。
- 定向安全/端口/路由/git-sync 测试：**73 passed, 0 failed**；覆盖 token 首启与 `0600`、token 路径越界/符号链接拒绝、quiz 默认关闭、恶意/逗号 Host GET、恶意 Host POST、Origin、webhook HMAC-SHA256 与 SHA-1 拒绝、route guard、可信根 403+日志、产品指纹与随机端口 single-instance。
- 黑盒随机端口冒烟：恶意 Host GET=403、逗号 Host GET=403、恶意 Host POST=403、`/etc/hosts` 越界打开=403；`/api/health`=200 且指纹匹配；`/api/data`=200 且返回 8 张虚构卡；demo Canvas=200；日志实际出现四条 `[security] denied`。
- 端口复用实测：同产品实例二次 `start.sh` 通过指纹后复用；普通 `python -m http.server` 占用端口时明确输出 `Refusing to reuse it` 并退出。两处随机测试端口收口后均已关闭，未留下 token、pidfile 或测试进程。
- 代码/配置静态门：Python 编译、`bash -n start.sh`、前端 `node --check`、两份 JSON parse 与 `git diff --check` 均通过；改动文件未出现个人路径/姓名/handle 回流。
- 源仓零触碰：本卡只读取 Phase 0 审计报告作逐条对账，没有向 `kanban-personal` 或 `canvas-studio` 源仓写入；所有改动仅在本冷启动仓。

## 开源收窄二：接力区与独立复核路径（KAN-1759）

公开 demo 的任务卡不在历史 `project/<项目>/` 布局下。本卡将 Review Cycle、
comments ledger、card lineage、任务详情的项目名推导、新卡落点和 task-canvas
清单统一到部署配置的 `scan_dirs`。Review 账本仍只增并与原卡同项目，
公开 demo 落在 `demo/projects/<slug>/.reviews/<task-id>/ledger.jsonl`；路径越界、
非 Markdown 或非 `scan_dirs` 卡仍失败关闭。上传图片、卡详情和 Git 变更任务 ID
识别中同类的 `project/` 主路径假设也已对齐；Canvas 的历史 `project/`
分支本来就有 `data_root` demo 分支，team adapter 中剩余的 `project/` 判断属于
其外部团队仓 schema，不参与公开 demo 任务路径。

卡详情「下一步接力」现在只保留「派生子任务」。「晋升为场景」、「用 AI
填充场景草稿」、「查看晋升场景」、「交接团队」和「扫前沿对标」的 UI、
前端 API 与 detail-module 转发链已删除。相应公开 HTTP 路由中央注册表摘除：
`/api/promote*`、`/api/spawn-prior-art`、`/api/team/handoff*` 全部返回
JSON 404。团队同步和场景文本的内部 library 仍作为默认关闭的兼容/辅助层保留，
不再暴露为公开卡详情动作。

涉删端点测试已同步：`test_task_endpoint.py` 删除 5 组 promote 行为测试
（其中 slug 拒绝为 3 参数行）；`test_open_llm_promote_fill.py` 删除 preview
写入与非 draft 拒绝的 HTTP 测试，保留不经路由的脱敏/正文规范化单测。
`test_route_registry.py` 现对 8 条退役路由逐一断言 JSON 404；新增 demo Review、
comments/lineage sidecar、子卡落点、项目名推导与接力区单按钮契约。

### KAN-1759 验证回执（2026-08-18）

- 固定顺序全量 `CI=true 本机 pytest -q -rs --disable-warnings`：
  **600 passed, 27 skipped, 0 failed**（28.56 秒）；27 个 skip 仍是未安装 Playwright
  或未迁入的可选 governance 路径，无新增 skip。
- 模块与构建门：3 个受影响 ES module `node --check` 通过，4 个受影响
  Python 模块编译通过，`git diff --check` 通过；Canvas Studio `npm run build`
  **475 modules** 通过。
- 隔离端口 `18996` 的三面 HTTP 旅程：首页、`literature-review` Project Map
  和 DEMO-001 Card Canvas 页均为 **200**。Card Canvas 按固定顺序 load → save
  → REF 复核：`kanban.canvas/v1`、4 个 REF、保存 `ok=true`、重载 200、
  `missing_refs=[]`。实测产生的 Canvas 格式化/台账运行态已清理，fixture 恢复到
  测试前字节。
- demo 子卡实测：从 DEMO-001 等价调用「派生子任务」后，API 创建
  `LIT-1`，路径为 `demo/projects/literature-review/LIT-1_...md`，`project`、
  `workdir` 与 `promoted_from=DEMO-001` 均正确；实测卡与运行 sidecar 已清理，
  demo 仍保持 8 张固定卡。
- demo 独立复核实测：`GET /api/review-cycle` 先返回 idle，无「评审运行受阻」；
  `POST /api/review-cycle/start` 返回 **200** 并将 `review_claude` 运行
  `9bca39f4` 放入 AI 队列，队列状态为 `running`；随后按验收边界调用 kill，
  最终状态 `killed`。本次不等待完整评审，评审 ledger/队列运行态已清理。
- 8 条退役 HTTP 路由在实际 demo 服务上均返回
  `{"ok": false, "error": "Not Found"}` + **404**。
- 源仓零触碰：所有写入仅发生在 `ai-dispatch-desk`；未向来源
  `kanban-personal` / `canvas-studio` 发出写命令。Claude 桌面浏览器的点击旅程与截图
  仍是本卡的最终独立验收门，本回执不冒充该截图已完成。

## 逐文件清单

| 仓内文件 | 来源仓与源路径 | 搬运方式 | Phase 0 审计交叉 |
|---|---|---|---|
| `.gitignore` | `kanban-personal:.gitignore` + `canvas-studio:.gitignore` | 待改写（合并并强化凭证/运行态外置规则） | 新建文件，不适用 |
| `.kanban.scan-allowlist.json` | KAN-1753 | 新建：限定 demo 扫描根 | 新建文件，不适用 |
| `LICENSE` | GNU AGPL-3.0 全文；与本地既有 AGPL-3.0 副本核对一致 | 原样 | 新增许可文件，不适用 |
| `PROVENANCE.md` | KAN-1751 | 待改写（本卡新建、自描述） | 新建文件，不适用 |
| `README.md` | KAN-1751 | 待改写（本卡新建占位） | 新建文件，不适用 |
| `start.sh` | KAN-1753/KAN-1754 | 新建并改写：公开跨平台冷启动入口 | 新建文件，不适用 |
| `demo/kanban.demo.config.json` | KAN-1753 | 新建：仓内 demo 部署配置 | 新建文件，不适用 |
| `canvas-studio/README.md` | `canvas-studio:README.md` | 待改写（仅新建骨架，未复制原正文） | 新建骨架，不适用 |
| `kanban/README.md` | `kanban-personal:shared/toolkit/kanban/README.md` | 待改写（仅新建骨架，未复制原正文） | 新建骨架，不适用 |
| `canvas-studio/eslint.config.js` | `canvas-studio:eslint.config.js` | 原样 | 未命中 |
| `canvas-studio/index.html` | `canvas-studio:index.html` | 原样 | 未命中 |
| `canvas-studio/package-lock.json` | `canvas-studio:package-lock.json` | 原样 | 未命中 |
| `canvas-studio/package.json` | `canvas-studio:package.json` | 原样 | 未命中 |
| `canvas-studio/src/App.tsx` | `canvas-studio:src/App.tsx` | 原样 | 未命中 |
| `canvas-studio/src/components/BoardLink.tsx` | `canvas-studio:src/components/BoardLink.tsx` | 原样 | 未命中 |
| `canvas-studio/src/components/Canvas.tsx` | `canvas-studio:src/components/Canvas.tsx` | 待改写（Phase 1-2/1-3） | AUDIT-L189, AUDIT-L416 |
| `canvas-studio/src/components/SystemAlertBadge.tsx` | `canvas-studio:src/components/SystemAlertBadge.tsx` | 选择性补拷 @1-3；补齐既有调用方构建依赖 | Phase 0 清单未列入冷启动搬运文件 |
| `canvas-studio/src/components/CanvasRail.tsx` | `canvas-studio:src/components/CanvasRail.tsx` | 原样 | 未命中 |
| `canvas-studio/src/components/CardPalette.tsx` | `canvas-studio:src/components/CardPalette.tsx` | 待改写（Phase 1-2/1-3） | AUDIT-L190 |
| `canvas-studio/src/components/ConversationMapView.tsx` | `canvas-studio:src/components/ConversationMapView.tsx` | 原样 | 未命中 |
| `canvas-studio/src/components/ConversationProjectGraphView.tsx` | `canvas-studio:src/components/ConversationProjectGraphView.tsx` | 原样 | 未命中 |
| `canvas-studio/src/components/canvas-handles.css` | `canvas-studio:src/components/canvas-handles.css` | 待改写（Phase 1-2/1-3） | AUDIT-L415 |
| `canvas-studio/src/components/canvasFocus.ts` | `canvas-studio:src/components/canvasFocus.ts` | 原样 | 未命中 |
| `canvas-studio/src/components/conversationNavigator.ts` | `canvas-studio:src/components/conversationNavigator.ts` | 原样 | 未命中 |
| `canvas-studio/src/components/dragTypes.ts` | `canvas-studio:src/components/dragTypes.ts` | 原样内容（EOF 空行归一化） | 未命中 |
| `canvas-studio/src/components/kan851.css` | `canvas-studio:src/components/kan851.css` | 原样 | 未命中 |
| `canvas-studio/src/components/nodes/DialogueNode.tsx` | `canvas-studio:src/components/nodes/DialogueNode.tsx` | 原样 | 未命中 |
| `canvas-studio/src/components/nodes/LinkNode.tsx` | `canvas-studio:src/components/nodes/LinkNode.tsx` | 待改写（Phase 1-2/1-3） | AUDIT-L417 |
| `canvas-studio/src/components/nodes/NoteNode.tsx` | `canvas-studio:src/components/nodes/NoteNode.tsx` | 待改写（Phase 1-2/1-3） | AUDIT-L191 |
| `canvas-studio/src/components/nodes/RefNode.tsx` | `canvas-studio:src/components/nodes/RefNode.tsx` | 原样 | 未命中 |
| `canvas-studio/src/components/refDisplay.ts` | `canvas-studio:src/components/refDisplay.ts` | 原样 | 未命中 |
| `canvas-studio/src/core/contextGraph.ts` | `canvas-studio:src/core/contextGraph.ts` | 原样 | 未命中 |
| `canvas-studio/src/core/dialoguePointer.ts` | `canvas-studio:src/core/dialoguePointer.ts` | 原样 | 未命中 |
| `canvas-studio/src/main.tsx` | `canvas-studio:src/main.tsx` | 原样 | 未命中 |
| `canvas-studio/src/services/canvasApi.ts` | `canvas-studio:src/services/canvasApi.ts` | 待改写（Phase 1-2/1-3） | AUDIT-L192, AUDIT-L742, AUDIT-L754 |
| `canvas-studio/src/shims/i18n.ts` | `canvas-studio:src/shims/i18n.ts` | 原样 | 未命中 |
| `canvas-studio/src/store/canvasStore.ts` | `canvas-studio:src/store/canvasStore.ts` | 原样 | 未命中 |
| `canvas-studio/src/styles.css` | `canvas-studio:src/styles.css` | 待改写（Phase 1-2/1-3） | AUDIT-L193 |
| `canvas-studio/src/types/canvas.ts` | `canvas-studio:src/types/canvas.ts` | 待改写（Phase 1-2/1-3） | AUDIT-L418 |
| `canvas-studio/src/vite-env.d.ts` | `canvas-studio:src/vite-env.d.ts` | 原样 | 未命中 |
| `canvas-studio/tsconfig.app.json` | `canvas-studio:tsconfig.app.json` | 原样 | 未命中 |
| `canvas-studio/tsconfig.json` | `canvas-studio:tsconfig.json` | 原样 | 未命中 |
| `canvas-studio/tsconfig.node.json` | `canvas-studio:tsconfig.node.json` | 原样 | 未命中 |
| `canvas-studio/vite.config.ts` | `canvas-studio:vite.config.ts` | 原样 | 未命中 |
| `kanban/.kanban.config.example.json` | `kanban-personal:.kanban.config.example.json` | 待改写（Phase 1-2/1-3） | AUDIT-L118, AUDIT-L141, AUDIT-L179, AUDIT-L203, AUDIT-L421, AUDIT-L463, AUDIT-L526, AUDIT-L529, AUDIT-L541, AUDIT-L545, AUDIT-L569, AUDIT-L716, AUDIT-L740, AUDIT-L745 |
| `kanban/DEPLOYMENT.md` | `kanban-personal:shared/toolkit/kanban/DEPLOYMENT.md` | 待改写（Phase 1-2/1-3） | AUDIT-L114, AUDIT-L181, AUDIT-L404, AUDIT-L443, AUDIT-L478, AUDIT-L608, AUDIT-L721 |
| `kanban/agent_mail_maintenance.py` | `kanban-personal:shared/toolkit/kanban/agent_mail_maintenance.py` | 原样 | 未命中 |
| `kanban/ai_run_guard.py` | `kanban-personal:shared/toolkit/kanban/ai_run_guard.py` | 原样 | 未命中 |
| `kanban/attention_queue.py` | `kanban-personal:shared/toolkit/kanban/attention_queue.py` | 原样 | 未命中 |
| `kanban/backfill_watcher_record_doc_type.py` | `kanban-personal:shared/toolkit/kanban/backfill_watcher_record_doc_type.py` | 待改写（Phase 1-2/1-3） | AUDIT-L257, AUDIT-L534 |
| `kanban/build_shadow_batch.py` | `kanban-personal:shared/toolkit/kanban/build_shadow_batch.py` | 待改写（Phase 1-2/1-3） | AUDIT-L258 |
| `kanban/canvas_event_ledger.py` | `kanban-personal:shared/toolkit/kanban/canvas_event_ledger.py` | 原样 | 未命中 |
| `kanban/canvas_seed.py` | `kanban-personal:shared/toolkit/kanban/canvas_seed.py` | 待改写（Phase 1-2/1-3） | AUDIT-L259, AUDIT-L476 |
| `kanban/comment_import.py` | `kanban-personal:shared/toolkit/kanban/comment_import.py` | 原样 | 未命中 |
| `kanban/conversation_map.py` | `kanban-personal:shared/toolkit/kanban/conversation_map.py` | 待改写（Phase 1-2/1-3） | AUDIT-L129, AUDIT-L166, AUDIT-L262, AUDIT-L573 |
| `kanban/conversation_project_graph.py` | `kanban-personal:shared/toolkit/kanban/conversation_project_graph.py` | 原样 | 未命中 |
| `kanban/discover_event_candidates.py` | `kanban-personal:shared/toolkit/kanban/discover_event_candidates.py` | 原样 | 未命中 |
| `kanban/evaluate_event_discovery.py` | `kanban-personal:shared/toolkit/kanban/evaluate_event_discovery.py` | 原样 | 未命中 |
| `kanban/feishu_notify.py` | `kanban-personal:shared/toolkit/kanban/feishu_notify.py` | 待改写（Phase 1-2/1-3） | AUDIT-L479 |
| `kanban/git-sync.py` | `kanban-personal:shared/toolkit/kanban/git-sync.py` | 待改写（Phase 1-2/1-3） | AUDIT-L480, AUDIT-L749 |
| `kanban/githooks/pre-commit` | `kanban-personal:shared/toolkit/kanban/githooks/pre-commit` | 原样 | 未命中 |
| `kanban/kanban.html` | `kanban-personal:shared/toolkit/kanban/kanban.html` | 待改写（Phase 1-2/1-3） | AUDIT-L264, AUDIT-L609 |
| `kanban/kanban.sh` | `kanban-personal:kanban.sh` | 待改写（Phase 1-2/1-3） | AUDIT-L542, AUDIT-L717 |
| `kanban/ledger_query.py` | `kanban-personal:shared/toolkit/kanban/ledger_query.py` | 原样 | 未命中 |
| `kanban/maintenance_cli.py` | `kanban-personal:shared/toolkit/kanban/maintenance_cli.py` | 待改写（Phase 1-2/1-3） | AUDIT-L266 |
| `kanban/mario-game-projection-v1.schema.json` | `kanban-personal:shared/toolkit/kanban/mario-game-projection-v1.schema.json` | 原样 | 未命中 |
| `kanban/mario-strategy-map-v1.schema.json` | `kanban-personal:shared/toolkit/kanban/mario-strategy-map-v1.schema.json` | 原样 | 未命中 |
| `kanban/mario-unit-v1.schema.json` | `kanban-personal:shared/toolkit/kanban/mario-unit-v1.schema.json` | 原样 | 未命中 |
| `kanban/mario_game_projection.py` | `kanban-personal:shared/toolkit/kanban/mario_game_projection.py` | 原样 | 未命中 |
| `kanban/mario_strategy_map.py` | `kanban-personal:shared/toolkit/kanban/mario_strategy_map.py` | 原样 | 未命中 |
| `kanban/materialize_approved.py` | `kanban-personal:shared/toolkit/kanban/materialize_approved.py` | 待改写（Phase 1-2/1-3） | AUDIT-L273 |
| `kanban/materialize_mario_game_projection.py` | `kanban-personal:shared/toolkit/kanban/materialize_mario_game_projection.py` | 原样 | 未命中 |
| `kanban/materialize_mario_unit.py` | `kanban-personal:shared/toolkit/kanban/materialize_mario_unit.py` | 原样 | 未命中 |
| `kanban/migrate_filenames.py` | `kanban-personal:shared/toolkit/kanban/migrate_filenames.py` | 原样 | 未命中 |
| `kanban/morning_batch.py` | `kanban-personal:shared/toolkit/kanban/morning_batch.py` | 已删除（removed@KAN-1758） | AUDIT-L275 |
| `kanban/network_doctor_panel.py` | `kanban-personal:shared/toolkit/kanban/network_doctor_panel.py` | 待改写（Phase 1-2/1-3） | AUDIT-L574 |
| `kanban/platform_adapter.py` | KAN-1754 | 新建：darwin/linux/unsupported 薄平台边界 | 新建文件；回销 AUDIT-L710, AUDIT-L715, AUDIT-L719 |
| `kanban/plan_batch.py` | `kanban-personal:shared/toolkit/kanban/plan_batch.py` | 待改写（Phase 1-2/1-3） | AUDIT-L95, AUDIT-L169, AUDIT-L556, AUDIT-L575 |
| `kanban/project_action_projection.py` | `kanban-personal:shared/toolkit/kanban/project_action_projection.py` | 待改写（Phase 1-2/1-3） | AUDIT-L276 |
| `kanban/project_canvas_reorganize.py` | `kanban-personal:shared/toolkit/kanban/project_canvas_reorganize.py` | 原样 | 未命中 |
| `kanban/project_conversations.py` | `kanban-personal:shared/toolkit/kanban/project_conversations.py` | 待改写（Phase 1-2/1-3） | AUDIT-L709 |
| `kanban/project_map.py` | `kanban-personal:shared/toolkit/kanban/project_map.py` | 原样 | 未命中 |
| `kanban/project_state_projection.py` | `kanban-personal:shared/toolkit/kanban/project_state_projection.py` | 待改写（Phase 1-2/1-3） | AUDIT-L280 |
| `kanban/projectctl.py` | `kanban-personal:shared/toolkit/kanban/projectctl.py` | 待改写（Phase 1-2/1-3） | AUDIT-L281 |
| `kanban/promote_flow.py` | `kanban-personal:shared/toolkit/kanban/promote_flow.py` | 待改写（Phase 1-2/1-3） | AUDIT-L535 |
| `kanban/real_projects.py` | `kanban-personal:shared/toolkit/kanban/real_projects.py` | 待改写（Phase 1-2/1-3） | AUDIT-L287 |
| `kanban/render_event_discovery_review.py` | `kanban-personal:shared/toolkit/kanban/render_event_discovery_review.py` | 待改写（Phase 1-2/1-3） | AUDIT-L289 |
| `kanban/render_mario_game_map.py` | `kanban-personal:shared/toolkit/kanban/render_mario_game_map.py` | 原样 | 未命中 |
| `kanban/render_mario_strategy_map.py` | `kanban-personal:shared/toolkit/kanban/render_mario_strategy_map.py` | 待改写（Phase 1-2/1-3） | AUDIT-L290 |
| `kanban/requirements.txt` | `kanban-personal:shared/toolkit/kanban/requirements.txt` | 原样 | 未命中 |
| `kanban/review_cycle.py` | `kanban-personal:shared/toolkit/kanban/review_cycle.py` | 原样 | 未命中 |
| `kanban/scan-docs.py` | `kanban-personal:shared/toolkit/kanban/scan-docs.py` | 待改写（Phase 1-2/1-3；Phase 1-1 已移除默认真实成员绑定） | AUDIT-L97, AUDIT-L131, AUDIT-L171, AUDIT-L291, AUDIT-L386, AUDIT-L396, AUDIT-L446, AUDIT-L482, AUDIT-L528, AUDIT-L536, AUDIT-L543, AUDIT-L551, AUDIT-L557, AUDIT-L564, AUDIT-L576, AUDIT-L710, AUDIT-L715, AUDIT-L719, AUDIT-L739, AUDIT-L741, AUDIT-L743, AUDIT-L744, AUDIT-L746, AUDIT-L747, AUDIT-L748, AUDIT-L750, AUDIT-L753 |
| `kanban/server_instance.py` | `kanban-personal:shared/toolkit/kanban/server_instance.py` | 原样 | 未命中 |
| `kanban/session_evidence_adapter.py` | `kanban-personal:shared/toolkit/kanban/session_evidence_adapter.py` | 原样 | 未命中 |
| `kanban/setup-deps.sh` | `kanban-personal:shared/toolkit/kanban/setup-deps.sh` | 原样 | 未命中 |
| `kanban/skill_invocation.py` | `kanban-personal:shared/toolkit/kanban/skill_invocation.py` | 待改写（Phase 1-2/1-3） | AUDIT-L483 |
| `kanban/static/kanban/ai-runtime.css` | `kanban-personal:shared/toolkit/kanban/static/kanban/ai-runtime.css` | 已删除（removed@KAN-1758） | AUDIT-L292 |
| `kanban/static/kanban/console.css` | `kanban-personal:shared/toolkit/kanban/static/kanban/console.css` | 待改写（Phase 1-2/1-3） | AUDIT-L293 |
| `kanban/static/kanban/design-tokens.css` | `kanban-personal:shared/toolkit/kanban/static/kanban/design-tokens.css` | 原样 | 未命中 |
| `kanban/static/kanban/kanban.css` | `kanban-personal:shared/toolkit/kanban/static/kanban/kanban.css` | 待改写（Phase 1-2/1-3） | AUDIT-L294 |
| `kanban/static/kanban/main.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/main.js` | 待改写（Phase 1-2/1-3） | AUDIT-L295, AUDIT-L537 |
| `kanban/static/kanban/modules/ai-queue.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/ai-queue.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/ai-threads.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/ai-threads.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/ai.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/ai.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/api.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/api.js` | 待改写（Phase 1-2/1-3） | AUDIT-L296 |
| `kanban/static/kanban/modules/auth.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/auth.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/automation-schedule.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/automation-schedule.js` | 已删除（removed@KAN-1758） | 未命中 |
| `kanban/static/kanban/modules/header-status.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/header-status.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/markdown.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/markdown.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/render-board-console-cards.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-board-console-cards.js` | 待改写（Phase 1-2/1-3） | AUDIT-L297 |
| `kanban/static/kanban/modules/render-board-console-runtime.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-board-console-runtime.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/render-board-console.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-board-console.js` | 待改写（Phase 1-2/1-3） | AUDIT-L298 |
| `kanban/static/kanban/modules/render-board-core.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-board-core.js` | 待改写（Phase 1-2/1-3） | AUDIT-L299, AUDIT-L447, AUDIT-L538 |
| `kanban/static/kanban/modules/render-board-duty.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-board-duty.js` | 待改写（Phase 1-2/1-3） | AUDIT-L300 |
| `kanban/static/kanban/modules/render-board.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-board.js` | 待改写（Phase 1-2/1-3） | AUDIT-L301 |
| `kanban/static/kanban/modules/render-detail-actions.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-detail-actions.js` | 待改写（Phase 1-2/1-3） | AUDIT-L302, AUDIT-L448, AUDIT-L539 |
| `kanban/static/kanban/modules/render-detail-view.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-detail-view.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/render-detail.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-detail.js` | 原样 | 未命中 |
| `kanban/static/kanban/modules/render-projects.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-projects.js` | 待改写（Phase 1-2/1-3） | AUDIT-L98, AUDIT-L304 |
| `kanban/static/kanban/modules/render-runtime.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/render-runtime.js` | 已删除（removed@KAN-1758） | AUDIT-L449, AUDIT-L540 |
| `kanban/static/kanban/modules/review-cycle.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/review-cycle.js` | 待改写（Phase 1-2/1-3） | AUDIT-L306 |
| `kanban/static/kanban/modules/ui.js` | `kanban-personal:shared/toolkit/kanban/static/kanban/modules/ui.js` | 原样 | 未命中 |
| `kanban/static/kanban/real-projects.css` | `kanban-personal:shared/toolkit/kanban/static/kanban/real-projects.css` | 原样 | 未命中 |
| `kanban/studio_static.py` | `kanban-personal:shared/toolkit/kanban/studio_static.py` | 待改写（Phase 1-2/1-3） | AUDIT-L544 |
| `kanban/task_canvas.py` | `kanban-personal:shared/toolkit/kanban/task_canvas.py` | 原样 | 未命中 |
| `kanban/task_document_links.py` | `kanban-personal:shared/toolkit/kanban/task_document_links.py` | 原样内容（EOF 空行归一化） | 未命中 |
| `kanban/task_id_allocator.py` | `kanban-personal:shared/toolkit/kanban/task_id_allocator.py` | 原样 | 未命中 |
| `kanban/task_scan_cache.py` | `kanban-personal:shared/toolkit/kanban/task_scan_cache.py` | 原样 | 未命中 |
| `kanban/test_acceptance_section_endpoints.py` | `kanban-personal:shared/toolkit/kanban/test_acceptance_section_endpoints.py` | 原样 | 未命中 |
| `kanban/test_agent_mail_maintenance.py` | `kanban-personal:shared/toolkit/kanban/test_agent_mail_maintenance.py` | 原样 | 未命中 |
| `kanban/test_ai_cwd_coercion.py` | `kanban-personal:shared/toolkit/kanban/test_ai_cwd_coercion.py` | 原样 | 未命中 |
| `kanban/test_ai_fork_lifecycle.py` | `kanban-personal:shared/toolkit/kanban/test_ai_fork_lifecycle.py` | 原样 | 未命中 |
| `kanban/test_ai_profile_defaults.py` | `kanban-personal:shared/toolkit/kanban/test_ai_profile_defaults.py` | 待改写（Phase 1-2/1-3） | AUDIT-L99, AUDIT-L172, AUDIT-L642 |
| `kanban/test_ai_queue_durability.py` | `kanban-personal:shared/toolkit/kanban/test_ai_queue_durability.py` | 原样 | 未命中 |
| `kanban/test_ai_results_metadata.py` | `kanban-personal:shared/toolkit/kanban/test_ai_results_metadata.py` | 原样 | 未命中 |
| `kanban/test_ai_run_guard.py` | `kanban-personal:shared/toolkit/kanban/test_ai_run_guard.py` | 待改写（Phase 1-2/1-3） | AUDIT-L484 |
| `kanban/test_ai_thread_tree.py` | `kanban-personal:shared/toolkit/kanban/test_ai_thread_tree.py` | 待改写（Phase 1-2/1-3） | AUDIT-L309 |
| `kanban/test_archive_done.py` | `kanban-personal:shared/toolkit/kanban/test_archive_done.py` | 原样 | 未命中 |
| `kanban/test_archived_project_lifecycle.py` | `kanban-personal:shared/toolkit/kanban/test_archived_project_lifecycle.py` | 原样内容（EOF 空行归一化） | 未命中 |
| `kanban/test_attention_queue.py` | `kanban-personal:shared/toolkit/kanban/test_attention_queue.py` | 原样 | 未命中 |
| `kanban/test_auth_sessions.py` | `kanban-personal:shared/toolkit/kanban/test_auth_sessions.py` | 待改写（Phase 1-2/1-3） | AUDIT-L310, AUDIT-L485 |
| `kanban/test_autologin_team_kanban.py` | `kanban-personal:shared/toolkit/kanban/test_autologin_team_kanban.py` | 待改写（Phase 1-2/1-3） | AUDIT-L311 |
| `kanban/test_automation_control_plane.py` | `kanban-personal:shared/toolkit/kanban/test_automation_control_plane.py` | 已删除（removed@KAN-1758） | AUDIT-L312, AUDIT-L613, AUDIT-L643, AUDIT-L727 |
| `kanban/test_backfill_watcher_record_doc_type.py` | `kanban-personal:shared/toolkit/kanban/test_backfill_watcher_record_doc_type.py` | 待改写（Phase 1-2/1-3） | AUDIT-L614 |
| `kanban/test_canvas_ref_resolution.py` | `kanban-personal:shared/toolkit/kanban/test_canvas_ref_resolution.py` | 原样 | 未命中 |
| `kanban/test_card_ai_note.py` | `kanban-personal:shared/toolkit/kanban/test_card_ai_note.py` | 原样 | 未命中 |
| `kanban/test_card_lineage.py` | `kanban-personal:shared/toolkit/kanban/test_card_lineage.py` | 待改写（Phase 1-2/1-3） | AUDIT-L313 |
| `kanban/test_chain_health_score.py` | `kanban-personal:shared/toolkit/kanban/test_chain_health_score.py` | 待改写（Phase 1-2/1-3） | AUDIT-L314 |
| `kanban/test_claude_auth_retry.py` | `kanban-personal:shared/toolkit/kanban/test_claude_auth_retry.py` | 原样 | 未命中 |
| `kanban/test_cli_path.py` | `kanban-personal:shared/toolkit/kanban/test_cli_path.py` | 原样 | 未命中 |
| `kanban/test_comment_import.py` | `kanban-personal:shared/toolkit/kanban/test_comment_import.py` | 待改写（Phase 1-2/1-3） | AUDIT-L316 |
| `kanban/test_comment_quote_frontend.py` | `kanban-personal:shared/toolkit/kanban/test_comment_quote_frontend.py` | 待改写（Phase 1-2/1-3） | AUDIT-L317 |
| `kanban/test_console_routing.py` | `kanban-personal:shared/toolkit/kanban/test_console_routing.py` | 待改写（Phase 1-2/1-3） | AUDIT-L319 |
| `kanban/test_conversation_map.py` | `kanban-personal:shared/toolkit/kanban/test_conversation_map.py` | 待改写（Phase 1-2/1-3） | AUDIT-L320 |
| `kanban/test_conversation_project_graph.py` | `kanban-personal:shared/toolkit/kanban/test_conversation_project_graph.py` | 待改写（Phase 1-2/1-3） | AUDIT-L321 |
| `kanban/test_decision_log_hook.py` | `kanban-personal:shared/toolkit/kanban/test_decision_log_hook.py` | 待改写（Phase 1-2/1-3） | AUDIT-L322 |
| `kanban/test_detail_overlay.py` | `kanban-personal:shared/toolkit/kanban/test_detail_overlay.py` | 原样 | 未命中 |
| `kanban/test_detail_template.py` | `kanban-personal:shared/toolkit/kanban/test_detail_template.py` | 原样 | 未命中 |
| `kanban/test_documents_doctor_trial_tools.py` | `kanban-personal:shared/toolkit/kanban/test_documents_doctor_trial_tools.py` | 待改写（Phase 1-2/1-3） | AUDIT-L323, AUDIT-L451, AUDIT-L615, AUDIT-L672, AUDIT-L683 |
| `kanban/test_dynamic_boards.py` | `kanban-personal:shared/toolkit/kanban/test_dynamic_boards.py` | 原样 | 未命中 |
| `kanban/test_e2e_task_detail_flow.py` | `kanban-personal:shared/toolkit/kanban/test_e2e_task_detail_flow.py` | 原样 | 未命中 |
| `kanban/test_feishu_notify.py` | `kanban-personal:shared/toolkit/kanban/test_feishu_notify.py` | 待改写（Phase 1-2/1-3） | AUDIT-L325, AUDIT-L486 |
| `kanban/test_frontend_dynamic_surfaces.py` | `kanban-personal:shared/toolkit/kanban/test_frontend_dynamic_surfaces.py` | 待改写（Phase 1-2/1-3） | AUDIT-L326, AUDIT-L616, AUDIT-L684 |
| `kanban/test_git_hygiene.py` | `kanban-personal:shared/toolkit/kanban/test_git_hygiene.py` | 待改写（Phase 1-2/1-3） | AUDIT-L406, AUDIT-L645, AUDIT-L673 |
| `kanban/test_git_sync.py` | `kanban-personal:shared/toolkit/kanban/test_git_sync.py` | 待改写（Phase 1-2/1-3） | AUDIT-L407, AUDIT-L487 |
| `kanban/test_governance_healthcheck_chain.py` | `kanban-personal:shared/toolkit/kanban/test_governance_healthcheck_chain.py` | 原样 | 未命中 |
| `kanban/test_governance_matrix.py` | `kanban-personal:shared/toolkit/kanban/test_governance_matrix.py` | 待改写（Phase 1-2/1-3） | AUDIT-L646, AUDIT-L674, AUDIT-L685, AUDIT-L696 |
| `kanban/test_governance_probe.py` | `kanban-personal:shared/toolkit/kanban/test_governance_probe.py` | 待改写（Phase 1-2/1-3） | AUDIT-L408, AUDIT-L452, AUDIT-L488, AUDIT-L617, AUDIT-L647 |
| `kanban/test_governance_result_card.py` | `kanban-personal:shared/toolkit/kanban/test_governance_result_card.py` | 待改写（Phase 1-2/1-3） | AUDIT-L100, AUDIT-L327 |
| `kanban/test_grill_lint.py` | `kanban-personal:shared/toolkit/kanban/test_grill_lint.py` | 待改写（Phase 1-2/1-3） | AUDIT-L328 |
| `kanban/test_header_status.py` | `kanban-personal:shared/toolkit/kanban/test_header_status.py` | 原样 | 未命中 |
| `kanban/test_owner_action_ledger.py` | `kanban-personal:shared/toolkit/kanban/<personal-owner>-action-ledger-test` | 已清除 @1-2（源文件名含个人 owner，公开账中脱敏） | AUDIT-L329 |
| `kanban/test_km_chain_data.py` | `kanban-personal:shared/toolkit/kanban/test_km_chain_data.py` | 原样 | 未命中 |
| `kanban/test_markdown_styling.py` | `kanban-personal:shared/toolkit/kanban/test_markdown_styling.py` | 原样 | 未命中 |
| `kanban/test_morning_batch.py` | `kanban-personal:shared/toolkit/kanban/test_morning_batch.py` | 已删除（removed@KAN-1758） | AUDIT-L334 |
| `kanban/test_net_doctor_script.py` | `kanban-personal:shared/toolkit/kanban/test_net_doctor_script.py` | 待改写（Phase 1-2/1-3） | AUDIT-L697 |
| `kanban/test_network_doctor_endpoint.py` | `kanban-personal:shared/toolkit/kanban/test_network_doctor_endpoint.py` | 原样 | 未命中 |
| `kanban/test_network_doctor_frontend_contract.py` | `kanban-personal:shared/toolkit/kanban/test_network_doctor_frontend_contract.py` | 原样 | 未命中 |
| `kanban/test_network_doctor_panel.py` | `kanban-personal:shared/toolkit/kanban/test_network_doctor_panel.py` | 原样 | 未命中 |
| `kanban/test_network_preset.py` | `kanban-personal:shared/toolkit/kanban/test_network_preset.py` | 原样 | 未命中 |
| `kanban/test_network_status.py` | `kanban-personal:shared/toolkit/kanban/test_network_status.py` | 待改写（Phase 1-2/1-3） | AUDIT-L182, AUDIT-L732 |
| `kanban/test_optional_integrations.py` | KAN-1753 | 新建：默认关闭、路径降级与 UI opt-in 回归 | 新建文件，不适用 |
| `kanban/test_open_llm_promote_fill.py` | `kanban-personal:shared/toolkit/kanban/test_open_llm_promote_fill.py` | 待改写（Phase 1-2/1-3） | AUDIT-L101, AUDIT-L489, AUDIT-L492, AUDIT-L619, AUDIT-L733 |
| `kanban/test_outbound_gate.py` | `kanban-personal:shared/toolkit/kanban/test_outbound_gate.py` | 待改写（Phase 1-2/1-3） | AUDIT-L102, AUDIT-L173, AUDIT-L660 |
| `kanban/test_ownership_lint.py` | `kanban-personal:shared/toolkit/kanban/test_ownership_lint.py` | 待改写（Phase 1-2/1-3） | AUDIT-L335 |
| `kanban/test_p0_card_spine.py` | `kanban-personal:shared/toolkit/kanban/test_p0_card_spine.py` | 待改写（Phase 1-2/1-3） | AUDIT-L103, AUDIT-L174, AUDIT-L336, AUDIT-L648 |
| `kanban/test_project_action_projection.py` | `kanban-personal:shared/toolkit/kanban/test_project_action_projection.py` | 待改写（Phase 1-2/1-3） | AUDIT-L337 |
| `kanban/test_project_canvas_reorganize.py` | `kanban-personal:shared/toolkit/kanban/test_project_canvas_reorganize.py` | 待改写（Phase 1-2/1-3） | AUDIT-L338 |
| `kanban/test_project_conversations.py` | `kanban-personal:shared/toolkit/kanban/test_project_conversations.py` | 原样 | 未命中 |
| `kanban/test_project_state_projection.py` | `kanban-personal:shared/toolkit/kanban/test_project_state_projection.py` | 原样 | 未命中 |
| `kanban/test_platform_adapter.py` | KAN-1754 | 新建：darwin 行为与 Linux mock adapter 回归 | 新建文件；回销 AUDIT-L710, AUDIT-L719, AUDIT-L733 |
| `kanban/test_provenance_probe.py` | `kanban-personal:shared/toolkit/kanban/test_provenance_probe.py` | 原样 | 未命中 |
| `kanban/test_public_entry.py` | `kanban-personal:shared/toolkit/kanban/test_public_entry.py` | 待改写（Phase 1-2/1-3） | AUDIT-L104 |
| `kanban/test_real_project_canvas.py` | `kanban-personal:shared/toolkit/kanban/test_real_project_canvas.py` | 原样 | 未命中 |
| `kanban/test_research_boards.py` | `kanban-personal:shared/toolkit/kanban/test_research_boards.py` | 原样 | 未命中 |
| `kanban/test_review_cycle.py` | `kanban-personal:shared/toolkit/kanban/test_review_cycle.py` | 待改写（Phase 1-2/1-3） | AUDIT-L349, AUDIT-L409 |
| `kanban/test_review_cycle_integration.py` | `kanban-personal:shared/toolkit/kanban/test_review_cycle_integration.py` | 待改写（Phase 1-2/1-3） | AUDIT-L348 |
| `kanban/test_route_registry.py` | `kanban-personal:shared/toolkit/kanban/test_route_registry.py` | 待改写（Phase 1-2/1-3） | AUDIT-L350 |
| `kanban/test_runtime_component_projection.py` | `kanban-personal:shared/toolkit/kanban/test_runtime_component_projection.py` | 已删除（removed@KAN-1758） | 未命中 |
| `kanban/test_scan_allowlist.py` | `kanban-personal:shared/toolkit/kanban/test_scan_allowlist.py` | 原样 | 未命中 |
| `kanban/test_scenarios_and_bridges.py` | `kanban-personal:shared/toolkit/kanban/test_scenarios_and_bridges.py` | 待改写（Phase 1-2/1-3） | AUDIT-L620 |
| `kanban/test_security_p0.py` | `kanban-personal:shared/toolkit/kanban/test_security_p0.py` | 原样 | 未命中 |
| `kanban/test_server_single_instance.py` | `kanban-personal:shared/toolkit/kanban/test_server_single_instance.py` | 待改写（Phase 1-2/1-3） | AUDIT-L351 |
| `kanban/test_server_version.py` | `kanban-personal:shared/toolkit/kanban/test_server_version.py` | 原样 | 未命中 |
| `kanban/test_session_evidence_adapter.py` | `kanban-personal:shared/toolkit/kanban/test_session_evidence_adapter.py` | 原样内容（EOF 空行归一化） | 未命中 |
| `kanban/test_skill_decision_cards.py` | `kanban-personal:shared/toolkit/kanban/test_skill_decision_cards.py` | 待改写（Phase 1-2/1-3） | AUDIT-L352, AUDIT-L621 |
| `kanban/test_skill_invocation.py` | `kanban-personal:shared/toolkit/kanban/test_skill_invocation.py` | 待改写（Phase 1-2/1-3） | AUDIT-L622 |
| `kanban/test_skill_slash_commands.py` | `kanban-personal:shared/toolkit/kanban/test_skill_slash_commands.py` | 原样 | 未命中 |
| `kanban/test_source_anchor_lint.py` | `kanban-personal:shared/toolkit/kanban/test_source_anchor_lint.py` | 待改写（Phase 1-2/1-3） | AUDIT-L353 |
| `kanban/test_status_changed_at.py` | `kanban-personal:shared/toolkit/kanban/test_status_changed_at.py` | 待改写（Phase 1-2/1-3） | AUDIT-L354 |
| `kanban/test_start_script.py` | KAN-1754 | 新建：Bash 语法、Linux opener、平台安装提示与 WSL 声明回归 | 新建文件；回销 AUDIT-L717 |
| `kanban/test_studio_static.py` | `kanban-personal:shared/toolkit/kanban/test_studio_static.py` | 原样 | 未命中 |
| `kanban/test_subagent_manifest_lint.py` | `kanban-personal:shared/toolkit/kanban/test_subagent_manifest_lint.py` | 原样 | 未命中 |
| `kanban/test_task_delete_archive.py` | `kanban-personal:shared/toolkit/kanban/test_task_delete_archive.py` | 待改写（Phase 1-2/1-3） | AUDIT-L355 |
| `kanban/test_task_document_links.py` | `kanban-personal:shared/toolkit/kanban/test_task_document_links.py` | 原样内容（EOF 空行归一化） | 未命中 |
| `kanban/test_task_endpoint.py` | `kanban-personal:shared/toolkit/kanban/test_task_endpoint.py` | 待改写（Phase 1-2/1-3） | AUDIT-L105, AUDIT-L175, AUDIT-L356, AUDIT-L454, AUDIT-L490, AUDIT-L623, AUDIT-L686, AUDIT-L698 |
| `kanban/test_task_id_allocator.py` | `kanban-personal:shared/toolkit/kanban/test_task_id_allocator.py` | 原样 | 未命中 |
| `kanban/test_task_id_persistence.py` | `kanban-personal:shared/toolkit/kanban/test_task_id_persistence.py` | 待改写（Phase 1-2/1-3） | AUDIT-L106, AUDIT-L134, AUDIT-L176, AUDIT-L357, AUDIT-L589, AUDIT-L649 |
| `kanban/test_task_scan_cache.py` | `kanban-personal:shared/toolkit/kanban/test_task_scan_cache.py` | 原样 | 未命中 |
| `kanban/test_task_search.py` | `kanban-personal:shared/toolkit/kanban/test_task_search.py` | 待改写（Phase 1-2/1-3） | AUDIT-L358 |
| `kanban/test_team_kanban_sync.py` | `kanban-personal:shared/toolkit/kanban/test_team_kanban_sync.py` | 待改写（Phase 1-2/1-3） | AUDIT-L359, AUDIT-L410, AUDIT-L455, AUDIT-L491, AUDIT-L624, AUDIT-L729 |
| `kanban/tests/fixtures/codex_jsonl_basic.txt` | `kanban-personal:shared/toolkit/kanban/tests/fixtures/codex_jsonl_basic.txt` | 原样 | 未命中 |
| `kanban/tests/fixtures/codex_jsonl_resume.txt` | `kanban-personal:shared/toolkit/kanban/tests/fixtures/codex_jsonl_resume.txt` | 原样 | 未命中 |
| `kanban/validate_batch.py` | `kanban-personal:shared/toolkit/kanban/validate_batch.py` | 原样 | 未命中 |

## Phase 1-6 溯源收口(2026-08-18)

补登本仓新写文件(源仓无对应物,均为公开版自有代码):

| 公开仓路径 | 来源 | 说明 |
|---|---|---|
| `kanban/attention_gate.py` | 新写 | 注意力/记录卡判据的公开版最小实现 |
| `kanban/conftest.py` | 新写 | pytest 公共 fixture(隔离 runtime root) |
| `kanban/role_policy.py` | 新写 | owner/operator/reviewer 角色→actor 映射(替代私有 persona 常量) |
| `kanban/test_frontend_resource_contract.py` | 新写 | 前端模块图契约测试(KAN-1757 白屏回归防护) |
| `kanban/test_public_roles_and_demo.py` | 新写 | 公开角色与 demo fixture 契约测试 |
| `kanban/requirements-dev.txt` | 新写 | 测试依赖与运行依赖分离(1-6 裁定:pytest 系不进运行时 requirements) |

后续对既有文件的缺陷修复以 git log 为账(714c349 起),不再逐条回写本清单。

许可证兼容:仓内代码仅两类——源仓我方代码(D1 裁定无障碍)与本仓新写;无第三方 vendored 源码。
运行依赖 `watchdog`(Apache-2.0)、构建依赖 Vite/React 生态均经包管理器安装,不随仓分发,与 AGPL-3.0 无冲突。
