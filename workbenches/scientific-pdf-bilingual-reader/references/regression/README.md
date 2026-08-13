# 私有回归材料边界

Skill 分发包不包含真实论文页面、译文、OCR 全文、任务 ID 或本机路径。

本机维护者如需运行私有回归测试，应把材料放在 Skill 目录之外，并显式设置：

```bash
export PDF_READER_PRIVATE_REGRESSION_DIR=/path/to/private-regression
```

该目录可包含 `fixture-manifest.json`、`skl-209-*` 与 `skl-212-howtoread` 等本地验收证据；不得提交或复制到 Codex/Claude Skill 发现目录。
