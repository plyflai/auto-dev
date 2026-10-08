"""Unit coverage for the disposable cross-session writer lease."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPTS = PLUGIN_ROOT / "scripts"
if str(HOOK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOOK_SCRIPTS))

import hook_session_state  # noqa: E402


class SessionWriterLeaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-writer-lease-")
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.data = Path(self.temporary.name) / "plugin-data"
        self.environment = patch.dict(
            hook_session_state.os.environ,
            {"PLUGIN_DATA": str(self.data)},
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    @staticmethod
    def event(session_id: str) -> dict[str, str]:
        return {"session_id": session_id}

    def claim(
        self,
        session_id: str,
        *,
        now: int,
        mutation: bool = True,
        branch_key: str = "main",
    ) -> dict[str, object]:
        return hook_session_state.claim_writer_lease(
            self.root,
            self.event(session_id),
            branch_key=branch_key,
            task_id="TASK-1",
            state_revision=3,
            mutation=mutation,
            now=now,
        )

    def test_first_claim_and_same_owner_renewal(self) -> None:
        acquired = self.claim("session-a", now=100)
        self.assertEqual(acquired["status"], "acquired")
        lease_id = acquired["lease"]["lease_id"]  # type: ignore[index]

        renewed = self.claim("session-a", now=101)
        self.assertEqual(renewed["status"], "owned")
        self.assertEqual(renewed["lease"]["lease_id"], lease_id)  # type: ignore[index]
        self.assertEqual(renewed["lease"]["owner_session"], hook_session_state.session_fingerprint("session-a"))  # type: ignore[index]

    def test_new_session_takes_over_and_old_owner_is_observer(self) -> None:
        self.claim("session-a", now=100, mutation=False)
        takeover = self.claim("session-b", now=101)
        self.assertEqual(takeover["status"], "taken_over")

        old_status = hook_session_state.writer_lease_status(
            self.root,
            self.event("session-a"),
            branch_key="main",
            now=102,
        )
        self.assertEqual(old_status["status"], "observer")
        old_claim = self.claim("session-a", now=102)
        self.assertEqual(old_claim["status"], "observer")

    def test_inflight_mutation_temporarily_blocks_handoff(self) -> None:
        self.claim("session-a", now=100, mutation=True)
        conflict = self.claim("session-b", now=101)
        self.assertEqual(conflict["status"], "conflict")

        takeover = self.claim(
            "session-b",
            now=100 + hook_session_state.WRITER_LEASE_INFLIGHT_SECONDS + 1,
        )
        self.assertEqual(takeover["status"], "taken_over")

    def test_expired_owner_is_preserved_as_superseded(self) -> None:
        self.claim("session-a", now=100, mutation=False)
        takeover = self.claim(
            "session-b",
            now=100 + hook_session_state.WRITER_LEASE_STALE_SECONDS + 1,
        )
        self.assertEqual(takeover["status"], "acquired")

        old_claim = self.claim("session-a", now=102 + hook_session_state.WRITER_LEASE_STALE_SECONDS)
        self.assertEqual(old_claim["status"], "observer")

    def test_branch_contexts_have_independent_leases(self) -> None:
        main = self.claim("session-a", now=100, branch_key="main")
        feature = self.claim("session-b", now=100, branch_key="feature")
        self.assertEqual(main["status"], "acquired")
        self.assertEqual(feature["status"], "acquired")


if __name__ == "__main__":
    unittest.main()
