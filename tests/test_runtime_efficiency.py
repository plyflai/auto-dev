"""Behavior-preserving efficiency contracts for status and progress runtime paths."""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts"
HOOK_SCRIPTS = PLUGIN_ROOT / "scripts"
for path in (SCRIPTS, HOOK_SCRIPTS):
    if str(path) not in os.sys.path:
        os.sys.path.insert(0, str(path))

import runctl  # noqa: E402
import auto_dev  # noqa: E402
from auto_dev_internal.foundation.evaluation import evaluation_scope  # noqa: E402
from auto_dev_internal.foundation.progress import (  # noqa: E402
    ProgressSnapshotStore,
    monitor_ready_file,
)


class RuntimeEfficiencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-efficiency-")
        self.root = pathlib.Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.runtime_cache = self.root / "runtime-cache"
        self.environment = patch.dict(
            os.environ,
            {"AUTO_DEV_RUNTIME_CACHE_ROOT": str(self.runtime_cache)},
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def test_scope_manifest_hashes_each_file_once_and_reuses_persistent_digests(self) -> None:
        scope = self.repo / "scope"
        scope.mkdir()
        (scope / "one.txt").write_text("one\n", encoding="utf-8")
        (scope / "two.txt").write_text("two\n", encoding="utf-8")

        with evaluation_scope(self.repo) as evaluation:
            first = runctl.local_scope_manifest(self.repo, ["scope"])
            second = runctl.local_scope_manifest(self.repo, ["scope"])
            self.assertEqual(first, second)
            self.assertEqual(evaluation.digest_reads, 2)

        with evaluation_scope(self.repo) as evaluation:
            third = runctl.local_scope_manifest(self.repo, ["scope"])
            self.assertEqual(first, third)
            self.assertEqual(evaluation.digest_reads, 0)
            self.assertEqual(evaluation.digest_hits, 2)

        (scope / "two.txt").write_text("changed\n", encoding="utf-8")
        with evaluation_scope(self.repo) as evaluation:
            changed = runctl.local_scope_manifest(self.repo, ["scope"])
            self.assertNotEqual(first["scope/two.txt"], changed["scope/two.txt"])
            self.assertEqual(evaluation.digest_reads, 1)
            self.assertEqual(evaluation.digest_hits, 1)

    def test_progress_snapshot_coalesces_concurrent_clients(self) -> None:
        lock = threading.Lock()
        calls = {"fingerprint": 0, "payload": 0}

        def fingerprint(_: str | None) -> str:
            with lock:
                calls["fingerprint"] += 1
            time.sleep(0.02)
            return "revision-1"

        def payload(_: str | None, __: str | None) -> dict[str, object]:
            with lock:
                calls["payload"] += 1
            time.sleep(0.02)
            return {"id": "TASK-1", "state_revision": 1}

        store = ProgressSnapshotStore(
            fingerprint=fingerprint,
            payload=payload,
            identity=lambda: {"task_id": None, "state_revision": 0},
        )
        results = []

        def read() -> None:
            results.append(store.snapshot(session_key=None, project_context_id=None))

        threads = [threading.Thread(target=read) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 20)
        self.assertEqual(calls, {"fingerprint": 1, "payload": 1})
        self.assertEqual({result.version for result in results}, {1})

    def test_evaluation_scope_does_not_hold_an_exclusive_lock_while_reading(self) -> None:
        entered = threading.Event()

        def follower() -> None:
            with evaluation_scope(self.repo):
                entered.set()

        with evaluation_scope(self.repo):
            thread = threading.Thread(target=follower)
            thread.start()
            self.assertTrue(entered.wait(timeout=1))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_evaluation_scope_merges_concurrent_fingerprint_updates(self) -> None:
        one = self.repo / "one.txt"
        two = self.repo / "two.txt"
        one.write_text("one\n", encoding="utf-8")
        two.write_text("two\n", encoding="utf-8")
        ready = threading.Barrier(2)
        release = threading.Barrier(2)

        def digest(path: pathlib.Path) -> None:
            with evaluation_scope(self.repo) as evaluation:
                evaluation.file_digest(path)
                ready.wait(timeout=1)
                release.wait(timeout=1)

        first = threading.Thread(target=digest, args=(one,))
        second = threading.Thread(target=digest, args=(two,))
        first.start()
        second.start()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())

        with evaluation_scope(self.repo) as evaluation:
            self.assertTrue(evaluation.file_digest(one))
            self.assertTrue(evaluation.file_digest(two))
            self.assertEqual(evaluation.digest_reads, 0)
            self.assertEqual(evaluation.digest_hits, 2)

    def test_health_identity_does_not_build_progress_payload(self) -> None:
        store = ProgressSnapshotStore(
            fingerprint=lambda _: "revision-1",
            payload=lambda _session, _context: self.fail("health must not build payload"),
            identity=lambda: {"task_id": "TASK-1", "state_revision": 7},
        )
        self.assertEqual(
            store.health_identity(),
            {"task_id": "TASK-1", "state_revision": 7},
        )

    def test_progress_snapshot_periodically_revalidates_unchanged_fingerprint(self) -> None:
        calls = {"payload": 0}

        def payload(_: str | None, __: str | None) -> dict[str, object]:
            calls["payload"] += 1
            return {"id": "TASK-1", "state_revision": calls["payload"]}

        store = ProgressSnapshotStore(
            fingerprint=lambda _: "stable",
            payload=payload,
            identity=lambda: {},
            check_interval=0.001,
            refresh_interval=0.01,
        )
        first = store.snapshot(session_key=None, project_context_id=None)
        time.sleep(0.02)
        second = store.snapshot(session_key=None, project_context_id=None)
        self.assertEqual(calls["payload"], 2)
        self.assertGreater(second.version, first.version)

    def test_ready_file_generation_fences_superseded_server(self) -> None:
        ready = self.root / "ready.json"
        ready.write_text(json.dumps({"generation": "old"}), encoding="utf-8")

        class Server:
            stopped = threading.Event()

            def shutdown(self) -> None:
                self.stopped.set()

        server = Server()
        monitor_ready_file(server, ready, "old", interval=0.01)
        ready.write_text(json.dumps({"generation": "new"}), encoding="utf-8")
        self.assertTrue(server.stopped.wait(timeout=1))

    def test_auto_dev_front_door_execs_instead_of_waiting_on_a_wrapper(self) -> None:
        with patch.object(auto_dev.os, "execvpe", side_effect=RuntimeError("exec-called")) as execute:
            with self.assertRaisesRegex(RuntimeError, "exec-called"):
                auto_dev.run_child("runctl.py", ["status", "--repo-root", str(self.repo)])
        argv = execute.call_args.args[1]
        self.assertEqual(pathlib.Path(argv[1]).name, "runctl.py")
        self.assertEqual(argv[2], "status")


if __name__ == "__main__":
    unittest.main()
