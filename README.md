# June Public

Public skill collection and landing pages.

## Landing Pages

- [`landing/workbuddy-team-sync-reporter/index.html`](landing/workbuddy-team-sync-reporter/index.html) — WorkBuddy team sync reporter

## Skills

- `skills/team-operations/workbuddy-team-sync-reporter/` - WorkBuddy 团队同步日报：在团队成员自己的 Mac 上同步指定 GitHub 仓库和 Feishu/Wiki 本地导出结果，生成可审阅中文日报，并在测试确认后交给 WorkBuddy 定时发送到飞书群。

- `skills/meeting-visualization/feishu-meeting-workflow/`  
  Feishu/Lark 会议工作流：解析 AI 纪要或会议转录文档，创建本地会议 case，区分内部来源记录与客户材料，并渲染客户安全的独立 HTML 会议总结。

- `skills/ip-operations/xiaohongshu-skills/`
  小红书自动化技能集合：认证、搜索、发布、互动、复合运营，以及 topic2feishu 采集写入飞书 Base。

- `skills/ip-operations/mj-adapt/`
  多平台内容适配：将已完成文章转换为公众号 HTML、小红书长图和社交短内容。

- `skills/openclaw/`  
  Archived OpenClaw onboarding and configuration skills. Kept for historical reference only; not recommended for new workflows.

## Not Promoted

- `skills/SKILL_INTAKE.md`  
  Removed. The old repo-local skill intake document is no longer promoted as the operating entrypoint.

- `skills/openclaw/`  
  Deprecated/trial tool skills. Keep isolated as archive material and avoid using them as active workflow recommendations.

## Safety

This repository contains only code, skill instructions, tests, examples, and selected extension source. It does not include local account state, cookies, Feishu app secrets, user tokens, bot tokens, fetched meeting transcripts, generated runtime workspaces, or collected output data.

For `workbuddy-team-sync-reporter`, repository URLs, Feishu/Wiki export commands, webhook URLs, bot secrets, app credentials, and WorkBuddy runtime traces must stay in each user's local config or environment files.
