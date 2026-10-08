#!/usr/bin/env python3
"""Canonical bilingual labels for user-visible Auto Dev control receipts."""

from __future__ import annotations

from typing import Mapping


_LABELS: Mapping[str, tuple[str, str]] = {
    "session_startup": ("会话启动恢复", "Session startup recovery"),
    "session_resume": ("会话恢复", "Session resume"),
    "session_clear": ("会话清理恢复", "Session clear recovery"),
    "session_compact": ("上下文压缩恢复", "Context compaction recovery"),
    "hook_activated": ("控制面已激活", "Control plane activated"),
    "model_changed": ("模型变更已重新同步", "Model change re-synchronized"),
    "active_task_changed": ("执行任务已切换", "Execution task changed"),
    "control_state_changed": ("控制状态已更新", "Control state updated"),
    "task_selection_required": ("需要选择任务", "Task selection required"),
    "task_paused": ("任务已暂停", "Task paused"),
    "task_resumed": ("任务已恢复", "Task resumed"),
    "scope_amended": ("任务范围已更新", "Task scope updated"),
    "plan_updated": ("任务计划已更新", "Task plan updated"),
    "checkpoint_updated": ("任务检查点已更新", "Task checkpoint updated"),
    "workspace_checkpoint_before": ("开工保护", "Pre-change protection"),
    "workspace_checkpoint_after": ("成果固化", "Post-change preservation"),
    "workspace_checkpoint_protection_armed": ("存档保护已建立", "Checkpoint protection armed"),
    "proof_recorded": ("验证证据已记录", "Verification proof recorded"),
    "impact_inspected": ("影响范围已检查", "Impact inspected"),
    "impact_recorded": ("影响与保留项已记录", "Impact and preservation recorded"),
    "policy_inspected": ("项目路径策略已检查", "Workspace path policy inspected"),
    "policy_set": ("项目路径策略已确认", "Workspace path policy confirmed"),
    "policy_approved": ("当前任务越线已批准", "Current task path crossing approved"),
    "delivery_tier_changed": ("交付档位已调整", "Delivery tier changed"),
    "status_unavailable": ("控制状态不可用", "Control state unavailable"),
    "pre_tool_use_denied": ("写入已阻止", "Write blocked"),
    "plugin_self_target": ("自身插件目录保护", "Plugin self-target guard"),
    "intake_turn_pending": ("需求澄清待分类", "Requirement intake awaiting classification"),
    "pre_git_intake_pending": ("预 Git 项目发现待处理", "Pre-Git project discovery pending"),
    "pre_git_guard_unavailable": ("预 Git 门禁不可用", "Pre-Git guard unavailable"),
    "session_activation_unavailable": ("会话启用不可用", "Session activation unavailable"),
    "intake_clear": ("需求澄清已通过", "Requirement intake cleared"),
    "intake_clarify": ("需求澄清需要补充", "Requirement intake needs clarification"),
    "intake_deep": ("深度需求澄清", "Deep requirement intake"),
    "intake_project_discovery": ("项目发现澄清", "Project discovery intake"),
    "intake_decision_resolved": ("需求决策已收敛", "Requirement decision resolved"),
    "intake_confirmed": ("需求基线已确认", "Requirement baseline confirmed"),
    "intake_reopened": ("需求基线已重新打开", "Requirement baseline reopened"),
    "project_context_adopted": ("项目上下文已收编", "Managed project context adopted"),
    "project_migrated": ("项目控制面已迁移", "Project control migrated"),
    "project_context_selected": ("项目上下文已切换", "Managed project context selected"),
    "capability_recorded": ("能力地图已更新", "Capability map updated"),
    "outcome_created": ("结果节点已创建", "Outcome created"),
    "outcome_linked": ("结果关系已连接", "Outcome relation linked"),
    "outcome_moved": ("结果节点已移动", "Outcome moved"),
    "task_attributed": ("任务归属已记录", "Task attribution recorded"),
    "activity_recorded": ("快速活动已记录", "Quick activity recorded"),
    "view_focus_changed": ("查看焦点已切换", "View focus changed"),
    "execution_focus_changed": ("执行焦点已切换", "Execution focus changed"),
    "legacy_upgrade_available": ("旧控制面可以升级", "Legacy control plane upgrade available"),
    "legacy_upgrade_current": ("控制面已是当前标准", "Control plane is current"),
    "legacy_upgrade_completed": ("旧控制面已升级", "Legacy control plane upgraded"),
    "legacy_upgrade_reverification_required": ("升级后需要真实复验", "Real revalidation required after upgrade"),
    "legacy_upgrade_manual_decision_required": ("升级需要人工决策", "Upgrade requires a manual decision"),
    "legacy_upgrade_blocked": ("控制面升级受阻", "Control plane upgrade blocked"),
    "legacy_upgrade_newer_than_cli": ("项目控制面版本高于当前工具", "Project control plane is newer than this CLI"),
    "review_ready": ("等待用户审阅", "Awaiting user review"),
    "completed": ("任务已完成", "Task completed"),
}


def bilingual_label(key: str) -> str:
    """Return the stable Chinese/English label for a control-plane event."""
    if key.startswith("subagent_"):
        return "子 Agent 协作上下文 / Subagent collaboration context"
    chinese, english = _LABELS.get(key, ("控制节点", "Control node"))
    return f"{chinese} / {english}"


def receipt(prefix: str, key: str, *details: str) -> str:
    """Format a concise user-visible receipt without translating opaque details."""
    parts = [f"{prefix}: {key}", bilingual_label(key)]
    parts.extend(detail for detail in details if detail)
    return " | ".join(parts)


def known_receipts() -> dict[str, dict[str, str]]:
    """Expose the catalog for deterministic CLI/UI readback."""
    return {
        key: {"zh": chinese, "en": english}
        for key, (chinese, english) in _LABELS.items()
    }
