"""Outcome contracts and product review lifecycle."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

def load_product_review_input(control, args: argparse.Namespace) -> dict[str, Any] | None:
    product_review_file = getattr(args, "product_review_file", None)
    product_review_json = getattr(args, "product_review_json", None)
    if product_review_file and product_review_json:
        raise ValueError("provide at most one of --product-review-file or --product-review-json")
    if not product_review_file and not product_review_json:
        return None
    try:
        raw = (
            pathlib.Path(product_review_file).expanduser().read_text(encoding="utf-8")
            if product_review_file
            else product_review_json
        )
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"product review must be valid JSON: {error}") from error
    return normalize_product_review(control, payload)


def normalize_product_review(control, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("product review must be a JSON object")
    allowed = {"completed", "purpose", "next_step", "user_impact", "test"}
    unknown = sorted(set(raw) - allowed - {"schema_version"})
    if unknown:
        raise ValueError(f"product review has unsupported fields: {', '.join(unknown)}")

    def text(label: str, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string")
        return control.require_concrete(label, value)

    completed = text("product review completed", raw.get("completed"))
    purpose = text("product review purpose", raw.get("purpose"))
    next_step = text("product review next step", raw.get("next_step"))
    user_impact = text("product review user impact", raw.get("user_impact"))
    raw_test = raw.get("test")
    if not isinstance(raw_test, dict):
        raise ValueError("product review test must be a JSON object")
    allowed_test = {"status", "entry", "role", "steps", "expected", "prerequisites", "reason"}
    unknown_test = sorted(set(raw_test) - allowed_test)
    if unknown_test:
        raise ValueError(f"product review test has unsupported fields: {', '.join(unknown_test)}")
    test_status = text("product review test status", raw_test.get("status"))
    if test_status not in control.PRODUCT_REVIEW_TEST_STATUSES:
        raise ValueError(
            "product review test status must be one of: "
            + ", ".join(sorted(control.PRODUCT_REVIEW_TEST_STATUSES))
        )

    def text_list(label: str, value: Any, *, required: bool = False) -> list[str]:
        if value is None:
            if required:
                raise ValueError(f"{label} requires at least one value")
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{label} must be a list of strings")
        if required and not value:
            raise ValueError(f"{label} requires at least one value")
        result: list[str] = []
        for item in value:
            concrete = control.require_concrete(label, item)
            if concrete not in result:
                result.append(concrete)
        return result

    test: dict[str, Any] = {"status": test_status}
    if test_status == "ready":
        test["entry"] = text("product review test entry", raw_test.get("entry"))
        test["role"] = text("product review test role", raw_test.get("role"))
        test["steps"] = text_list("product review test step", raw_test.get("steps"), required=True)
        test["expected"] = text("product review test expected result", raw_test.get("expected"))
        prerequisites = text_list("product review test prerequisite", raw_test.get("prerequisites"))
        if prerequisites:
            test["prerequisites"] = prerequisites
    else:
        test["reason"] = text("product review test reason", raw_test.get("reason"))
        entry = raw_test.get("entry")
        if entry is not None:
            test["entry"] = text("product review test entry", entry)

    return {
        "schema_version": control.PRODUCT_REVIEW_SCHEMA_VERSION,
        "completed": completed,
        "purpose": purpose,
        "next_step": next_step,
        "user_impact": user_impact,
        "test": test,
    }


def product_review_receipt(control, 
    product_review: dict[str, Any] | None,
    e2e_evidence: list[dict[str, Any]] | None = None,
    release_evidence: list[dict[str, Any]] | None = None,
) -> str:
    lines: list[str]
    if product_review is None:
        lines = [
            "💡 Auto Dev 产品验收回执",
            "产品验收摘要未提供：请补充本阶段完成内容、用户变化和测试入口，再交给产品同学验收。",
        ]
    else:
        test = product_review["test"]
        lines = [
            "💡 Auto Dev 产品验收回执",
            f"本阶段完成：{product_review['completed']}",
            f"目的与下一步：{product_review['purpose']}；{product_review['next_step']}",
            f"用户变化：{product_review['user_impact']}",
        ]
        if test["status"] == "ready":
            lines.extend([
                f"请测试：{test['entry']}（{test['role']}）",
                f"步骤：{'；'.join(test['steps'])}",
                f"预期：{test['expected']}",
            ])
            if test.get("prerequisites"):
                lines.append(f"前置条件：{'；'.join(test['prerequisites'])}")
        elif test["status"] == "blocked":
            lines.append(f"测试状态：暂不可测。{test['reason']}")
        else:
            lines.append(f"测试状态：暂无直接用户入口。{test['reason']}")
    for evidence in e2e_evidence or []:
        checks = evidence.get("checks") if isinstance(evidence.get("checks"), dict) else {}
        status_labels = {"passed": "通过", "partial": "部分通过", "blocked": "阻塞"}
        lines.extend([
            "",
            "E2E 自动验证",
            f"验证结果：{status_labels.get(evidence.get('result'), evidence.get('result', '未知'))}",
            f"用户流程：{evidence.get('user_flow', '-')}",
            f"测试环境：{evidence.get('environment', '-')}",
            f"页面表现：{checks.get('page', '-')}",
            f"数据交互：{checks.get('data_interaction', '-')}",
            f"系统结果：{checks.get('system_result', '-')}",
            f"尚未验证：{'；'.join(evidence.get('unverified', [])) or '无'}",
            f"产品下一步：{evidence.get('next_step', '-')}",
        ])
        gui = evidence.get("gui") if isinstance(evidence.get("gui"), dict) else None
        if gui is not None:
            cases = gui.get("cases") if isinstance(gui.get("cases"), list) else []
            case_summary = "；".join(
                f"{case.get('id', '-')}={case.get('status', '-')}"
                for case in cases
                if isinstance(case, dict)
            )
            bundle = gui.get("evidence") if isinstance(gui.get("evidence"), dict) else {}
            bundle_keys = "；".join(
                key for key, value in bundle.items()
                if isinstance(value, list) and value
            )
            lines.extend([
                f"GUI 执行：{gui.get('executor', '-')}（可视化：{gui.get('visual_mode', '-')}）",
                f"GUI 用例：{case_summary or '-'}",
                f"GUI 证据：{bundle_keys or '-'}",
            ])
            fallback = gui.get("manual_fallback")
            if isinstance(fallback, dict):
                lines.append(f"GUI 手测原因：{fallback.get('reason', '-')}")
    release_status_labels = {
        "succeeded": "成功", "partial": "部分完成", "rolled_back": "已回滚", "blocked": "阻塞",
    }
    check_status_labels = {
        "passed": "通过", "failed": "失败", "blocked": "阻塞", "not_applicable": "不适用",
    }
    rollback_status_labels = {
        "ready": "就绪", "executed": "已执行", "not_ready": "未就绪", "not_applicable": "不适用",
    }
    for evidence in release_evidence or []:
        health = evidence.get("health") if isinstance(evidence.get("health"), dict) else {}
        user_flow = evidence.get("user_flow") if isinstance(evidence.get("user_flow"), dict) else {}
        rollback = evidence.get("rollback") if isinstance(evidence.get("rollback"), dict) else {}
        lines.extend([
            "",
            "发布验证",
            f"最终状态：{release_status_labels.get(evidence.get('result'), evidence.get('result', '未知'))}",
            f"目标环境：{evidence.get('environment', '-')}",
            f"部署版本：{evidence.get('version', '-')}",
            f"健康检查：{check_status_labels.get(health.get('status'), health.get('status', '未知'))}。{health.get('summary', '-')}",
            f"关键用户流程：{check_status_labels.get(user_flow.get('status'), user_flow.get('status', '未知'))}。{user_flow.get('summary', '-')}",
            "回滚准备："
            f"{rollback_status_labels.get(rollback.get('status'), rollback.get('status', '未知'))}；"
            f"触发：{rollback.get('trigger', '-')}；目标：{rollback.get('target', '-')}",
            f"尚未验证：{'；'.join(evidence.get('unverified', [])) or '无'}",
            f"产品下一步：{evidence.get('next_step', '-')}",
        ])
    return "\n".join(lines)


def normalize_outcome(control, 
    raw: Any,
    previous: dict[str, Any],
    *,
    node_id: str,
) -> dict[str, Any] | None:
    if raw is None:
        # Existing control state remains readable and can finish its old plan. Every
        # newly introduced node, however, must carry an outcome contract.
        if previous:
            return previous.get("outcome")
        raise ValueError(f"node {node_id} requires an outcome contract")
    if not isinstance(raw, dict):
        raise ValueError(f"node {node_id} outcome must be an object")
    kind = control.require_concrete("outcome kind", str(raw.get("kind", "")))
    if kind not in control.OUTCOME_KINDS:
        raise ValueError(f"node {node_id} has unsupported outcome kind: {kind}")
    primary = control.require_concrete("primary outcome", str(raw.get("primary", "")))
    document_authorization = raw.get("document_authorization")
    if kind == "document":
        document_authorization = control.require_concrete(
            "document outcome authorization", str(document_authorization or "")
        )
    elif document_authorization is not None:
        raise ValueError("document outcome authorization is only valid for kind=document")
    raw_proofs = raw.get("proofs")
    if not isinstance(raw_proofs, list) or not raw_proofs:
        raise ValueError(f"node {node_id} outcome requires at least one proof")
    proofs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_proof in raw_proofs:
        if not isinstance(raw_proof, dict):
            raise ValueError(f"node {node_id} outcome proof must be an object")
        proof_id = control.require_proof_id(str(raw_proof.get("id", "")))
        if proof_id in seen:
            raise ValueError(f"node {node_id} has duplicate proof id: {proof_id}")
        seen.add(proof_id)
        evidence_kind = str(raw_proof.get("evidence_kind") or "supporting")
        if evidence_kind not in control.EVIDENCE_KINDS:
            raise ValueError(f"node {node_id} proof has unsupported evidence kind: {evidence_kind}")
        coverage_values = raw_proof.get("coverage_ids", [])
        if isinstance(coverage_values, str):
            coverage_values = [coverage_values]
        if not isinstance(coverage_values, list):
            raise ValueError(f"node {node_id} proof coverage_ids must be an array")
        coverage = [
            control.require_control_id("proof coverage id", str(value))
            for value in coverage_values
        ]
        proof_record: dict[str, Any] = {
            "id": proof_id,
            "description": control.require_concrete("proof description", str(raw_proof.get("description", ""))),
            "evidence_kind": evidence_kind,
            "coverage_ids": list(dict.fromkeys(coverage)),
        }
        raw_recipe = raw_proof.get("recipe")
        if raw_recipe is not None:
            if not isinstance(raw_recipe, dict):
                raise ValueError(f"node {node_id} proof recipe must be an object")
            unknown_recipe = sorted(set(raw_recipe) - {
                "argv", "cwd", "inputs", "observed_paths", "preflight_argv",
                "evidence_file", "evidence_schema",
            })
            if unknown_recipe:
                raise ValueError(
                    f"node {node_id} proof recipe has unsupported fields: "
                    + ", ".join(unknown_recipe)
                )
            argv = raw_recipe.get("argv")
            if not isinstance(argv, list) or not argv:
                raise ValueError(f"node {node_id} proof recipe requires a non-empty argv array")
            normalized_argv = [
                control.require_concrete("proof recipe argument", str(value)) for value in argv
            ]
            recipe = {"argv": normalized_argv}
            if raw_recipe.get("cwd") is not None:
                recipe["cwd"] = control.require_concrete(
                    "proof recipe cwd", str(raw_recipe["cwd"])
                )
            for key in ("inputs", "observed_paths"):
                values = raw_recipe.get(key)
                if values is not None:
                    if not isinstance(values, list):
                        raise ValueError(f"node {node_id} proof recipe {key} must be an array")
                    recipe[key] = [
                        control.require_concrete(f"proof recipe {key} path", str(value))
                        for value in values
                    ]
            if raw_recipe.get("preflight_argv") is not None:
                values = raw_recipe["preflight_argv"]
                if not isinstance(values, list) or not values:
                    raise ValueError(
                        f"node {node_id} proof recipe preflight_argv must be a non-empty array"
                    )
                recipe["preflight_argv"] = [
                    control.require_concrete("proof preflight argument", str(value))
                    for value in values
                ]
            if raw_recipe.get("evidence_file") is not None:
                recipe["evidence_file"] = control.require_concrete(
                    "proof recipe evidence file", str(raw_recipe["evidence_file"])
                )
            if raw_recipe.get("evidence_schema") is not None:
                recipe["evidence_schema"] = control.require_concrete(
                    "proof recipe evidence schema", str(raw_recipe["evidence_schema"])
                )
            proof_record["recipe"] = recipe
        proofs.append(proof_record)
    return {
        "kind": kind,
        "primary": primary,
        "proofs": proofs,
        **({"document_authorization": document_authorization} if document_authorization else {}),
    }


def command_task_review(control, args: argparse.Namespace) -> int:
    repo = control.resolve_repo(args.repo_root)
    state = control.ensure_root(repo)
    receipt = control.require_working_task(state)
    loaded_revision = int(receipt.get("state_revision", 0))
    if args.state_revision != loaded_revision:
        raise ValueError(
            f"state revision conflict: expected {loaded_revision}, received {args.state_revision}"
        )
    control.validate_completion_readiness(repo, state, receipt)
    prepared_at = control.now()
    product_review = load_product_review_input(control, args)
    e2e_evidence = control.task_e2e_evidence(repo, receipt)
    release_evidence = control.task_release_evidence(repo, receipt)
    review = {
        "summary": control.require_concrete("review summary", args.summary),
        "changed_files": [control.require_concrete("changed file", value) for value in args.file],
        "validation_results": control.require_concrete_list("validation result", args.validation),
        "remaining_risks": [control.require_concrete("remaining risk", value) for value in args.risk],
        "prepared_at": prepared_at,
        "prepared_head": control.git_head(repo),
        "prepared_status": control.workspace_product_status(control.current_status(repo)),
        "product_review_status": (
            product_review.get("test", {}).get("status") if product_review else "missing"
        ),
    }
    if product_review is not None:
        review["product_review"] = product_review
    if e2e_evidence:
        review["e2e_evidence"] = e2e_evidence
    if release_evidence:
        review["release_evidence"] = release_evidence
    receipt["status"] = "review_ready"
    receipt["review"] = review
    control.continuity_event(
        receipt,
        "review_ready",
        summary=review["summary"],
        validation_results=review["validation_results"],
        remaining_risks=review["remaining_risks"],
    )
    next_revision = control.write_active(state, receipt, expected_revision=loaded_revision)
    print(json.dumps({
        "status": "review_ready",
        "task_id": receipt["id"],
        "state_revision": next_revision,
        "review": review,
        "product_review": product_review,
        "product_receipt": product_review_receipt(control, 
            product_review, e2e_evidence, release_evidence,
        ),
        "receipt": control.bilingual_receipt("🧾 Auto Dev", "review_ready", f"task={receipt['id']}"),
    }, ensure_ascii=False))
    return 0
