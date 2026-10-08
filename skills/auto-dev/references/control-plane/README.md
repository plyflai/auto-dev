# Control Plane Router

进入条件：任务涉及 canonical CLI、Hook、状态安全、工具依赖、路径策略、诊断、CodeGraph 或用户可见控制回执。

- CLI 命令与状态契约：[cli-contract.md](cli-contract.md)
- 新建、切换与替代执行焦点：[state-transitions.md](state-transitions.md)
- Lifecycle Hook 行为：[lifecycle-hooks.md](lifecycle-hooks.md)
- Workspace 路径策略：[workspace-policy.md](workspace-policy.md)
- 外部/真机/长时间动作归属：[action-attribution.md](action-attribution.md)
- Dependency registry、lease、环境与领域记忆：[project-memory.md](project-memory.md)
- CodeGraph 导航：[code-navigation.md](code-navigation.md)
- 风险改造的 impact 保存：[impact-preservation.md](impact-preservation.md)
- 项目运行诊断：[runtime-diagnostics.md](runtime-diagnostics.md)
- 控制面业务语言：[control-plane-language.md](control-plane-language.md)
- 中英双语稳定节点标签：[receipt-catalog.md](receipt-catalog.md)
- 用户可见阶段与等待：[interaction-contract.md](interaction-contract.md)

只读取当前工具或状态分支需要的契约。`.auto-dev` 与 canonical CLI 仍是真相源，README 不复制状态规则。
