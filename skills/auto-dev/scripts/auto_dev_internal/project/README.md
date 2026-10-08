# Project

进入条件：修改 Project Context、Outcome DAG、Capability Map、Activity/Focus、bootstrap 或产品验收投影。

- Project/Outcome/Capability/Activity facade：[model.py](model.py)
- Project Context 与领域记录实现：[context.py](context.py)
- project inspect/init/migrate：[lifecycle.py](lifecycle.py)
- bootstrap inspect/apply：[bootstrap.py](bootstrap.py)
- Outcome 与 product review：[outcome_review.py](outcome_review.py)

Project revision 和 hierarchy state 由 foundation helpers 保护。验证入口是 intake hierarchy、project control、product review 和 UI projection。
