from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.vector import SQLiteVectorMemory


class TwoDimensionEmbedder:
    model_id = "test-two-dimension-v1"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if "趋势" in text else [0.0, 1.0]


class VectorMemoryTests(unittest.TestCase):
    def test_add_search_top_k_delete_and_scope_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "memory.sqlite3"
            store = SQLiteVectorMemory(database)
            sales = store.add(
                "user-a",
                "销售趋势分析应先确认日期字段，再按月聚合销售额。",
                kind="sop",
            )
            store.add(
                "user-a",
                "异常检测前应检查数值字段的缺失值。",
                kind="analysis_experience",
            )
            store.add("user-b", "销售趋势的私人规则", kind="sop")

            matches = store.search("user-a", "如何分析销售趋势和日期", top_k=1)

            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].entry.id, sales.id)
            self.assertGreater(matches[0].score, 0)
            self.assertNotIn("私人规则", matches[0].entry.content)
            self.assertTrue(store.delete("user-a", sales.id))
            self.assertFalse(store.delete("user-a", sales.id))
            self.assertEqual(len(store.list("user-a")), 1)
            store.close()

            reopened = SQLiteVectorMemory(database)
            self.assertEqual(len(reopened.list("user-a")), 1)
            reopened.close()

    def test_default_embedder_recalls_domain_paraphrases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteVectorMemory(Path(directory) / "memory.sqlite3")
            expected = store.add(
                "user-a",
                "异常检测前应检查数值字段的缺失值。",
                kind="analysis_experience",
            )
            store.add(
                "user-a",
                "销售趋势需要使用日期字段按月汇总。",
                kind="sop",
            )

            matches = store.search(
                "user-a", "排查离群点之前先确认空值", top_k=1, min_score=0.08
            )

            self.assertEqual(matches[0].entry.id, expected.id)
            self.assertGreater(matches[0].score, 0.08)
            store.close()

    def test_duplicate_add_updates_existing_entry_and_update_reembeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteVectorMemory(Path(directory) / "memory.sqlite3")
            first = store.add(
                "user-a",
                "趋势分析先检查日期字段。",
                kind="sop",
                metadata={"version": 1},
            )
            duplicate = store.add(
                "user-a",
                "  趋势分析先检查日期字段。  ",
                kind="sop",
                metadata={"version": 2},
            )

            self.assertEqual(duplicate.id, first.id)
            self.assertEqual(len(store.list("user-a")), 1)
            self.assertEqual(duplicate.metadata, {"version": 2})

            updated = store.update(
                "user-a",
                first.id,
                content="离群点排查先检查空值。",
                metadata={"version": 3},
            )
            matches = store.search("user-a", "异常检测和缺失值", top_k=1)

            self.assertEqual(updated.id, first.id)
            self.assertEqual(updated.metadata, {"version": 3})
            self.assertEqual(matches[0].entry.id, first.id)
            with self.assertRaises(KeyError):
                store.update("user-a", "missing-id", content="不存在")
            store.close()

    def test_reopening_with_replacement_embedder_reindexes_existing_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "memory.sqlite3"
            original = SQLiteVectorMemory(database)
            entry = original.add("user-a", "销售趋势分析规则", kind="sop")
            original.close()

            replacement = SQLiteVectorMemory(database, embedder=TwoDimensionEmbedder())
            matches = replacement.search("user-a", "趋势", top_k=1)

            self.assertEqual(matches[0].entry.id, entry.id)
            self.assertEqual(matches[0].score, 1.0)
            replacement.close()


if __name__ == "__main__":
    unittest.main()
