# Intake

进入条件：修改当前 turn 的需求分类、Intake gate、strict inherited contract 或 coverage 校验。

- Contract 规范化、hash、coverage 与 readiness：[contract.py](contract.py)
- Intake 状态、命令和 contract projection：[workflow.py](workflow.py)

持久状态仍通过 foundation helper 写入；本领域不改变 CLI public command names。主要验证是 intake hierarchy、strict contract 和 Hook gate 测试。
