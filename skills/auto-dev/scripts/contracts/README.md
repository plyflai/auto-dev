# Script Contracts

进入条件：复验 canonical CLI、状态控制、CodeGraph、Project Memory、运行诊断或进度服务的 shell 契约。

- [cli-contract-test.sh](cli-contract-test.sh)
- [code-navigation-contract-test.sh](code-navigation-contract-test.sh)
- [outcome-contract-test.sh](outcome-contract-test.sh)
- [plan-numbering-contract-test.sh](plan-numbering-contract-test.sh)
- [progress-server-contract-test.sh](progress-server-contract-test.sh)
- [project-control-contract-test.sh](project-control-contract-test.sh)
- [project-memory-contract-test.sh](project-memory-contract-test.sh)
- [runctl-selftest.sh](runctl-selftest.sh)
- [runtime-diagnostics-contract-test.sh](runtime-diagnostics-contract-test.sh)

每个脚本从自身位置解析 Skill root，不依赖调用者 cwd。需要整组复验时批量运行本目录的 `*test.sh` / `*selftest.sh`。
