from __future__ import annotations

import unittest

from minem.case_brief import CASE_BRIEF_SCHEMA_VERSION, DEFAULT_MAX_CASES, build_case_brief
from minem.cli.parser import build_parser


class CaseBriefTests(unittest.TestCase):
    def test_default_brief_selects_at_most_three_evidence_first_cases(self) -> None:
        brief = build_case_brief("https://example.com/case-doc")

        self.assertEqual(brief["schemaVersion"], CASE_BRIEF_SCHEMA_VERSION)
        self.assertEqual(brief["requestedMaxCases"], DEFAULT_MAX_CASES)
        self.assertTrue(brief["selectionPolicy"]["doNotSplitByHeading"])
        self.assertTrue(brief["selectionPolicy"]["doNotPadToLimit"])
        self.assertTrue(brief["mediaPolicy"]["directEvidenceOnly"])
        self.assertTrue(brief["mediaPolicy"]["includeAllStrongCustomerEvidence"])
        self.assertIn("click-to-play", brief["mediaPolicy"]["videoInteraction"])
        self.assertTrue(brief["pagePolicy"]["viewerOwnsSourceCopyToast"])
        self.assertTrue(brief["pagePolicy"]["adaptivePagesPerCase"])
        self.assertTrue(brief["pagePolicy"]["videoPlaybackRequired"])
        self.assertEqual(brief["defaults"]["pagesPerCase"]["maximum"], 4)
        self.assertEqual(brief["outputSchema"]["properties"]["cases"]["maxItems"], 3)
        self.assertIn("最多发布：3 个案例", brief["prompt"])
        self.assertIn("禁止把每个标题机械地变成案例", brief["prompt"])
        self.assertIn("跨案例素材不得混用", brief["prompt"])
        self.assertIn("自适应生成 1–4 张", brief["prompt"])
        self.assertIn("视频必须以真实可播放资源入库", brief["prompt"])
        self.assertIn("不要为了压缩成一页只保留一张图片", brief["prompt"])

        page_plan = brief["outputSchema"]["properties"]["cases"]["items"]["properties"]["pagePlan"]
        self.assertEqual(page_plan["properties"]["pages"]["maxItems"], 4)

    def test_brief_keeps_explicit_audience_focus_and_limit(self) -> None:
        brief = build_case_brief(
            "/tmp/source.md",
            audience="零售行业客户",
            focus="突出效率和收入增长",
            max_cases=2,
        )

        self.assertEqual(brief["audience"], "零售行业客户")
        self.assertEqual(brief["focus"], "突出效率和收入增长")
        self.assertEqual(brief["requestedMaxCases"], 2)
        self.assertEqual(brief["outputSchema"]["properties"]["cases"]["maxItems"], 2)
        self.assertIn("面向零售行业客户", brief["prompt"])

    def test_brief_rejects_empty_source_and_excessive_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "source document"):
            build_case_brief("")
        with self.assertRaisesRegex(ValueError, "between 1 and 12"):
            build_case_brief("source", max_cases=13)

    def test_cli_parser_exposes_case_brief(self) -> None:
        args = build_parser().parse_args(
            ["case", "brief", "https://example.com/doc", "--audience", "CEO", "--max-cases", "2"]
        )

        self.assertEqual(args.command_name, "case.brief")
        self.assertEqual(args.source, "https://example.com/doc")
        self.assertEqual(args.audience, "CEO")
        self.assertEqual(args.max_cases, 2)


if __name__ == "__main__":
    unittest.main()
