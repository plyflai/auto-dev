# Auto Dev Scripts Router

进入条件：调用、维护或验证 Auto Dev 的确定性本地能力。正常使用优先调用 canonical front door，不读取内部实现目录。

## Public And Compatibility Entrypoints

- Canonical CLI：[auto_dev.py](auto_dev.py)
- Run-control compatibility facade：[runctl.py](runctl.py)
- Project-memory compatibility facade：[project_memory.py](project_memory.py)
- Dependency compatibility facade：[dependency_manager.py](dependency_manager.py)
- Read-only progress service：[progress_server.py](progress_server.py)
- Stable progress page asset：[progress_page.html](progress_page.html)
- Rolling worker lifecycle is exposed through the canonical `milestone worker prepare|inspect|capture|apply|cleanup` commands; model selection and Codex Subagent creation remain host-owned.

Hook 共享的稳定叶子是 [contract_lineage.py](contract_lineage.py)、[plugin_identity.py](plugin_identity.py) 和 [receipt_catalog.py](receipt_catalog.py)。

## Maintenance Routes

- 内部领域实现：[auto_dev_internal/README.md](auto_dev_internal/README.md)
- Shell 契约验证：[contracts/README.md](contracts/README.md)

公共入口拥有参数、stdout/stderr 和退出码契约；内部 package 不应成为 SKILL、Hook 或用户必须记忆的调用路径。
