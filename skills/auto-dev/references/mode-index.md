# Mode Index

维护 reference 信息架构时使用 [README.md](README.md)；正常请求只按下面的唯一模式读取对应 leaf。

本文件只选择入口，不展开执行细则。

## Read Only

以下请求不进入 Requirement Intake，也不写产品文件：

- 解释代码、调用链或架构
- Survey 项目结构、入口、模块与测试面
- 只读 review、诊断或影响评估

读取 [read-only.md](execution/read-only.md)。若后续要求写入，再进入 Requirement Intake。

## Resume / Handoff

- 恢复中断任务、读取当前进度：Resume
- 导出下一位 Agent 可继续执行的上下文：Handoff
- 接手没有控制面或旧控制面缺少可用计划的项目：Bootstrap / Adopt

读取 [resume-handoff.md](continuity/resume-handoff.md)。若恢复后目标发生变化，回到 Requirement Intake。

## Quick Write

以下请求可先尝试一次性快速写入：

- 单一小 patch，例如修改一个字段、补一个分支或调整一个局部判断。
- 不改变公共契约、依赖、配置真相源、权限、安全边界或控制面。
- 当前分支没有 active task；已有 Project 但处于 idle / selection_required 时仍可尝试。

读取 [quick-write.md](intake/quick-write.md)。Hook 会按真实 patch 再做一次确定性边界检查；失败后转入 Product Write，不得把 Quick Write 当成任意写入绕过。

## Product Write

新功能、bug 修复、重构、优化、测试、清理、配置或产品行为变化均进入：

```text
Requirement Intake -> Direct / Team Core
```

不要按“功能 / bug / 重构”关键词提前选择治理强度。治理强度由最终需求和仓库风险决定。

当请求新建或重塑一个 Project、Capability 或多 Outcome initiative 时，Requirement Intake 先选 `project-discovery`，建立有边界的 Managed Project Frame 与初始 Outcome Graph；不要把“先做一个大计划”误写成一个无限扩张的 Task Plan。既有仓库从一个明确 Task 开始时，先建立 `provisional + partial` Context 和 `unlinked` Outcome，随着证据逐步补完。

## 完成条件

- 只命中一个入口。
- 只读入口未写产品文件。
- 产品写入已转到 [requirement-intake.md](intake/requirement-intake.md)。
