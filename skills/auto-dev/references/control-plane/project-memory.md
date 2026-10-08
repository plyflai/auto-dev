# Project Memory

Project Memory 保存 CodeGraph 无法提供、但项目会反复需要的已验证事实。当前包含 dependency/gotcha、Deep Debug 用户确认后晋升的 incident case，以及环境 profile 和跨功能业务领域记忆。它不是每个动作的检查表：只在能力命中时读取相应 kind。

存储继续使用 `.auto-dev/project-memory.json`。Dependency 的 canonical 命令是 `auto_dev.py deps`；incident case 使用 `auto_dev.py memory case search|promote`。旧的 `dependency_manager.py` 与 `project_memory.py` 仍是兼容入口。

## 最小模型

- dependency：已验证或待验证的依赖配方。包含 capability、版本组合、环境条件、命令、runtime argv 前缀、成功标准、scope、状态和 fallback。
- attempt：只在 candidate、新版本、失败或显式复验时追加的运行结果。普通成功的 known-good 配方不写完整 attempt。
- gotcha：项目专属的反直觉行为、错误调用或适用边界。
- incident_case：Deep Debug 经过 fresh evidence、恢复验证和用户确认后晋升的可搜索案例；历史案例始终只是当前诊断的候选假设。

dependency 状态只有：

~~~
known-good
known-bad
candidate
needs-recheck
~~~

角色只有：

~~~
preferred
fallback
candidate
avoid
~~~

known-bad 只能是 avoid。一次失败不足以自动把 preferred 降级；模型根据运行证据显式记录 attempt --next-status 后才改变状态。

## 快路径

任务首次需要某项工具能力时执行一次紧凑解析：

~~~bash
python3 <skill-root>/scripts/auto_dev.py deps resolve --repo-root . \
  --capability android-instrumentation --scope reverse --environment "Python 3.10" \
  --write-lease
~~~

输出只包含 selected recipe、blocked 组合、fallback、candidate、review_due 和 resolution lease。不要默认读取完整 revisions 或 attempts。

命中 known-good/preferred 或 known-good/fallback 后，当前任务复用 `.auto-dev/dependency-lease.json`。lease 只授权已记录的绝对 runtime argv 前缀；裸命令、PATH 重排或不匹配的包装器不能替代它。以下事件才使 lease 需要重新解析：工具链失败、版本或环境变化、输入/任务形态变化、已知 patch/new release 需要复验、或用户明确要求比较/升级。

优先级固定为：

~~~
明确项目决策 > preferred > fallback > candidate > 通用经验/联网调查
~~~

known-bad/avoid 与 incompatibility 会在 resolve 中返回，不能被“常见开源方案”静默覆盖。

## Managed Runtime Gate

对已被 Plugin 识别为受管外部动作的工具族，Hook 会在真正调用前执行只读 gate。它要求：

- active lease 的 capability 与动作匹配；
- lease 指向仍为 `known-good/preferred|fallback` 的 recipe，且不处于 review/recheck；
- 实际 argv 以 recipe 中记录的绝对 `runtime_argvs` 前缀开始。

`gate` 不写文件，适合 Hook 和恢复时读取：

~~~bash
python3 <skill-root>/scripts/auto_dev.py deps gate --repo-root . \
  --capability android-instrumentation \
  --argv-json '["/absolute/python", "tools/frida/run_probe.py", "--script", "probe.js"]'
~~~

没有 lease、lease 与当前 runtime 不匹配、或 recipe 需要复验时，gate 非零返回 `preflight-required`。不要以 source 某个项目环境脚本绕过它。

## Candidate Preflight And Promotion

candidate 不能直接成为正常执行路径。先在已有 node-bound action 内打开一个短时 permit；permit 只能匹配已声明的 candidate runtime argv，默认 15 分钟、最长 60 分钟：

~~~bash
python3 <skill-root>/scripts/auto_dev.py deps preflight open --repo-root . \
  --permit-id frida17-preflight --dependency-id frida17-host \
  --capability android-instrumentation --scope reverse --action-id capture-1 \
  --argv-json '["/absolute/python", "tools/frida/run_probe.py", "--script", "probe.js"]'
~~~

动作完成后必须关闭 permit，并带真实 evidence。只有 action contract 已声明该 preflight 足以证明配方时才使用 `--promote`；它原子地记录 passed attempt、提升为 `known-good/preferred|fallback` 并写入 active lease。`environment`、`compatibility` 或 `unknown` 失败会记录分类、撤销同一 lease 并把原 known-good 标为 `needs-recheck`，因此不能被下一次 resolve 静默重签；`input`、`usage` 等非工具失败保留原 recipe。任何失败都不会自动联网升级或写成 known-bad：

~~~bash
python3 <skill-root>/scripts/auto_dev.py deps preflight close --repo-root . \
  --permit-id frida17-preflight --result passed --classification output \
  --summary "probe_ready" --evidence "trace: probe_ready" --promote
~~~

普通 known-good 成功不重复写 attempt；candidate、失败、环境漂移或显式复验才写新 evidence。`input` / `usage` 失败不降级 recipe，也不撤销其匹配 lease；只有 `environment`、`compatibility` 或 `unknown` 的已失败 preflight 才会撤销并要求重新解析。candidate promotion 只把本次实际验证的 runtime argv 写入 lease；直接记录为 known-good 的 recipe 只能声明已有证据覆盖的 argv 前缀。

## 失败路径

工具链失败时先记录最少 runtime evidence，再分类：

~~~
tool-task-mismatch
usage
environment
input
compatibility
output
downstream
unknown
~~~

任务与工具不匹配、参数错误、输入错误或环境缺失，不等于 dependency 坏了。先查询当前 capability 的 known-bad、gotcha 和 fallback；没有匹配经验时才用模型和联网能力调查新版本或替代品。

记录新证据时：

~~~bash
python3 <skill-root>/scripts/auto_dev.py deps attempt --repo-root . \
  --dependency-id frida-py39 --result failed --classification compatibility \
  --summary "attach failed with the Python 3.9 combination" \
  --evidence "stderr: incompatible client" --environment "Python 3.9" \
  --next-status known-bad --next-role avoid
~~~

新版本或替代工具先记录为 candidate；只有项目成功标准和下游验证通过后，才可显式晋升为 known-good/preferred。旧配方应保留为 fallback，不能被一次成功覆盖。

## 依赖更新

工具自身的更新提示只是信号，不自动替换当前版本。registry 使用：

~~~
check_policy: on_miss / on_failure / on_demand / ttl / disabled
last_checked_at
next_review_at
update_signal
~~~

仅在失败、缺少配方、显式升级请求、环境漂移、重复问题或 ttl 到期时检查上游。review 只列出应检查的依赖，不联网、不自动升级：

~~~bash
python3 <skill-root>/scripts/auto_dev.py deps review --repo-root .
~~~

发现新版本后，先形成 candidate，再运行最小项目验证；是否替换 preferred 由证据决定。

## 维护命令

~~~bash
python3 <skill-root>/scripts/auto_dev.py deps record dependency --repo-root . \
  --id frida-py310 --name Frida --purpose "Android instrumentation" \
  --capability android-instrumentation --source https://github.com/frida/frida \
  --version "Python 3.10 + Frida 16.5" --environment "Python 3.10" \
  --command "frida-ps -U" --runtime-argv '["/absolute/frida-ps"]' \
  --success "target process is listed" \
  --evidence "device smoke passed" --scope reverse --status known-good --role preferred \
  --check-policy on_failure

python3 <skill-root>/scripts/auto_dev.py deps record dependency --repo-root . \
  --id frida-py39 --name Frida --purpose "Android instrumentation" \
  --capability android-instrumentation --source https://github.com/frida/frida \
  --version "Python 3.9 + Frida 16.5" --evidence "attach compatibility failure" \
  --scope reverse --status known-bad --role avoid \
  --incompatible "Python 3.9" --fallback frida-py310

python3 <skill-root>/scripts/auto_dev.py deps list --repo-root . --kind dependency --compact
python3 <skill-root>/scripts/auto_dev.py deps show frida-py310 --repo-root . --attempts
python3 <skill-root>/scripts/auto_dev.py deps verify --repo-root . --strict
~~~

依赖记录不得包含凭据、令牌、口令、原始敏感数据或只靠聊天上下文才能解释的命令。产品运行日志仍由 runtime-diagnostics.json 管理，不能混入 dependency attempts。

## Incident Case Search And Promotion

Deep Debug 生成假设前先执行只读搜索：

~~~bash
python3 <skill-root>/scripts/auto_dev.py memory case search --repo-root . \
  --symptom "request completes but stale state remains" \
  --scope src/state --component state-machine --environment staging
~~~

结果携带 `memory_revision`、memory/query digest、case IDs、score 和 compatibility warnings。Agent 用 `debug case-search bind` 绑定同一结果；历史 case 不能自动成为当前 root cause。

只有 source Task 已进入 `review_ready`，且满足以下条件，才能显式 promotion：

- 普通修复：fresh `root_cause_confirmed` + `recovery=verified`。
- no-defect：fresh `no_defect_observed` + `recovery=not_applicable`，并明确环境/范围边界。
- 两者都需要当前 Task state revision、Project Memory revision、用户 confirmation source、lesson 和 evidence refs。

`awaiting_confirmation / inconclusive / blocked` 不得 promotion。长期 case 只保存症状信号、范围/组件/环境、根因类别、修复、保护性测试、教训、source Task/digest 和确认 digest；完整 hypotheses/observations 留在 Task。Project Memory mutation 使用 `memory_revision` CAS、registry lock、原子替换和 readback；dependency/gotcha 既有语义不变。

## Resume And Handoff

Resume 先读取当前 resolution lease 和当前 scope 相关 dependency recipe；没有失败、环境漂移或复验触发时不展开 attempts。Handoff 传递 registry 与 active lease，导入后用 verify 判断已知配方是否需要复验；短时 preflight permit 不随 handoff 迁移，目标环境必须重新打开并验证它。

Dependency registry 只处理开发工具/外部依赖的项目可用性。它不替代 Requirement Intake、Direct/Team 分流、CodeGraph、产品日志或依赖锁文件的正常版本管理。

## Environment And Domain Memory

`environment inspect` 是零写入 readback；旧控制面先返回 `migration_required`，必须通过显式 `legacy-upgrade apply` 进入当前版本。之后 `environment init` 为已初始化项目创建新的 `.auto-dev/path.md` 投影，`environment set` 用当前 `memory_revision` 和 confirmation source 写入结构化 profile。profile 只记录已确认的 host、working root、endpoint、路径、结构化 argv 运行/观测入口和 GUI executor 事实，拒绝凭据；它从不读取旧 `.autodev/**`。`path.md` 是人读投影，不可直接编辑。

`domain inspect|set` 使用同一 revision/lock/atomic/readback 契约，持久化跨功能稳定的业务术语、业务不变量、待消歧概念和耐久决策，并生成 `.auto-dev/project-domain.md`。不要记录当前 Task 的临时实现细节或未确认推测。

只有显式 `legacy-upgrade inspect` 才会只读列出已知 `.autodev` 素材的 path、digest、kind 和建议的人工重录路径。它不解析、不自动导入，也不会把旧 Green 文本提升为当前状态。
