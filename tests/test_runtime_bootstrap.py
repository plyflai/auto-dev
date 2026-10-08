"""Runtime bootstrap selection coverage for installed Auto Dev upgrades."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = PLUGIN_ROOT / "scripts" / "runtime_bootstrap.py"
SPEC = importlib.util.spec_from_file_location("auto_dev_runtime_bootstrap", BOOTSTRAP)
assert SPEC is not None and SPEC.loader is not None
runtime_bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_bootstrap)


class RuntimeBootstrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-runtime-bootstrap-")
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.data = self.root / "data"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_bundle(self, name: str, version: str) -> Path:
        bundle = self.cache / name
        required = [
            ".codex-plugin/plugin.json",
            "scripts/runtime_bootstrap.py",
            "scripts/hook_dispatch.py",
            "skills/auto-dev/scripts/auto_dev.py",
            "skills/auto-dev/scripts/auto_dev_internal/task/workers.py",
            "skills/refresh/SKILL.md",
        ]
        for relative in required:
            path = bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative == ".codex-plugin/plugin.json":
                path.write_text(
                    json.dumps({"name": "auto-dev", "version": version}),
                    encoding="utf-8",
                )
            else:
                path.write_text("# fixture\n", encoding="utf-8")
        return bundle

    def test_recent_usable_sibling_precedes_configured_bundle(self) -> None:
        configured = self.make_bundle("1.0.0+codex.old", "1.0.0+codex.old")
        current = self.make_bundle("1.0.0+codex.current", "1.0.0+codex.current")
        os.utime(configured, (1, 1))
        os.utime(current, (2, 2))

        with patch.dict(
            os.environ,
            {"PLUGIN_ROOT": str(configured), "PLUGIN_DATA": str(self.data)},
            clear=False,
        ):
            candidates = runtime_bootstrap.candidate_bundles()

        self.assertEqual(candidates[0], ("sibling", current.resolve()))
        self.assertIn(configured.resolve(), [bundle for _, bundle in candidates])

    def test_explicit_current_registry_remains_authoritative(self) -> None:
        configured = self.make_bundle("1.0.0+codex.old", "1.0.0+codex.old")
        current = self.make_bundle("1.0.0+codex.current", "1.0.0+codex.current")
        self.data.mkdir()
        (self.data / "runtime-upgrade.json").write_text(
            json.dumps({
                "current_bundle": str(current),
                "previous_bundle": str(configured),
            }),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"PLUGIN_ROOT": str(configured), "PLUGIN_DATA": str(self.data)},
            clear=False,
        ):
            candidates = runtime_bootstrap.candidate_bundles()

        self.assertEqual(candidates[0], ("current", current.resolve()))
        self.assertIn(configured.resolve(), [bundle for _, bundle in candidates])

    def test_incomplete_newer_sibling_is_ignored(self) -> None:
        configured = self.make_bundle("1.0.0+codex.current", "1.0.0+codex.current")
        incomplete = self.cache / "1.0.0+codex.incomplete"
        incomplete.mkdir()
        os.utime(configured, (1, 1))
        os.utime(incomplete, (2, 2))

        with patch.dict(
            os.environ,
            {"PLUGIN_ROOT": str(configured), "PLUGIN_DATA": str(self.data)},
            clear=False,
        ):
            candidates = runtime_bootstrap.candidate_bundles()

        self.assertEqual(candidates[0][1], configured.resolve())
        self.assertNotIn(incomplete.resolve(), [bundle for _, bundle in candidates])

    def test_bootstrap_executes_dispatcher_from_recent_sibling(self) -> None:
        configured = self.make_bundle("1.0.0+codex.old", "1.0.0+codex.old")
        current = self.make_bundle("1.0.0+codex.current", "1.0.0+codex.current")
        (current / "scripts" / "hook_dispatch.py").write_text(
            """import json, os, sys
event = json.loads(sys.stdin.read())
print(json.dumps({
    "event": event.get("hook_event_name"),
    "root": os.environ.get("PLUGIN_ROOT"),
    "source": os.environ.get("AUTO_DEV_RUNTIME_RESOLVED_FROM"),
    "version": os.environ.get("AUTO_DEV_RUNTIME_VERSION"),
    "recovered": os.environ.get("AUTO_DEV_RUNTIME_RECOVERED"),
}))
""",
            encoding="utf-8",
        )
        os.utime(configured, (1, 1))
        os.utime(current, (2, 2))
        environment = dict(os.environ)
        environment.update({"PLUGIN_ROOT": str(configured), "PLUGIN_DATA": str(self.data)})

        result = subprocess.run(
            [sys.executable, str(BOOTSTRAP)],
            input=json.dumps({"hook_event_name": "SessionStart"}),
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["event"], "SessionStart")
        self.assertEqual(payload["root"], str(current.resolve()))
        self.assertEqual(payload["source"], "sibling")
        self.assertEqual(payload["version"], "1.0.0+codex.current")
        self.assertEqual(payload["recovered"], "1")


if __name__ == "__main__":
    unittest.main()
