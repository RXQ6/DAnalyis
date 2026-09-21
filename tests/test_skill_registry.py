from __future__ import annotations

import unittest

from skill_runtime import SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def test_discovery_uses_metadata_without_loading_full_skill(self) -> None:
        registry = SkillRegistry()

        match = registry.discover(
            {"query": "请做数据诊断并分析异常原因", "active_dataset_ids": ["ds_1"]}
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.name, "data-diagnosis")
        self.assertEqual(registry.loaded_skill_names, ())

    def test_generic_analysis_does_not_match_or_load_skill(self) -> None:
        registry = SkillRegistry()

        match = registry.discover(
            {"query": "统计销售额总和", "active_dataset_ids": ["ds_1"]}
        )

        self.assertIsNone(match)
        self.assertEqual(registry.loaded_skill_names, ())

    def test_business_diagnosis_phrasings_match(self) -> None:
        queries = (
            "为什么最近销量下降",
            "最近销售额为什么一直降",
            "哪个地区导致指标下降",
            "帮我分析异常波动原因",
        )

        for query in queries:
            with self.subTest(query=query):
                registry = SkillRegistry()
                match = registry.discover(
                    {"query": query, "active_dataset_ids": ["ds_1"]}
                )
                self.assertIsNotNone(match)
                self.assertEqual(match.name, "data-diagnosis")
                self.assertEqual(registry.loaded_skill_names, ())

    def test_non_diagnostic_requests_do_not_match(self) -> None:
        queries = (
            "你好，最近怎么样",
            "计算 12 * 8",
            "统计销售额总和",
            "请解释什么是根因分析",
            "异常原因这个字段应该改名吗",
        )

        for query in queries:
            with self.subTest(query=query):
                registry = SkillRegistry()
                match = registry.discover(
                    {"query": query, "active_dataset_ids": ["ds_1"]}
                )
                self.assertIsNone(match)
                self.assertEqual(registry.loaded_skill_names, ())

    def test_diagnosis_requires_a_dataset(self) -> None:
        registry = SkillRegistry()

        self.assertIsNone(registry.discover({"query": "请做数据诊断"}))
        self.assertEqual(registry.loaded_skill_names, ())

    def test_load_returns_complete_definition_after_match(self) -> None:
        registry = SkillRegistry()
        match = registry.discover(
            {"query": "查一下异常原因", "dataset_paths": ["sales.csv"]}
        )

        definition = registry.load(match.name)

        self.assertEqual(definition.name, "data-diagnosis")
        self.assertEqual(definition.version, "1.0.0")
        self.assertIn("inspect_data", definition.allowed_tools)
        self.assertNotIn("delegate_data_check", definition.allowed_tools)
        self.assertTrue(definition.workflow)
        self.assertTrue(definition.boundaries)
        self.assertIn("# data-diagnosis", definition.instructions)
        self.assertEqual(registry.loaded_skill_names, ("data-diagnosis",))


if __name__ == "__main__":
    unittest.main()
