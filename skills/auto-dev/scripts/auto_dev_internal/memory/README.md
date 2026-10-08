# Project Memory

进入条件：修改 dependency registry、resolution lease、preflight、query/review、confirmed incident case，或已确认的环境/业务领域事实。

- schema、locking、atomic storage 与 validation：[store.py](store.py)
- dependency/gotcha record 与 attempt：[entries.py](entries.py)
- resolve、lease、gate 与 preflight：[leases.py](leases.py)
- list/show/verify/review：[queries.py](queries.py)
- incident-case search 与 promote：[cases.py](cases.py)
- environment profile、domain memory 与可再生 Markdown 投影：[profiles.py](profiles.py)

公共兼容入口仍是顶层 `project_memory.py` 和 `dependency_manager.py`。验证入口是 project-memory contract 与 P1 Debug memory tests。
