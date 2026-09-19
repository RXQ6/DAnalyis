from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.kv import SQLiteKVMemory


class KVMemoryTests(unittest.TestCase):
    def test_set_get_overwrite_delete_list_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "memory.sqlite3"
            store = SQLiteKVMemory(database)
            store.set("user-a", "preferred_metric", "销售额")
            store.set("user-a", "default_aggregation", {"operation": "sum"})
            store.set("user-a", "preferred_metric", "利润")

            self.assertEqual(store.get("user-a", "preferred_metric").value, "利润")
            self.assertEqual(
                [entry.key for entry in store.list("user-a")],
                ["default_aggregation", "preferred_metric"],
            )
            self.assertIsNone(store.get("user-b", "preferred_metric"))
            store.close()

            reopened = SQLiteKVMemory(database)
            self.assertEqual(reopened.get("user-a", "preferred_metric").value, "利润")
            self.assertTrue(reopened.delete("user-a", "preferred_metric"))
            self.assertFalse(reopened.delete("user-a", "preferred_metric"))
            self.assertIsNone(reopened.get("user-a", "preferred_metric"))
            reopened.close()

    def test_same_key_is_deduplicated_and_update_requires_existing_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteKVMemory(Path(directory) / "memory.sqlite3")
            first = store.set("user-a", "default_aggregation", "sum")
            duplicate = store.set("user-a", "default_aggregation", "sum")
            updated = store.update("user-a", "default_aggregation", "average")

            self.assertEqual(first, duplicate)
            self.assertEqual(len(store.list("user-a")), 1)
            self.assertEqual(updated.value, "average")
            with self.assertRaises(KeyError):
                store.update("user-a", "missing", "sum")
            store.close()


if __name__ == "__main__":
    unittest.main()
