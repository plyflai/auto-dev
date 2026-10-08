# Pre-Git Control

在开始需求澄清前运行：

```text
auto_dev.py project inspect --repo-root .
```

它是只读命令，不创建 `.auto-dev/`，也不初始化 Git。

## Route

- `ready`：已有 Git 或 local No-Git 控制面，进入普通 Intake。
- `git_ready`：已有 Git、尚无 Project；在当前 Intake/确认边界中建立 Git control。
- `git_setup_recommended`：当前目录没有 Git，但 Git 可用且目录可写。默认推荐 Git，不得静默执行。
- `inside_parent_repository`：当前目录位于父 Git 仓库内；让用户选择父仓库、独立仓库或 local control。
- `migration_available`：原 local control 检测到 Git；等待显式迁移。
- `uninitialized`：Git 不可用或目录不可写；只提供 local/只读选项，并说明原因。

## Git Recommendation

`git_setup_recommended` 在任何产品写入前显示：

```text
📍 当前: 目录尚未建立 Git；检测到 Git 可用，建议先建立本地 Git 控制面
📌 下一步:
[1] 初始化 Git 并建立 Auto Dev 控制面 - 保留 branch、diff 与 handoff 能力
[2] 继续只读需求澄清 - 暂不写产品文件，稍后再选择存储
[3] 使用 local No-Git 控制面 - 明确放弃 Git 证据与 branch 能力
[0] 暂停
```

用户明确选择 `[1]` 或等价自然语言后，执行：

```text
auto_dev.py project init --mode git --confirmation-source "用户确认初始化 Git"
```

这只会创建本地 Git 与 `.auto-dev/`；不得自动 commit、push 或配置 remote。用户不回应不等于授权。`[2]` 可继续只读调查，但直到用户选 Git/local 前不得写产品文件。

若当前已经是 local No-Git control，以上 `project init --mode git` 只初始化 Git 并返回 `migration_available`；随后仍须以当前 revision 和第二次明确确认执行 `project migrate`，不会自动改写现有 Task、Plan 或历史。

## Local No-Git

用户明确选择 `[3]` 后执行：

```text
auto_dev.py project init --mode local --confirmation-source "用户明确选择 local No-Git 控制面"
```

local control 使用同一份 `.auto-dev/` Project、Intake、Task、Plan、revision、lock、backup 与 recover 契约，但 `workspace.vcs` 必须为 `none`。它没有 branch、commit 或 Git diff；Task 必须带显式 scope，验证使用文件快照、hash、测试和 proof，不能伪造 Git 证据。

## Pre-Git Hook

用户显式引用 `$auto-dev` 且目录尚未受管时，`UserPromptSubmit` 在 `PLUGIN_DATA` 写入短期 pending marker，并建立同一 session 的 activation marker，回执 `pre_git_intake_pending`。它不保存 prompt 正文，也不推断业务语义。`PreToolUse` 在此 marker 未升级为 Git/local control 前阻止产品写入，只允许调查和 canonical storage mutation；后续建立 `.auto-dev` 后继续沿用该 session activation，不会因控制面落地而丢失显式启用状态。

普通未显式启用 Auto Dev 的非 Git 对话不登记 marker，以免把普通小修改误拦为受管项目。`PLUGIN_DATA` 不可用时回执 `pre_git_guard_unavailable`；Agent 必须停在只读路径并如实报告，不能声称硬门已生效。

## Migration And Recovery

用户后来初始化 Git 后，先显示 `migration_available`，再执行：

```text
auto_dev.py project migrate --project-revision <current> --confirmation-source "用户确认迁移到 Git"
```

迁移重写 workspace identity、当前 execution context 和 local Task 的 Git baseline，并保留 Task/Plan/Intake 历史。新建但尚未首次提交的 Git 仓库明确报告 `head: null`，不会把字符串 `HEAD` 当作可验证提交。目录移动、Git 被删除、control identity 不匹配或状态不可读时停止产品写入并要求显式 recover、迁移或重新收编；不得静默绑定另一个目录或仓库。
