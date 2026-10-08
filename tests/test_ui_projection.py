"""Contract checks for the read-only Progress UI projection."""

from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PROGRESS_PAGE = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "progress_page.html"


class UiProjectionContractTest(unittest.TestCase):
    def test_progress_page_defaults_to_dark_with_an_ephemeral_theme_toggle(self) -> None:
        page = PROGRESS_PAGE.read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN" data-theme="dark">', page)
        self.assertIn('html[data-theme="light"]', page)
        self.assertIn('id="theme-toggle"', page)
        self.assertIn('aria-pressed="true"', page)
        self.assertIn('let theme = "dark";', page)
        self.assertIn('function setTheme(next)', page)
        self.assertIn('theme === "dark" ? "light" : "dark"', page)
        self.assertIn('switchToLight', page)
        self.assertIn('switchToDark', page)
        self.assertNotIn("auto-dev-progress-theme", page)

    def test_progress_page_distinguishes_recorded_baselines_and_renders_product_review(self) -> None:
        page = PROGRESS_PAGE.read_text(encoding="utf-8")
        self.assertIn('id="product-review-summary"', page)
        self.assertIn("product_receipt", page)
        self.assertIn("proofRecorded", page)
        self.assertIn("performanceDetails", page)

    def test_progress_page_renders_the_compact_performance_fields(self) -> None:
        page = PROGRESS_PAGE.read_text(encoding="utf-8")
        for field in (
            "sample_count", "observed_value", "target_value", "improvement_pct",
            "noise_tolerance_pct", "change_exceeds_noise",
        ):
            self.assertIn(field, page)

    def test_progress_page_links_git_archive_hashes_to_their_milestone(self) -> None:
        page = PROGRESS_PAGE.read_text(encoding="utf-8")
        for contract in (
            "workspace_checkpoint_nodes",
            "renderMilestoneCheckpointChain",
            "milestone-checkpoint-chain",
            "milestoneArchiveBefore",
            "milestoneArchiveAfter",
            "short_hash",
        ):
            self.assertIn(contract, page)

    def test_progress_page_projects_control_plane_upgrade_status_without_actions(self) -> None:
        page = PROGRESS_PAGE.read_text(encoding="utf-8")
        for status in (
            "upgrade_available", "reverification_required", "manual_decision_required",
            "blocked", "newer_than_cli",
        ):
            self.assertIn(status, page)
        self.assertIn("hierarchy.control_plane_upgrade", page)
        self.assertNotIn("legacy-upgrade apply", page)

    def test_progress_page_marks_completed_nodes_with_stale_proofs_for_revalidation(self) -> None:
        page = PROGRESS_PAGE.read_text(encoding="utf-8")
        for contract in (
            "nodeReverificationIssue",
            'issue.kind === "stale_proof"',
            "proofRevalidationRequired",
            "executionRevalidationProgress",
            'reverification_required: "已完成，需复验"',
            '["done", "completed", "reverification_required"]',
        ):
            self.assertIn(contract, page)

    def test_progress_page_projects_the_latest_focus_transition(self) -> None:
        page = PROGRESS_PAGE.read_text(encoding="utf-8")
        self.assertIn("last_transition", page)
        self.assertIn("transitionStatus", page)


if __name__ == "__main__":
    unittest.main()
