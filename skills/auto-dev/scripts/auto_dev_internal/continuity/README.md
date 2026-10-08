# Continuity

进入条件：修改 workspace checkpoint、portable handoff 或受治理 `fix inspect/apply`。

- Git checkpoint 与 rollback inspection：[workspace.py](workspace.py)
- Handoff export/import：[handoff.py](handoff.py)
- Repair backup、apply、audit 与 readback：[repair.py](repair.py)

状态写入继续经过 revision、backup 和 readback 约束。验证入口是 P0 migration、Hook fix/workspace 与 handoff tests。
