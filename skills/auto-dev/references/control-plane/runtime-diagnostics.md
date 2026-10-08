# Runtime Diagnostics

本契约处理 auto-dev 交付物的运行态记录，不处理 auto-dev 自己的任务 receipt。目标是让新建或修改的网页、App、服务和后台流程，在正常运行和失败时留下可定位、可保存、可由后续 Agent 消化的项目级记录。

## 适用与评估

在 Requirement Intake 的仓库调查中检查目标运行路径、既有日志层、存储与读取方式。结论只有四种：

- `covered`：本轮关键状态和失败路径已经由可用的项目级日志层覆盖；验证读取入口并登记清单。
- `augment`：项目级日志层可用，但本轮功能缺少关键事件、错误上下文或可读取入口；在该层补齐。
- `foundation`：日志层缺失、不能稳定保存、无法供 Agent 读取，或不满足最小字段与脱敏要求；建立或修复共享基础后再接入功能。
- `not_applicable`：本轮没有可运行行为，例如纯文档或静态素材改动；在最终需求回执说明原因。

`foundation` 涉及新共享层、外部服务、持久化存储、留存期或隐私边界时，按执行路由进入 Team Core；需要产品取舍的部分并入既有最终需求回执。这里不新增确认门。

## 接入规则

- 复用项目现有的日志抽象、命名和存储路径；不要为单个功能新建孤立日志系统。
- 记录有诊断价值的运行状态：关键操作的开始/完成、业务状态变化、外部调用边界、重试/降级和错误。不要逐行记录，也不要把每次 UI 点击都当作日志事件。
- 每条事件采用项目的结构化格式，并能表达至少 `timestamp`、`level`、`component`、`event`、`outcome`、`correlation_id` 和 `error`。成功事件可省略具体错误值，但错误结构必须稳定。
- 关联 ID 要能贯穿同一请求、任务或用户操作；错误记录保留可行动的错误类型、消息与必要上下文，不记录密钥、令牌、口令、完整身份信息或原始敏感载荷。
- 运行记录需要有稳定保存方式和可执行读取路径。客户端无法直接写入 Agent 可读位置时，先检查现有后端、设备本地存储或受控导出方式；若这会引入新的留存、隐私、成本或外部依赖，回到既有最终需求回执，不静默添加。清单中的读取命令或查询不包含凭据、令牌或原始敏感数据。

## 持久化清单

完成日志接入或确认既有覆盖后，在项目根的 `.auto-dev/runtime-diagnostics.json` 写入或更新本轮条目。使用现有脚本而不是手写不一致的格式：

```bash
python3 <skill-root>/scripts/auto_dev.py diagnostics --repo-root . \
  --id <stable-area-id> \
  --component <component> \
  --scope <product-path> \
  --layer <project-log-layer> \
  --storage <where-records-persist> \
  --retention <retention-or-rotation> \
  --read <command-or-query-an-agent-can-run> \
  --event <meaningful-event> \
  --field timestamp --field level --field component --field event \
  --field outcome --field correlation_id --field error \
  --correlation <how-the-id-is-propagated> \
  --redaction <what-is-excluded-or-redacted> \
  --verify <success-and-failure-readback-evidence>
```

条目按 `id` 覆盖更新，包含组件、产品范围、日志层、持久化位置、留存、读取命令或查询、事件、字段、关联方式、脱敏、验证和限制。`.auto-dev/` 是本地的项目工作记录；它让同一项目的新 session 直接接手，不替代需要进入版本控制的运维文档或生产日志策略。

## 验证与交接

1. 执行本轮成功路径和相关失败路径。
2. 用清单中的读取方法找到对应记录，并核对关联 ID、结果和错误上下文。
3. 新 session 恢复时先读取该清单，再按记录中的命令、路径或查询继续诊断。

出现任何一个情况都不能把运行诊断标为完成：记录没有稳定保存、读取方法需要猜测、错误路径没有留下可行动上下文、或清单遗漏了本轮适用的运行路径。
