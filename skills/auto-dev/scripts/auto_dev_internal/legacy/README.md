# Legacy Upgrade

进入条件：修改旧控制面检测、升级计划、状态面 registry、事务 apply 或 revalidation。

- 兼容 orchestration facade：[orchestration.py](orchestration.py)
- fingerprint、step 和 apply 计划：[plan.py](plan.py)
- inspect projection 与命令：[inspection.py](inspection.py)
- upgrade dataclass 与 state-surface registry：[models.py](models.py)

旧状态只通过版本化 inspect/apply 迁移。验证入口是完整 legacy-upgrade tests 和新项目 current-version 检查。
