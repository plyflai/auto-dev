"""Legacy upgrade data model and control-plane surface registry."""

from __future__ import annotations

from dataclasses import dataclass, field
import pathlib
from typing import Any, Callable

import project_memory
from auto_dev_internal.foundation.core import (
    SCHEMA_VERSION, PROJECT_SCHEMA_VERSION, CONTINUITY_SCHEMA_VERSION,
    RUNTIME_DIAGNOSTICS_SCHEMA_VERSION, WORKSPACE_POLICY_SCHEMA_VERSION,
    VERIFICATION_GATE_POLICY,
)

@dataclass
class LegacyUpgradeTask:
    identifier: str
    receipt: dict[str, Any]
    task_path: pathlib.Path | None
    active_projection: bool = False


@dataclass
class LegacyUpgradePlan:
    repo: pathlib.Path
    state: dict[str, pathlib.Path]
    project: dict[str, Any]
    project_exists: bool
    project_revision: int
    current_version: int
    target_version: int
    timestamp: str
    source_project_schema: int | None = None
    tasks: dict[str, LegacyUpgradeTask] = field(default_factory=dict)
    active_task_id: str | None = None
    active_task_revision: int | None = None
    pending_steps: list["LegacyUpgradeStep"] = field(default_factory=list)
    writes: dict[pathlib.Path, dict[str, Any] | str] = field(default_factory=dict)
    changes: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    unsupported_records: list[dict[str, Any]] = field(default_factory=list)
    historical_runs: dict[str, Any] = field(default_factory=dict)
    state_surfaces: list[dict[str, Any]] = field(default_factory=list)
    revalidation_targets: list[dict[str, Any]] = field(default_factory=list)
    manual_decisions: list[dict[str, Any]] = field(default_factory=list)
    newer_than_cli: list[dict[str, Any]] = field(default_factory=list)
    fingerprint: str | None = None

    def add_blocker(self, code: str, detail: str, *, path: pathlib.Path | None = None) -> None:
        payload: dict[str, Any] = {"code": code, "detail": detail}
        if path is not None:
            payload["path"] = upgrade_relative_path(self.state, path)
        self.blockers.append(payload)

    def add_warning(self, code: str, detail: str, *, path: pathlib.Path | None = None) -> None:
        payload: dict[str, Any] = {"code": code, "detail": detail}
        if path is not None:
            payload["path"] = upgrade_relative_path(self.state, path)
        self.warnings.append(payload)

    def queue_write(
        self,
        path: pathlib.Path,
        payload: dict[str, Any],
        *,
        record_type: str,
        record_id: str | None = None,
    ) -> None:
        relative = upgrade_relative_path(self.state, path)
        if path not in self.writes:
            change: dict[str, Any] = {
                "operation": "update" if path.exists() else "create",
                "path": relative,
                "record_type": record_type,
            }
            if record_id:
                change["record_id"] = record_id
            self.changes.append(change)
        self.writes[path] = payload

    def queue_text(
        self,
        path: pathlib.Path,
        payload: str,
        *,
        record_type: str,
    ) -> None:
        relative = upgrade_relative_path(self.state, path)
        if path not in self.writes:
            self.changes.append({
                "operation": "update" if path.exists() else "create",
                "path": relative,
                "record_type": record_type,
            })
        self.writes[path] = payload


@dataclass(frozen=True)
class LegacyUpgradeStep:
    version: int
    identifier: str
    title: str
    description: str
    planner: Callable[[LegacyUpgradePlan], None]
    surface_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ControlPlaneStateSurface:
    identifier: str
    storage: str
    target_schema: int | str
    contract_revision: int
    impact: str
    adopted_in_version: int


CONTROL_PLANE_STATE_SURFACES: tuple[ControlPlaneStateSurface, ...] = (
    ControlPlaneStateSurface("project", ".auto-dev/project.json", PROJECT_SCHEMA_VERSION, 2, "structural", 2),
    ControlPlaneStateSurface("task_receipts", ".auto-dev/tasks/*.json", SCHEMA_VERSION, 2, "additive", 2),
    ControlPlaneStateSurface("continuity", "task.continuity", CONTINUITY_SCHEMA_VERSION, 2, "structural", 2),
    ControlPlaneStateSurface("proof_attempts", "task.continuity.proofs", "append-only-v1", 2, "semantic", 2),
    ControlPlaneStateSurface(
        "project_memory", ".auto-dev/project-memory.json",
        project_memory.REGISTRY_SCHEMA_VERSION, 3, "structural", 4,
    ),
    ControlPlaneStateSurface(
        "environment_projection", ".auto-dev/path.md",
        "environment-profile-v1", 1, "additive", 4,
    ),
    ControlPlaneStateSurface(
        "domain_projection", ".auto-dev/project-domain.md",
        "domain-memory-v1", 1, "additive", 4,
    ),
    ControlPlaneStateSurface(
        "dependency_lease", ".auto-dev/dependency-lease.json",
        project_memory.LEASE_SCHEMA_VERSION, 2, "additive", 2,
    ),
    ControlPlaneStateSurface(
        "runtime_diagnostics", ".auto-dev/runtime-diagnostics.json",
        RUNTIME_DIAGNOSTICS_SCHEMA_VERSION, 1, "additive", 2,
    ),
    ControlPlaneStateSurface(
        "workspace_policy", ".auto-dev/config.json",
        WORKSPACE_POLICY_SCHEMA_VERSION, 1, "manual", 2,
    ),
    ControlPlaneStateSurface("handoff_packet", "external handoff packet", 1, 1, "none", 2),
    ControlPlaneStateSurface(
        "verification_gate_policy", "project.verification_gate_policy",
        VERIFICATION_GATE_POLICY, 1, "semantic", 3,
    ),
    ControlPlaneStateSurface(
        "plan_strategy", "task.continuity.plan",
        "plan-strategy-v1", 1, "additive", 5,
    ),
)

def bind(control) -> None:
    """Resolve facade-owned helpers used by model methods and registry values."""
    for name in ("upgrade_relative_path",):
        globals()[name] = getattr(control, name)
