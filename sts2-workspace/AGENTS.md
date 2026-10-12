# Codex → Claude Code → Codex 委派规则

本目录是从本地共享工作区导入的源码快照；原始 `sts2-cli/` 与 `sts2-rl-agent/` 是独立 Git 仓库，导入时不携带其 `.git` 元数据。
保留所有已有项目规则、下级 AGENTS.md 和用户未提交的修改。本规则不授权回滚、覆盖或提交已有修改。
此快照由上级 SlayTheModel 仓库统一跟踪。Git 操作在上级仓库执行，不要在快照中初始化嵌套仓库。

## 角色与默认流程

- Codex 是总指挥，负责需求理解、规划、任务拆分、架构设计、核心决策、验收、集成、最终合并与交付。
- Claude Code CLI 是执行者，负责边界明确、可独立完成的代码修改、重构、文档及重复性工作。
- 收到开发需求后，Codex 先检查相关规则和 Git 状态并规划；适合委派的任务自动生成 Markdown 任务文件，通过下面的脚本同步派发，无需逐步询问用户。
- Codex 等待调用结束后读取 `report.md`、原始结果和错误日志，对比实际 Git diff（包括未跟踪文件）、确认范围、运行适当测试，再决定验收。执行者的完成声明和脚本退出码 0 **不等于 Codex 验收成功**。
- 不合格时生成包含具体问题、修复范围、验收标准的修复任务重新派发；验收合格后自动继续后续步骤。权限或网络受限时记录具体原因，不解除安全边界；涉及高风险、额外授权或需求歧义时才询问用户。
- Claude 没有任意 Bash/PowerShell 权限。需要命令验证时，Codex 自己执行；不要让 Claude 伪造测试结果。若任务要求执行测试但授权工具无法执行，应报告 partial/blocked，由 Codex 验证后更新任务。

## 派单入口

从本目录运行（本机可用 `python`；`python3` 当前为不可用的 Windows 别名）：

```powershell
python scripts/delegate_claude.py path/to/task.md --cwd sts2-rl-agent
python scripts/delegate_claude.py path/to/task.md --cwd sts2-cli --read-only
```

任务使用 UTF-8 Markdown，必须含非空的 `## Goal`、`## Scope`、`## Acceptance criteria`、`## Forbidden`。
验收标准用 `- ` 列表，每条将分配 C1、C2 等 ID。Scope 列出允许读写的具体文件、目录和现有修改保护要求。
禁止事项须列明不得触及的文件、行为与边界。任务文件建议放在 `.handoffs/tasks/`；不得包含凭据。

默认只暴露并授权 Read、Edit、Write、Glob、Grep；`--read-only` 只暴露 Read、Glob、Grep。
使用 `--output-format json`、`dontAsk`、safe mode、关闭额外 MCP/技能，未授权工具不能通过非交互提示获得权限。
禁止使用跳过权限审查的危险选项。文件修改范围仍需 Codex 检查，工具名单不是按路径隔离的沙箱。

每次调用生成独立 `.handoffs/<UTC时间>-<随机ID>/`，保存任务原文、实际提示、原始 stdout、stderr、验证错误、调用元数据与报告。
超时、非零退出、错误 JSON、is_error 不为 false、空 result、partial/blocked、未覆盖全部验收项、剩余工作和工具拒绝均返回非零。
通过机器检查只记为 `completed_pending_codex_review`；Codex 验收记录应注明 diff、测试证据和最终结论。
安全模式关闭 Claude 自动项目上下文；Codex 必须把适用的项目规则显式写入任务。架构及最终决策不委派给 Claude。

## 初始化环境记录

2026-10-12：`python3` 是不可执行的 Windows 应用别名（退出码 9009）；`python` 为 Python 3.13.12，可执行。
Claude Code CLI 版本为 2.1.296，README 非交互只读派单已通过。
现有配置的实际模型为 `deepseek-flash[1m]`，CLI stderr 有 `unrecognized_model` 警告，但本次进程退出码 0、JSON is_error=false。
此入口使用现有 Claude Code 模型与认证配置，不代表一定调用 Anthropic Claude 模型；初始化未改动认证、模型或全局安全设置。
