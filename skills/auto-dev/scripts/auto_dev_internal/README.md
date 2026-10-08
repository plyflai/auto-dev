# Auto Dev Internal Router

进入条件：修改、调试或扩展 canonical CLI 背后的领域实现。普通 CLI/Hook 调用不读取本目录。

- 共享 schema、CLI 装配、状态投影与回执：[foundation/README.md](foundation/README.md)
- Requirement Intake 与 inherited contract：[intake/README.md](intake/README.md)
- Project、Outcome、Capability 与 bootstrap：[project/README.md](project/README.md)
- Task、Plan 与交付生命周期：[task/README.md](task/README.md)
- Proof、Debug、Policy 与 impact：[verification/README.md](verification/README.md)
- Workspace、handoff 与受治理修复：[continuity/README.md](continuity/README.md)
- 版本化旧控制面升级：[legacy/README.md](legacy/README.md)
- Dependency registry 与 incident memory：[memory/README.md](memory/README.md)

状态 schema 和兼容 export 仍由顶层 `runctl.py` / `project_memory.py` facade 暴露；领域 package 只拥有内部实现和局部测试边界。
