"""Regression coverage for environment/domain memory and legacy-material boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
SCRIPTS = CLI.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import runctl  # noqa: E402
import project_memory  # noqa: E402


class EnvironmentDomainMemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-environment-domain-")
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        legacy = self.repo / ".autodev"
        legacy.mkdir()
        (legacy / "path.md").write_text(
            "legacy endpoint https://legacy.example.invalid\n", encoding="utf-8"
        )
        (legacy / "project-domain.md").write_text(
            "LegacyTerminology must never be imported automatically\n", encoding="utf-8"
        )
        (legacy / "current-test.md").write_text("old green result\n", encoding="utf-8")
        self.exec("git", "init", "-q")
        self.exec("git", "config", "user.name", "Auto Dev Environment Test")
        self.exec("git", "config", "user.email", "auto-dev-environment@example.com")
        self.exec("git", "add", "README.md")
        self.exec("git", "commit", "-qm", "initial")
        self.exec("git", "checkout", "-qb", "environment-domain")
        self.cli("project", "init", "--confirmation-source", "environment fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def exec(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments),
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check:
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
        return result

    def cli(self, *arguments: str, check: bool = True) -> dict[str, Any]:
        result = self.exec(
            sys.executable,
            str(CLI),
            *arguments,
            "--repo-root",
            str(self.repo),
            check=check,
        )
        if not check:
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        return json.loads(result.stdout)

    def control_snapshot(self) -> dict[str, bytes]:
        root = self.repo / ".auto-dev"
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and not path.name.endswith(".lock")
        }

    def test_project_init_creates_new_projections_without_importing_legacy_material(self) -> None:
        control = self.repo / ".auto-dev"
        memory = json.loads((control / "project-memory.json").read_text(encoding="utf-8"))
        self.assertEqual(memory["schema_version"], 4)
        self.assertEqual(memory["environment_profile"]["host"]["id"], "local")
        self.assertEqual(memory["environment_profile"]["working_roots"][0]["id"], "repository")
        self.assertEqual(memory["environment_profile"]["allowed_roots"], [str(self.repo.resolve())])
        self.assertEqual(memory["domain_memory"]["terms"], [])
        path_projection = (control / "path.md").read_text(encoding="utf-8")
        domain_projection = (control / "project-domain.md").read_text(encoding="utf-8")
        self.assertIn("Generated from `.auto-dev/project-memory.json`", path_projection)
        self.assertIn(str(self.repo.resolve()), path_projection)
        self.assertNotIn("legacy.example.invalid", path_projection)
        self.assertNotIn("LegacyTerminology", domain_projection)
        status = self.cli("status", "--compact")
        self.assertNotIn("legacy_artifact_candidates", status)
        self.assertNotIn("legacy.example.invalid", json.dumps(status, ensure_ascii=False))

    def test_environment_and_domain_writes_are_revisioned_and_regenerate_projections(self) -> None:
        inspected = self.cli("environment", "inspect")
        profile = {
            "allowed_roots": [str(self.repo.resolve()), "/srv/checkout"],
            "endpoints": [
                {
                    "id": "staging",
                    "url": "https://staging.example.test",
                    "purpose": "checkout verification",
                    "environment": "staging",
                }
            ],
            "locations": [
                {"id": "logs", "path": "/srv/checkout/logs", "purpose": "request diagnostics"}
            ],
            "operations": [
                {
                    "id": "gui-checkout",
                    "kind": "gui",
                    "argv": ["npx", "playwright", "test", "--headed"],
                    "purpose": "run checkout GUI verification",
                    "working_directory": str(self.repo.resolve()),
                    "evidence_root": "artifacts/gui",
                }
            ],
            "gui": {
                "executor": "playwright",
                "visual_mode": "required",
                "evidence_roots": ["artifacts/gui"],
                "devices": ["Desktop Chrome"],
            },
        }
        updated = self.cli(
            "environment",
            "set",
            "--memory-revision",
            str(inspected["memory_revision"]),
            "--confirmation-source",
            "user confirmed environment facts",
            "--profile-json",
            json.dumps(profile),
        )
        self.assertEqual(updated["status"], "updated")
        path_projection = (self.repo / ".auto-dev" / "path.md").read_text(encoding="utf-8")
        self.assertIn("https://staging.example.test", path_projection)
        self.assertIn("playwright", path_projection)
        stale = self.cli(
            "environment",
            "set",
            "--memory-revision",
            str(inspected["memory_revision"]),
            "--confirmation-source",
            "stale confirmation",
            "--profile-json",
            json.dumps(profile),
            check=False,
        )
        self.assertNotEqual(stale["returncode"], 0)
        self.assertIn("memory revision conflict", stale["stderr"])
        domain = {
            "terms": [
                {
                    "name": "claim",
                    "definition": "A user request to redeem one credential.",
                    "relations": ["credential", "redemption"],
                    "source": "product policy",
                    "status": "active",
                }
            ],
            "invariants": [
                {
                    "id": "one-claim-per-credential",
                    "rule": "A credential can have at most one completed claim.",
                    "scope": "credential redemption",
                    "source": "product policy",
                }
            ],
            "ambiguities": [],
            "decisions": [
                {
                    "id": "credential-identity",
                    "decision": "Use credential ID as the stable claim identity.",
                    "rationale": "Order numbers are not unique across retries.",
                    "source": "ADR-12",
                    "status": "active",
                }
            ],
        }
        domain_updated = self.cli(
            "domain",
            "set",
            "--memory-revision",
            str(updated["memory_revision"]),
            "--confirmation-source",
            "user confirmed domain memory",
            "--domain-json",
            json.dumps(domain),
        )
        self.assertEqual(domain_updated["status"], "updated")
        domain_projection = (self.repo / ".auto-dev" / "project-domain.md").read_text(encoding="utf-8")
        self.assertIn("one-claim-per-credential", domain_projection)
        unsafe = dict(profile)
        unsafe["endpoints"] = [{
            "id": "unsafe",
            "url": "https://example.test/?api_key=do-not-store",
            "purpose": "unsafe fixture",
        }]
        rejected = self.cli(
            "environment",
            "set",
            "--memory-revision",
            str(domain_updated["memory_revision"]),
            "--confirmation-source",
            "reject credential fixture",
            "--profile-json",
            json.dumps(unsafe),
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("credential or secret", rejected["stderr"])
        unsafe_cookie = dict(profile)
        unsafe_cookie["endpoints"] = [{
            "id": "unsafe-cookie",
            "url": "https://example.test/",
            "purpose": "Cookie: do-not-store",
        }]
        cookie_rejected = self.cli(
            "environment",
            "set",
            "--memory-revision",
            str(domain_updated["memory_revision"]),
            "--confirmation-source",
            "reject cookie fixture",
            "--profile-json",
            json.dumps(unsafe_cookie),
            check=False,
        )
        self.assertNotEqual(cookie_rejected["returncode"], 0)
        self.assertIn("credential or secret", cookie_rejected["stderr"])

    def test_only_explicit_legacy_inspect_scans_old_materials_without_importing_them(self) -> None:
        before = self.control_snapshot()
        internal = runctl.legacy_upgrade_inspection_payload(
            self.repo.resolve(), runctl.paths(self.repo.resolve())
        )
        self.assertFalse(internal["legacy_material_scan"]["performed"])
        self.assertEqual(internal["legacy_artifact_candidates"], [])
        inspection = self.cli("legacy-upgrade", "inspect")
        self.assertEqual(inspection["status"], "current")
        self.assertTrue(inspection["legacy_material_scan"]["performed"])
        candidates = {item["path"]: item for item in inspection["legacy_artifact_candidates"]}
        path_candidate = candidates[".autodev/path.md"]
        self.assertEqual(path_candidate["kind"], "environment_path")
        self.assertEqual(path_candidate["content_handling"], "digest_only")
        self.assertEqual(path_candidate["import_policy"], "manual_reentry_required")
        self.assertEqual(
            path_candidate["sha256"],
            hashlib.sha256((self.repo / ".autodev" / "path.md").read_bytes()).hexdigest(),
        )
        self.assertNotIn("legacy.example.invalid", json.dumps(inspection, ensure_ascii=False))
        self.assertEqual(before, self.control_snapshot())

    def test_v3_memory_upgrade_preserves_the_existing_cas_revision(self) -> None:
        legacy_memory = self.repo / "legacy-project-memory.json"
        legacy_memory.write_text(json.dumps({
            "schema_version": 3,
            "memory_revision": 7,
            "updated_at": "2026-08-05T00:00:00+00:00",
            "entries": [],
            "attempts": [],
        }), encoding="utf-8")
        normalized = project_memory.load(legacy_memory)
        self.assertEqual(normalized["schema_version"], 4)
        self.assertEqual(normalized["memory_revision"], 7)


if __name__ == "__main__":
    unittest.main()
