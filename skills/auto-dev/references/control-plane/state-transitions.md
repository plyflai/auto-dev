# State Transitions

进入条件：创建新执行焦点，或从当前 Task/Outcome 切换到不相关的新工作。

正常路径统一使用：

```text
auto_dev.py transition --repo-root . --spec-file <transition.json>
```

首版 Registry：

- `start-new`：当前 branch 无执行 Task；一次创建或复用 Context、Outcome、confirmed clear Intake、Task 和 active Plan。
- `switch-passed`：当前 Task 为 `review_ready` 且用户接受；沿用既有严格完成门禁归档为 `passed`，再创建新焦点。
- `switch-superseded`：当前工作被明确的新工作替代；保留历史成果并归档为 `superseded`，不为离开旧焦点重验 stale proof，再创建新焦点。

Transition 使用 expected project/task revision 和 request ID。退出旧焦点、进入新焦点、Plan ready 与 UI readback 是一个失败可恢复的控制动作；只有 Context、Outcome、Intake、Task、active node、compact projection 和 `/api/state` 一致时返回 `ready`。失败返回非零、恢复原控制状态，并仍返回可用时的控制面 URL。

Proof 策略：

- `strict-completion` 只用于声明旧 Task 在当前状态下正式 `passed`。
- `target-only` 用于 `start-new` 和 `switch-superseded`；旧 proof freshness 不阻止无关新工作。

相关反馈继续使用原 Task 的 `task resume`。控制面损坏先走 `fix`，但修复完成后继续原 transition intent，不把修复本身变成新的产品目标。底层 `start / plan / finish / abandon / bootstrap` 保留为兼容、修复和高级入口；正常新建或切换不再由 Agent逐条拼接。
