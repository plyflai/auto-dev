from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"


@unittest.skipUnless(shutil.which("codegraph"), "real CodeGraph binary is unavailable")
class CodeGraphLiveE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-codegraph-live-")
        self.repo = Path(self.temporary.name).resolve()
        files = {
            "src/pricing.py": """def calculate_total(value: int) -> int:
    return value * 2
""",
            "src/reporting.py": """from src.pricing import calculate_total


def summarize_price(value: int) -> str:
    return str(calculate_total(value))
""",
            "src/presenter.py": """from src.reporting import summarize_price


def render_price(value: int) -> str:
    return f"price={summarize_price(value)}"
""",
            "src/endpoint.py": """from src.presenter import render_price


def price_endpoint(value: int) -> dict[str, str]:
    return {"body": render_price(value)}
""",
            "tests/test_reporting.py": """from src.reporting import summarize_price


def test_summarize_price_uses_pricing() -> None:
    assert summarize_price(3) == "6"
""",
            "tests/test_endpoint.py": """from src.endpoint import price_endpoint


def test_price_endpoint() -> None:
    assert price_endpoint(3) == {"body": "price=6"}
""",
        }
        for relative, content in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (self.repo / "src" / "__init__.py").write_text("", encoding="utf-8")
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        subprocess.run(
            ["git", "add", "."], cwd=self.repo, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        subprocess.run(
            ["git", "-c", "user.name=Auto Dev Test", "-c", "user.email=auto-dev@example.invalid",
             "commit", "-qm", "fixture"],
            cwd=self.repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        completed = subprocess.run(
            ["codegraph", "init", "."], cwd=self.repo, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if completed.returncode != 0:
            self.fail(f"codegraph init failed:\n{completed.stdout}\n{completed.stderr}")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def inspect(self, *arguments: str, check: bool = True) -> dict[str, object]:
        completed = subprocess.run(
            ["python3", str(CLI), "impact", "inspect", "--repo-root", str(self.repo), *arguments],
            cwd=self.repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if not check:
            return {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        if completed.returncode != 0:
            self.fail(f"impact inspect failed:\n{completed.stdout}\n{completed.stderr}")
        return json.loads(completed.stdout)

    def test_live_binary_reports_deep_python_impact_and_fails_closed_when_stale(self) -> None:
        inspected = self.inspect("--symbol", "calculate_total", "--file", "src/pricing.py")

        self.assertEqual(inspected["coverage_status"], "complete")
        self.assertEqual(inspected["test_discovery"]["source"], "inferred")
        self.assertEqual(inspected["test_discovery"]["status"], "verified")
        self.assertIn("tests/test_endpoint.py", inspected["affected_tests"])
        self.assertIn("tests/test_reporting.py", inspected["affected_tests"])
        self.assertIn("price_endpoint", {
            item["name"] for item in inspected["affected_symbols"]
        })
        symbol_result = inspected["codegraph"]["symbol_results"][0]
        self.assertTrue(symbol_result["stabilized"])
        self.assertGreaterEqual(max(symbol_result["depths_checked"]), 4)

        file_only = self.inspect("--file", "src/pricing.py")
        self.assertTrue(file_only["impact_signal"])
        self.assertEqual(file_only["coverage_status"], "partial")
        self.assertTrue(file_only["needs_uncertainty"])
        self.assertIn("file_dependents_not_enumerated", file_only["coverage_reasons"])

        (self.repo / "src" / "pending.py").write_text(
            "from src.pricing import calculate_total\n\nvalue = calculate_total(5)\n",
            encoding="utf-8",
        )
        stale = self.inspect("--symbol", "calculate_total", check=False)
        self.assertEqual(stale["returncode"], 2)
        self.assertIn("CodeGraph index is not up to date", stale["stderr"])


if __name__ == "__main__":
    unittest.main()
