"""Unit coverage for immutable inherited-contract algebra."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "auto-dev" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contract_lineage import (  # noqa: E402
    capsule,
    merge_contracts,
    normalize_contract,
    prewrite_coverage_ids,
)


class ContractLineageTest(unittest.TestCase):
    def strict_parent(self) -> dict[str, object]:
        value = normalize_contract(
            {
                "id": "SKINCARD-BASELINE",
                "mode": "legacy-parity",
                "mainline": "Migrate skin-distributor-backend; replace order entry only with card redemption.",
                "hard_constraints": [
                    {"id": "H-FORK", "text": "This is a fork and migration, not a greenfield admin."},
                ],
                "forbidden_moves": ["Do not invent an unrelated overview, jobs, or audit admin surface."],
                "replacement_map": [
                    {"id": "R-ORDER", "from": "commerce order identity", "to": "card redemption identity"},
                ],
                "required_coverage": [
                    {"id": "C-ROUTES", "description": "Legacy route matrix", "evidence_kind": "route-matrix"},
                    {"id": "C-DOWNLOAD", "description": "Legacy delivery compatibility", "evidence_kind": "compatibility"},
                ],
            },
            default_id="unused",
        )
        self.assertIsNotNone(value)
        return value or {}

    def test_merge_keeps_parent_constraints_and_adds_child_contribution(self) -> None:
        parent = self.strict_parent()
        child = normalize_contract(
            {
                "id": "M1-OUTCOME",
                "mode": "standard",
                "hard_constraints": [
                    {"id": "H-M1", "text": "The first user path must be traceable to legacy routes."},
                ],
                "required_coverage": [
                    {"id": "C-VISUAL", "description": "Legacy visual baseline", "evidence_kind": "visual-parity"},
                ],
            },
            default_id="unused",
        )
        merged = merge_contracts(parent, child)

        self.assertIsNotNone(merged)
        self.assertEqual(merged["mode"], "legacy-parity")
        self.assertEqual(
            [item["id"] for item in merged["hard_constraints"]],
            ["H-FORK", "H-M1"],
        )
        self.assertEqual(
            [item["id"] for item in merged["required_coverage"]],
            ["C-ROUTES", "C-DOWNLOAD", "C-VISUAL"],
        )
        self.assertEqual(merged["replacement_map"][0]["id"], "R-ORDER")

    def test_replaying_the_same_confirmed_contract_is_hash_stable(self) -> None:
        parent = self.strict_parent()
        replayed = merge_contracts(parent, parent)

        self.assertEqual(replayed, parent)
        self.assertEqual(replayed["hash"], parent["hash"])

    def test_conflicting_child_cannot_redefine_parent_constraint(self) -> None:
        parent = self.strict_parent()
        child = normalize_contract(
            {
                "id": "CHILD",
                "hard_constraints": [
                    {"id": "H-FORK", "text": "This may be redesigned as a new admin."},
                ],
            },
            default_id="unused",
        )

        with self.assertRaisesRegex(ValueError, "inherited contract conflict"):
            merge_contracts(parent, child)

    def test_automatic_ids_are_namespaced_per_contract(self) -> None:
        parent = normalize_contract(
            {
                "id": "PARENT",
                "mode": "strict",
                "hard_constraints": ["Keep the parent behavior."],
                "required_coverage": ["Prove the parent behavior."],
            },
            default_id="unused",
        )
        child = normalize_contract(
            {
                "id": "CHILD",
                "hard_constraints": ["Keep the child behavior."],
                "required_coverage": ["Prove the child behavior."],
            },
            default_id="unused",
        )

        merged = merge_contracts(parent, child)

        assert merged is not None
        self.assertEqual(
            [item["id"] for item in merged["hard_constraints"]],
            ["PARENT.H1", "CHILD.H1"],
        )
        self.assertEqual(
            [item["id"] for item in merged["required_coverage"]],
            ["PARENT.C1", "CHILD.C1"],
        )

    def test_child_cannot_replace_the_parent_mainline(self) -> None:
        parent = self.strict_parent()
        child = normalize_contract(
            {"id": "CHILD", "mainline": "Build a new generic admin product."},
            default_id="unused",
        )

        with self.assertRaisesRegex(ValueError, "conflict for mainline"):
            merge_contracts(parent, child)

    def test_capsule_is_compact_but_preserves_the_mainline_and_negative_constraints(self) -> None:
        parent = self.strict_parent()
        value = capsule(parent, current_node="M1", task_coverage=["C-ROUTES"])

        self.assertEqual(value["status"], "strict")
        self.assertEqual(value["mainline"], parent["mainline"])
        self.assertEqual(value["forbidden_moves"], parent["forbidden_moves"])
        self.assertEqual(value["replacement_map"], parent["replacement_map"])
        self.assertEqual([item["id"] for item in value["required_coverage"]], ["C-ROUTES"])
        self.assertLess(len(json.dumps(value, ensure_ascii=False)), 1800)

    def test_migration_contract_prioritizes_anchor_and_prewrite_coverage(self) -> None:
        contract = normalize_contract(
            {
                "id": "MIGRATION",
                "mode": "fork",
                "mainline": "Preserve the reference product path.",
                "hard_constraints": [
                    {"id": "H-NORMAL", "text": "A lower-priority constraint."},
                    {"id": "H-ANCHOR", "text": "Never replace the reference path.", "anchor": True},
                ],
                "required_coverage": [
                    {
                        "id": "C-REFERENCE",
                        "description": "Reference route matrix",
                        "evidence_kind": "route-matrix",
                        "artifact_schema": "auto-dev/reference-matrix/v1",
                    }
                ],
            },
            default_id="unused",
        )

        self.assertIsNotNone(contract)
        assert contract is not None
        self.assertEqual(prewrite_coverage_ids(contract), ["C-REFERENCE"])
        value = capsule(contract, task_coverage=["C-REFERENCE"])
        self.assertEqual(value["hard_constraints"][0]["id"], "H-ANCHOR")
        self.assertEqual(value["required_coverage"][0]["write_gate"], "before_product_write")
        self.assertEqual(value["required_coverage"][0]["artifact_schema"], "auto-dev/reference-matrix/v1")

    def test_evidence_artifact_shape_is_part_of_the_contract_data(self) -> None:
        contract = normalize_contract(
            {
                "id": "ARTIFACT",
                "mode": "strict",
                "mainline": "Keep evidence traceable.",
                "required_coverage": [
                    {
                        "id": "C-TRACE",
                        "description": "Traceability manifest",
                        "evidence_kind": "artifact",
                        "artifact_schema": "auto-dev/trace/v1",
                    }
                ],
            },
            default_id="unused",
        )

        assert contract is not None
        self.assertEqual(contract["required_coverage"][0]["artifact_schema"], "auto-dev/trace/v1")


if __name__ == "__main__":
    unittest.main()
