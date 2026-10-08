# CodeGraph 使用契约

CodeGraph 是代码结构与符号关系的首选事实源，不是测试、运行时观测或业务规则的替代品。

## 触发条件

涉及已有代码理解、入口定位、调用链、影响面、复用点、重构、优化、清理或测试范围时：

1. 检查 `codegraph` CLI 和可用的 CodeGraph MCP。
2. 用 `codegraph status` 确认当前项目已索引；未索引时按环境允许执行或提示 `codegraph init -i`。
3. 项目已索引且导航器可用时，先导航，再读取源码。

纯文档、非代码配置、运行时行为或代码导航器不可用时，不强行套用本契约。

## 语义动作

优先使用区域探索：

```text
codegraph explore "<功能区域或问题>"
```

按需要使用：

```text
codegraph files                 # 文件树与邻近测试
codegraph query "<symbol>"    # 符号定位
codegraph callers "<symbol>"  # 调用方
codegraph callees "<symbol>"  # 下游依赖
codegraph impact "<symbol>"    # 影响面
codegraph node "<symbol>"     # 单个符号实现
```

MCP 与 CLI 的能力等价时，使用当前可用接口；不要为同一问题重复重建上下文。

## 降级与证据

- 未索引：先记录并初始化；不能初始化时说明原因，再用最小范围 `rg` / Read。
- 结果 stale：只读取提示涉及的文件，并把 stale 作为降级原因。
- 刚编辑的行、非代码配置或 CodeGraph 未覆盖的动态注册：读取最小必要范围。
- 导航结果只证明结构关系；行为仍需测试、日志、运行或其他直接证据。

用户可见时使用轻量回执：

```text
🧭 CodeGraph 导航回执
- 动作: semantic_explore / semantic_impact / ...
- 查询意图: ...
- 用途: 入口 / 调用链 / 影响面 / 测试面
- Raw Read 降级: 无 / [原因与范围]
```

不要把原始 CodeGraph 输出复制成项目地图；跨任务只记录目标符号、计划决策、验证范围和降级原因。

当重构、删除、重命名、公共契约或迁移风险需要把影响判断保存到 Handoff 时，转入 [impact-preservation.md](impact-preservation.md)。它复用 CodeGraph JSON，不建立第二套图；零结果必须保留 uncertainty，不能写成“安全”。

## 完成条件

- 适用任务在第一次大范围源码探索前完成导航。
- 导航动作、查询意图和必要降级原因可追溯。
- 未把导航结果冒充测试或运行时证据。
