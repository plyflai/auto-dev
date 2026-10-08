"""Pure evidence-manifest checks for strict contract proofs."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "auto-dev" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from runctl import read_e2e_evidence, read_evidence_artifact, read_release_evidence  # noqa: E402


class ContractEvidenceTest(unittest.TestCase):
    def test_release_manifest_is_normalized_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-dev-release-evidence-") as directory:
            repo = Path(directory)
            artifact = repo / "release.json"
            artifact.write_text(json.dumps({
                "schema": "auto-dev/release-evidence/v1",
                "source_ref": "ci/run/123",
                "result": "succeeded",
                "environment": "staging",
                "version": "v2.4.1",
                "health": {"status": "passed", "summary": "Service is healthy"},
                "user_flow": {"status": "passed", "summary": "Login smoke passed"},
                "rollback": {
                    "status": "ready",
                    "trigger": "Health or login smoke fails",
                    "target": "v2.4.0",
                },
                "unverified": ["Real payment"],
                "next_step": "Product can begin staging acceptance",
            }), encoding="utf-8")

            result = read_release_evidence(repo, "release.json")

            self.assertEqual(result["schema"], "auto-dev/release-evidence/v1")
            self.assertEqual(result["rollback"]["target"], "v2.4.0")
            self.assertRegex(str(result["sha256"]), r"^[0-9a-f]{64}$")

    def test_release_manifest_rejects_secrets_missing_fields_and_invalid_rollback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-dev-release-evidence-") as directory:
            repo = Path(directory)
            artifact = repo / "release.json"
            manifest = {
                "schema": "auto-dev/release-evidence/v1",
                "source_ref": "ci/run/123",
                "result": "succeeded",
                "environment": "staging",
                "version": "v2.4.1",
                "health": {"status": "passed", "summary": "Service is healthy"},
                "user_flow": {"status": "passed", "summary": "Login smoke passed"},
                "rollback": {
                    "status": "ready",
                    "trigger": "Health or login smoke fails",
                    "target": "v2.4.0",
                },
                "unverified": [],
                "next_step": "Product can begin staging acceptance",
            }
            missing = dict(manifest)
            missing.pop("version")
            artifact.write_text(json.dumps(missing), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fields must contain"):
                read_release_evidence(repo, "release.json")

            secret = {**manifest, "health": {"status": "passed", "summary": "password=secret"}}
            artifact.write_text(json.dumps(secret), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "credential or secret"):
                read_release_evidence(repo, "release.json")

            rolled_back = {
                **manifest,
                "result": "rolled_back",
                "rollback": {**manifest["rollback"], "status": "ready"},
            }
            artifact.write_text(json.dumps(rolled_back), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires rollback status executed"):
                read_release_evidence(repo, "release.json")

    def test_e2e_manifest_is_normalized_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-dev-e2e-evidence-") as directory:
            repo = Path(directory)
            artifact = repo / "e2e.json"
            artifact.write_text(
                json.dumps({
                    "schema": "auto-dev/e2e-evidence/v1",
                    "source_ref": "playwright-report/checkout.html",
                    "result": "passed",
                    "user_flow": "A customer submits an order",
                    "environment": "staging",
                    "checks": {
                        "page": "The order confirmation is visible",
                        "data_interaction": "The submit request returns successfully",
                        "system_result": "The order is recorded with the expected total",
                    },
                    "unverified": ["Real payment is not covered"],
                    "next_step": "Product can verify the flow with a test account",
                }),
                encoding="utf-8",
            )

            result = read_e2e_evidence(repo, "e2e.json")

            self.assertEqual(result["schema"], "auto-dev/e2e-evidence/v1")
            self.assertEqual(result["checks"]["page"], "The order confirmation is visible")
            self.assertRegex(str(result["sha256"]), r"^[0-9a-f]{64}$")

    def test_e2e_manifest_rejects_missing_check_and_sensitive_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-dev-e2e-evidence-") as directory:
            repo = Path(directory)
            artifact = repo / "e2e.json"
            artifact.write_text(json.dumps({
                "schema": "auto-dev/e2e-evidence/v1",
                "source_ref": "report",
                "result": "passed",
                "user_flow": "flow",
                "environment": "staging",
                "checks": {"page": "ok", "data_interaction": "ok"},
                "unverified": [],
                "next_step": "review",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checks must contain"):
                read_e2e_evidence(repo, "e2e.json")

            artifact.write_text(json.dumps({
                "schema": "auto-dev/e2e-evidence/v1",
                "source_ref": "report",
                "result": "passed",
                "user_flow": "password=secret",
                "environment": "staging",
                "checks": {"page": "ok", "data_interaction": "ok", "system_result": "ok"},
                "unverified": [],
                "next_step": "review",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "credential or secret"):
                read_e2e_evidence(repo, "e2e.json")
    def test_reference_manifest_is_read_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-dev-evidence-") as directory:
            repo = Path(directory)
            artifact = repo / "reference.json"
            artifact.write_text(
                json.dumps(
                    {
                        "schema": "auto-dev/reference-matrix/v1",
                        "coverage_ids": ["C-REFERENCE"],
                        "source_ref": "legacy@abc123",
                        "entries": [{"source": "/legacy", "target": "/new"}],
                    }
                ),
                encoding="utf-8",
            )

            result = read_evidence_artifact(
                repo,
                "reference.json",
                expected_schemas={"auto-dev/reference-matrix/v1"},
                coverage_ids={"C-REFERENCE"},
            )

            self.assertEqual(result["path"], "reference.json")
            self.assertEqual(result["source_ref"], "legacy@abc123")
            self.assertRegex(str(result["sha256"]), r"^[0-9a-f]{64}$")

    def test_reference_manifest_rejects_missing_coverage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-dev-evidence-") as directory:
            repo = Path(directory)
            (repo / "reference.json").write_text(
                json.dumps(
                    {
                        "schema": "auto-dev/reference-matrix/v1",
                        "coverage_ids": ["C-OTHER"],
                        "source_ref": "legacy@abc123",
                        "entries": [{"source": "/legacy", "target": "/new"}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "does not cover"):
                read_evidence_artifact(
                    repo,
                    "reference.json",
                    expected_schemas={"auto-dev/reference-matrix/v1"},
                    coverage_ids={"C-REFERENCE"},
                )


if __name__ == "__main__":
    unittest.main()
