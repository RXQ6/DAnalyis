from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from datasets import DatasetRegistry, DatasetRegistryError
from eval_agent import create_average_xlsx


class DatasetRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.registry = DatasetRegistry(self.root / "derived")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_registers_unique_ids_and_safe_summaries(self) -> None:
        first = self.write(
            "sales.csv",
            "日期,地区,销售额\n2026-01-02,华东,20\n2026-01-01,华南,10\n",
        )
        second_dir = self.root / "other"
        second_dir.mkdir()
        second = second_dir / "sales.csv"
        second.write_text("日期,地区,销售额\n2026-02-01,华北,30\n", encoding="utf-8")

        first_summary = self.registry.register(first)
        second_summary = self.registry.register(second)

        self.assertNotEqual(first_summary["datasetId"], second_summary["datasetId"])
        self.assertEqual(first_summary["filename"], "sales.csv")
        self.assertEqual(first_summary["rowCount"], 2)
        self.assertEqual(
            first_summary["dateRanges"],
            [{"column": "日期", "minimum": "2026-01-01", "maximum": "2026-01-02"}],
        )
        public_text = json.dumps(self.registry.public_context(), ensure_ascii=False)
        self.assertNotIn(str(first), public_text)
        self.assertNotIn("华东", public_text)
        self.assertNotIn("华南", public_text)

    def test_registers_xlsx_with_existing_deterministic_loader(self) -> None:
        workbook = self.root / "average.xlsx"
        create_average_xlsx(workbook)

        summary = self.registry.register(workbook)

        self.assertEqual(summary["format"], "xlsx")
        self.assertEqual(summary["rowCount"], 3)
        self.assertEqual(
            [(column["name"], column["type"]) for column in summary["columns"]],
            [("产品", "text"), ("销售额", "number")],
        )

    def test_unknown_and_duplicate_dataset_ids_are_rejected(self) -> None:
        data = self.write("one.csv", "id,value\n1,10\n")
        self.registry.register(data, dataset_id="ds_fixed")
        with self.assertRaises(DatasetRegistryError) as duplicate:
            self.registry.register(data, dataset_id="ds_fixed")
        self.assertEqual(duplicate.exception.code, "duplicate_dataset_id")
        with self.assertRaises(DatasetRegistryError) as missing:
            self.registry.resolve("ds_missing")
        self.assertEqual(missing.exception.code, "dataset_not_found")

    def test_derived_dataset_exposes_lineage_but_not_path(self) -> None:
        data = self.write("derived.csv", "id,value\n1,10\n")
        summary = self.registry.register_derived(
            data,
            filename="merged.csv",
            lineage={"operation": "merge", "leftDatasetId": "ds_left"},
        )

        self.assertTrue(summary["derived"])
        self.assertEqual(summary["lineage"]["operation"], "merge")
        self.assertNotIn("path", summary)


if __name__ == "__main__":
    unittest.main()
