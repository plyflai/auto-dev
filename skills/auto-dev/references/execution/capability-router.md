# Team Capability Router

将 Team 的固定全量流水线改为风险证据驱动的能力组合。

## 选择规则

对每个能力输出 `enabled / skipped`，并引用需求回执或仓库证据。缺少证据时默认 `skipped`；证据不足但风险可能真实时先补调查，不能靠想象启用。

| Capability | 启用证据 |
|---|---|
| architecture | 新模块边界、共享抽象、跨模块/跨平台协调、广泛重构 |
| data-contract | 数据、Schema、公共 API、协议、配置真相源、外部契约 |
| debug-observability | 根因未知、异步、缓存、竞态、性能或多轮诊断；或本轮运行态功能需要补齐项目级日志层、稳定留存或后续 Agent 可读取的诊断入口 |
| gui | 页面、窗口、表单、交互状态或视觉结果变化 |
| release | 部署、生产配置、远端系统、发布协调或回退演练 |
| parallel-work | 至少两个独立工作流，边界清楚且合并成本可控 |
| compliance | 权限、认证、支付、安全、隐私或合规 |

`debug-observability` 启用后再选择 profile：一轮观测可收敛时为 `standard`；存在多个可区分根因、flaky/异步/跨边界多轮 probe、一次修复失败或跨 session 恢复需求时为 `deep`。已知根因的小修保持 Direct，不创建 diagnostic state。

[impact-preservation.md](../control-plane/impact-preservation.md) 是条件式 Core protection profile，不是第八个 capability。只有重构/删除/重命名/公共契约/迁移风险需要可恢复 impact 时启用；否则保持普通 CodeGraph 导航。

[workspace-policy.md](../control-plane/workspace-policy.md) 是条件式项目保护策略，不是 capability。只有项目存在稳定禁区、逐次审批区或敏感证据区时启用；AI 提议规则，用户确认持久规则，Hook 机械执行。

[performance-verification.md](../verification/performance-verification.md) 是 `measured_improvement`
Outcome 的条件式验证 profile，不是第八个 capability。只有性能目标、可重复工作量、
环境和 benchmark 都具体时启用；普通任务不增加 baseline/comparison 流程。

## Capability Receipt

```text
🧾 Team Capability Receipt

Enabled:
- [capability]: [决定性证据] [optional profile: standard|deep]

Skipped:
- [capability]: [为何当前风险不需要]

Core protection:
- [branch / dirty scope / rollback]

Budgets:
- implementation_repair: 2
- same_class_findings: 2
- review_passes: [1-2]
- gui_retries: [0-3]
- parallel_agents: [任务收益与运行时容量支持的上限]
- elapsed_time: [任务合理上限]

Stop conditions:
- [需要重规划、回流需求或请求权限的条件]
```

## 预算原则

- 预算是熔断器，不是质量上限。耗尽后停止当前策略并重规划，不能降低验收标准。
- 同类问题连续出现两次时，从局部修补切换到不变量、状态矩阵或系统性审查。
- Review 只覆盖真实风险边界；机械重复不逐文件冷启动审查。
- `parallel_agents` 是 fan-out 总上限；没有足够独立工作流时保持 1，不为用满容量而创建子任务。

## 完成条件

- 7 个能力均有 enabled 或 skipped 结论。
- 每个 enabled 项都有可定位证据。
- 预算和停止条件与任务规模相称。
- 只加载 enabled capability 文件。
