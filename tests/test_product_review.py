"""Unit coverage for the product-facing review_ready contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "auto-dev" / "scripts"))

from runctl import normalize_product_review, product_review_receipt  # noqa: E402


class ProductReviewTest(unittest.TestCase):
    def test_release_evidence_is_rendered_inside_the_product_receipt(self) -> None:
        review = normalize_product_review({
            "completed": "完成预发发布",
            "purpose": "交付产品验收",
            "next_step": "产品开始验收",
            "user_impact": "新版本已在预发可用",
            "test": {"status": "not_applicable", "reason": "发布烟测已完成"},
        })
        receipt = product_review_receipt(review, release_evidence=[{
            "result": "succeeded",
            "environment": "staging",
            "version": "v2.4.1",
            "health": {"status": "passed", "summary": "服务及依赖健康"},
            "user_flow": {"status": "passed", "summary": "登录和下单烟测通过"},
            "rollback": {
                "status": "ready",
                "trigger": "健康检查或下单烟测失败",
                "target": "v2.4.0",
            },
            "unverified": ["真实支付"],
            "next_step": "产品可以开始预发验收",
        }])
        self.assertTrue(receipt.startswith("💡 Auto Dev 产品验收回执"))
        self.assertIn("目标环境：staging", receipt)
        self.assertIn("部署版本：v2.4.1", receipt)
        self.assertIn("健康检查：通过。服务及依赖健康", receipt)
        self.assertIn("关键用户流程：通过。登录和下单烟测通过", receipt)
        self.assertIn("回滚准备：就绪；触发：健康检查或下单烟测失败；目标：v2.4.0", receipt)
        self.assertIn("尚未验证：真实支付", receipt)
        self.assertIn("产品下一步：产品可以开始预发验收", receipt)

    def test_e2e_evidence_is_rendered_for_a_product_manager(self) -> None:
        review = normalize_product_review({
            "completed": "完成下单流程",
            "purpose": "验证用户可以完成下单",
            "next_step": "产品开始验收",
            "user_impact": "用户可以提交订单",
            "test": {"status": "not_applicable", "reason": "E2E 已完成自动验证"},
        })
        receipt = product_review_receipt(review, [{
            "result": "passed",
            "user_flow": "普通用户提交订单",
            "environment": "预发环境",
            "checks": {
                "page": "确认页正常展示",
                "data_interaction": "提交请求成功",
                "system_result": "订单已正确生成",
            },
            "unverified": ["真实支付"],
            "next_step": "使用测试账号验收下单",
        }])
        self.assertIn("验证结果：通过", receipt)
        self.assertIn("用户流程：普通用户提交订单", receipt)
        self.assertIn("测试环境：预发环境", receipt)
        self.assertIn("页面表现：确认页正常展示", receipt)
        self.assertIn("数据交互：提交请求成功", receipt)
        self.assertIn("系统结果：订单已正确生成", receipt)
        self.assertIn("尚未验证：真实支付", receipt)
        self.assertIn("产品下一步：使用测试账号验收下单", receipt)

    def test_blocked_product_review_is_concrete_and_user_facing(self) -> None:
        review = normalize_product_review({
            "completed": "完成接口错误提示",
            "purpose": "让用户知道提交失败的原因",
            "next_step": "等待测试环境恢复后进行页面验收",
            "user_impact": "提交失败时会看到明确原因",
            "test": {
                "status": "blocked",
                "reason": "测试环境接口尚未部署",
            },
        })
        receipt = product_review_receipt(review)
        self.assertEqual(review["schema_version"], 1)
        self.assertIn("💡 Auto Dev 产品验收回执", receipt)
        self.assertIn("暂不可测", receipt)
        self.assertIn("测试环境接口尚未部署", receipt)

    def test_not_applicable_requires_a_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "product review test reason"):
            normalize_product_review({
                "completed": "完成内部状态迁移",
                "purpose": "统一控制面状态",
                "next_step": "产品继续验收现有页面",
                "user_impact": "用户侧暂无直接变化",
                "test": {"status": "not_applicable"},
            })

    def test_ready_requires_an_entry_steps_and_expected_result(self) -> None:
        with self.assertRaisesRegex(ValueError, "product review test entry"):
            normalize_product_review({
                "completed": "完成设置页调整",
                "purpose": "减少设置误操作",
                "next_step": "产品验证设置流程",
                "user_impact": "用户可以更快完成设置",
                "test": {
                    "status": "ready",
                    "role": "普通用户",
                    "steps": ["打开设置"],
                    "expected": "页面正常展示",
                },
            })


if __name__ == "__main__":
    unittest.main()
