# 私有回归材料边界

公开仓库只保存回归测试代码，不保存真实论文页面、译文、OCR 全文、页面截图、任务目录、
客户材料、本机路径或模型 trace。

## 为什么测试分成两层

| 层级 | 数据 | 目的 | 当前结果 |
| --- | --- | --- | --- |
| 公开分发测试 | 合成数据与代码内 fixture | 验证安装、路由、QA、Comment、修复事务和 UI 合同 | 131 passed、19 skipped |
| 私有回归测试 | 仓库外维护的真实复杂页面 | 验证目录、旋转页、扫描页、表格与历史缺陷不回归 | 150 passed（2026-08-13 本机记录） |

公开 clone 不具备私有材料时，相关测试必须明确 `skipped`，不能伪造通过，也不能从网络
自动下载维护者的测试文档。

## 维护者运行方式

把私有回归 bundle 放在 Skill / Git 仓库之外，然后显式设置：

```bash
export PDF_READER_PRIVATE_REGRESSION_DIR=/absolute/path/to/private-regression
pytest -q
```

该目录可以包含 fixture manifest、真实页面、期望指标与本机验收收据，但必须满足：

- 不位于 `scientific-pdf-bilingual-reader/` 内；
- 不复制到 Codex / Claude Skill 发现目录；
- 不出现在 Git diff、README 截图、错误日志或公开测试输出中；
- 只在维护者明确设置环境变量时加载；
- 缺失、损坏或版本不匹配时 fail closed 或 skip，不回退到猜测路径。

## 发布前检查

```bash
find . -type f \( -iname '*.pdf' -o -iname '*.png' -o -iname '*.jpg' \
  -o -iname '*.jpeg' -o -iname '*.jsonl' -o -iname '*.log' \) -print
```

仓库允许产品 README 使用经过人工确认的合成演示截图；除这些明确的公开图片外，扫描
结果中出现真实页面或任务产物都应阻止发布。
