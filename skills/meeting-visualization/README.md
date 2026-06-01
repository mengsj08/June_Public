# Meeting Visualization Skills

会议资料解析、会议 case 搭建和客户安全产物生成相关 skill。

## Skills

| Skill | When to use | Main output |
| --- | --- | --- |
| `feishu-meeting-workflow/` | 需要从飞书/Lark AI notes、会议转录、minutes 链接或本地转录创建会议分析 case | 本地 case、转录归档、内部 brief、客户材料、HTML 或 pre-consult handoff |

## Quick Start

示例提示词：

```text
使用 feishu-meeting-workflow，读取这个飞书会议链接，创建本地 case，并生成客户可见会议总结 HTML。
```

```text
使用 feishu-meeting-workflow，这是一场售前面访，请走 pre-consult 五阶段交接流程。
```

## Public Safety

此目录不能包含：

- Lark CLI profile、app secret、user token、bot token。
- 客户会议原始转录、运行 workspace、生成页面。
- 飞书 doc/minute token、签名媒体 URL。
- 内部销售判断混入客户可见材料。

公开版本只保留 skill 代码、脚本和说明。
