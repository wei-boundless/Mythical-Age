from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from modality_index import ModalityArtifactStore
from .catalog import StructuredDataCatalog


class StructuredDataArtifactBuilder:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.store = ModalityArtifactStore(self.root_dir)

    def save_profile(self, relative_source: str, df: pd.DataFrame) -> dict[str, Any]:
        profile = self.build_profile(df)
        payload = {"source": relative_source, **profile}
        self.store.save_json("table", relative_source, "profile", payload)
        return payload

    def build_profile(self, df: pd.DataFrame) -> dict[str, Any]:
        numeric_columns: list[str] = []
        datetime_columns: list[str] = []
        categorical_columns: list[str] = []
        for column in df.columns:
            series = df[column]
            if pd.api.types.is_numeric_dtype(series):
                numeric_columns.append(column)
            elif str(series.dtype).startswith("datetime"):
                datetime_columns.append(column)
            else:
                categorical_columns.append(column)

        column_stats: dict[str, dict[str, Any]] = {}
        for column in df.columns:
            series = df[column]
            non_null = int(series.notna().sum())
            unique = int(series.nunique(dropna=True))
            sample_values = [str(value) for value in series.dropna().astype(str).head(5).tolist()]
            column_stats[column] = {
                "display_name": StructuredDataCatalog.display_label(column),
                "dtype": str(series.dtype),
                "non_null": non_null,
                "unique": unique,
                "sample_values": sample_values,
            }

        return {
            "rows": int(len(df)),
            "columns": list(df.columns),
            "numeric_columns": numeric_columns,
            "datetime_columns": datetime_columns,
            "categorical_columns": categorical_columns,
            "column_stats": column_stats,
        }


