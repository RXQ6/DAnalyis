"""Trusted task-scoped mapping from opaque dataset ids to local files."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from .bridge import MultiFileBridge, MultiFileBridgeError


MAX_DATASETS = 20


class DatasetRegistryError(RuntimeError):
    def __init__(
        self, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class DatasetRegistry:
    """Own dataset paths and expose summaries without raw rows or trusted paths."""

    def __init__(self, work_dir: str | Path, *, bridge: MultiFileBridge | None = None) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.bridge = bridge or MultiFileBridge()
        self._datasets: dict[str, dict[str, Any]] = {}

    def register(
        self,
        file_path: str | Path,
        *,
        dataset_id: str | None = None,
        filename: str | None = None,
        lineage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if len(self._datasets) >= MAX_DATASETS:
            raise DatasetRegistryError(
                "dataset_limit", f"dataset count cannot exceed {MAX_DATASETS}"
            )
        active_id = dataset_id or f"ds_{uuid.uuid4().hex[:12]}"
        if not re.fullmatch(r"ds_[A-Za-z0-9_-]{1,64}", active_id):
            raise DatasetRegistryError("invalid_dataset_id", "dataset id is invalid")
        if active_id in self._datasets:
            raise DatasetRegistryError(
                "duplicate_dataset_id", f"dataset id already exists: {active_id}"
            )
        path = Path(file_path).resolve()
        try:
            summary = self.bridge.summarize(str(path))
        except MultiFileBridgeError as error:
            raise DatasetRegistryError(error.code, str(error), error.details) from error
        public = {
            "datasetId": active_id,
            "filename": filename or summary["filename"],
            "format": summary["format"],
            "sizeBytes": summary["sizeBytes"],
            "rowCount": summary["rowCount"],
            "columnCount": summary["columnCount"],
            "columns": summary["columns"],
            "dateRanges": summary["dateRanges"],
            "derived": lineage is not None,
            "lineage": lineage,
        }
        self._datasets[active_id] = {
            "path": str(path),
            "fingerprint": summary["fingerprint"],
            "public": public,
        }
        return _copy(public)

    def register_derived(
        self, file_path: str | Path, *, filename: str, lineage: dict[str, Any]
    ) -> dict[str, Any]:
        return self.register(file_path, filename=filename, lineage=lineage)

    def resolve(self, dataset_id: str) -> str:
        return self._entry(dataset_id)["path"]

    def fingerprint(self, dataset_id: str) -> str:
        return self._entry(dataset_id)["fingerprint"]

    def summary(self, dataset_id: str) -> dict[str, Any]:
        return _copy(self._entry(dataset_id)["public"])

    def list_summaries(
        self, dataset_ids: list[str] | tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        if dataset_ids is None:
            entries = self._datasets.values()
        else:
            entries = [self._entry(dataset_id) for dataset_id in dataset_ids]
        return [_copy(item["public"]) for item in entries]

    def public_context(
        self, dataset_ids: list[str] | tuple[str, ...] | None = None
    ) -> dict[str, Any]:
        summaries = self.list_summaries(dataset_ids)
        return {"datasetCount": len(summaries), "datasets": summaries}

    def contains(self, dataset_id: str) -> bool:
        return dataset_id in self._datasets

    def output_path(self, prefix: str = "merged") -> Path:
        safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", prefix).strip("_") or "merged"
        return self.work_dir / f"{safe_prefix}_{uuid.uuid4().hex[:12]}.csv"

    def __len__(self) -> int:
        return len(self._datasets)

    def _entry(self, dataset_id: str) -> dict[str, Any]:
        try:
            return self._datasets[dataset_id]
        except KeyError as error:
            raise DatasetRegistryError(
                "dataset_not_found", f"dataset id is not registered: {dataset_id}"
            ) from error


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value
