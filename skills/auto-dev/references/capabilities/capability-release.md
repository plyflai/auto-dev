# Capability: Release

## Enable When

涉及部署、生产配置、远端系统、外部写入、发布协调或需要回退演练。

## Hard Gates

- 明确环境、目标版本、授权边界、变更窗口和负责人。
- 建立发布前 checkpoint、健康检查、回退条件与回退动作。
- 外部写入、推送、合并、部署或通知遵守用户授权，不由任务终态自动扩大权限。
- 凭据只通过既有安全通道使用，不写入 Skill 或运行记录。

## Verification

- 发布前验证构建/产物与配置。
- 发布后运行最小健康检查和关键用户路径。
- 失败达到退出条件时执行回退，不在生产环境无限试错。

发布动作仍由项目现有 CI/CD、脚本或人工流程执行。动作完成后，只有当前
Team Task 已启用 `release` 且 active Plan node 为 `node_kind=release` 时，才将
`auto-dev/release-evidence/v1` manifest 通过同一个 `proof --evidence-file` 绑定。
manifest 记录环境、版本、健康检查、关键用户流程、回退触发/目标、未验证边界
和产品下一步；它只证明发布结果，不授予 deploy、push、认证或外部写入权限。

## Completion

- 目标版本可追溯，关键健康检查通过。
- 回退状态、残余风险和外部影响已记录。
- `partial / blocked / rolled_back` 不成为 Green proof；报告内容变化后原 Proof 失效。
