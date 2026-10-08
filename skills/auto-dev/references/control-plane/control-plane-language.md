# Control-Plane Writing Language

新建或更新受管 `.auto-dev` 状态时，所有由 Agent 生成的**人类可读字段默认使用简体中文**。这是状态写作约定，不改变 CLI 的结构化 schema、状态枚举或用户可见 Hook 节点的中英双语回执。

## 默认范围

以下内容用中文概括，保持短、具体、可验证：

- Project Context 的标题、使命、权限/交付/上下文边界、外部依赖说明和证据说明。
- Intake baseline 的摘要、目标、推断、范围、验收、非目标、假设、仓库事实、专家补全和决策说明。
- Task 的任务名、验收、确认来源说明、路由证据、验证说明和停止条件。
- Outcome 的标题、陈述、验收；Plan 的目标、原因、节点标题、主结果、proof 描述、下一步和 gap。
- Checkpoint、review、handoff、activity、capability 与 external-reference 的摘要、证据、风险和结论。

示例：

```text
任务: 修复共享渲染器中的按键按压越槽问题
验收: 字母和逗号按键的按压动画不会越过背景槽位
验证: 运行 pytest tests/test_renderer.py，并核对真机采集帧
```

## 不翻译的内容

- ID、状态枚举、CLI 子命令和参数、文件路径、URL、版本、哈希、正则和机器可解析字段。
- 代码符号、API 名称、第三方产品名、日志/报错原文，以及需要逐字保留的用户引文或契约文本。
- 用户明确要求使用其他语言的字段；此时按用户要求记录，不能为了默认中文改写其意思。

命令或代码符号嵌入中文说明时保留其原样，例如“运行 `python3 -m unittest`”。不要把同一份状态内容存成中英双份；双语只属于 [receipt-catalog.md](receipt-catalog.md) 的节点标签。

## 历史与边界

本规则只约束新写入或经用户明确确认后修订的字段。不得为了中文化自动翻译已有 Task、Plan、Proof、历史事件或用户确认来源；这会改变历史语义和审计证据。CLI 仍只校验结构和 revision，不用脆弱的语言检测阻止合法的英文、代码或用户原文。
