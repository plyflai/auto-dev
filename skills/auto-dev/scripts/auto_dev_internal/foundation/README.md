# Foundation

进入条件：修改跨领域 schema/helpers、CLI parser、稳定回执、运行诊断或 compact status。

- 共享常量、I/O 与状态 helper：[core.py](core.py)
- argparse 子命令装配：[cli.py](cli.py)
- workspace/receipt 兼容投影：[receipts.py](receipts.py)
- 请求级求值、single-flight 与派生摘要缓存：[evaluation.py](evaluation.py)
- 进度服务共享快照与 lease fencing：[progress.py](progress.py)
- runtime diagnostics 与恢复命令：[runtime.py](runtime.py)
- compact/full status 组装：[status.py](status.py)

`core.py` 是共享状态 owner；其他模块不得复制 schema 或持久化规则。验证从顶层 `runctl.py` 和对应契约/单测进入。
