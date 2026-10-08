"""Static contract coverage for the natural-language Auto Dev upgrade route."""

from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL = PLUGIN_ROOT / "skills" / "auto-dev" / "SKILL.md"
CONTINUITY = PLUGIN_ROOT / "skills" / "auto-dev" / "references" / "continuity" / "README.md"
LEGACY = CONTINUITY.parent / "legacy-upgrade.md"


class LegacyUpgradeNaturalLanguageRouteTest(unittest.TestCase):
    def test_update_request_runs_inspection_without_exposing_cli_to_the_user(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        continuity = CONTINUITY.read_text(encoding="utf-8")
        legacy = LEGACY.read_text(encoding="utf-8")
        for document in (skill, continuity, legacy):
            self.assertIn("更新新版 Auto Dev", document)
            self.assertIn("legacy-upgrade", document)
        self.assertIn("Agent 自己先运行零写入的 Legacy Upgrade inspect", skill)
        self.assertIn("用户只决定是否执行真实升级", continuity)
        self.assertIn("不要求用户提供 CLI、revision、step 或 fingerprint", legacy)
        self.assertIn("自动带入完整 apply contract", legacy)


if __name__ == "__main__":
    unittest.main()
