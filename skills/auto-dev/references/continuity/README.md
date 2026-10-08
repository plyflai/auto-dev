# Continuity Router

进入条件：恢复、交接、压缩后续作，或现有控制面需要版本化升级。

- Resume、Handoff 与长期 Plan/Checkpoint：[resume-handoff.md](resume-handoff.md)
- Legacy control-plane inspect/apply/revalidation：[legacy-upgrade.md](legacy-upgrade.md)

用户说“更新新版 Auto Dev”“升级这个项目的 Auto Dev”或等价表达时，Agent 直接进入 Legacy Upgrade：自己运行 inspect、自己保留精确 apply contract；用户只决定是否执行真实升级，不输入命令或参数。

正常新任务不读取本目录。恢复先走 resume/handoff；只有 inspect 明确返回升级状态时才进入 legacy upgrade。
