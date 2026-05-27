from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, insert, select
from sqlalchemy.engine import Engine

from .models import ManagedFileRepositorySpec
from .receipts import FileOperationReceipt
from .resolver import managed_file_operation_receipts_table, managed_file_repositories_table, metadata


class FileManagementMetadataStore:
    """SQLAlchemy Core metadata store for managed file repositories and receipts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(f"sqlite:///{self.db_path}", future=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.engine.begin() as conn:
            MigrationContext.configure(conn)
            existing_tables = set(inspect(conn).get_table_names())
            if "managed_file_repositories" not in existing_tables:
                metadata.create_all(conn)

    def upsert_repository(self, *, profile_id: str, repository: ManagedFileRepositorySpec) -> None:
        payload = {
            "repository_id": repository.repository_id,
            "profile_id": profile_id,
            "repository_kind": repository.repository_kind,
            "storage_adapter": repository.storage_adapter,
            "scope_kind": repository.scope_kind,
            "root_ref": repository.root_ref,
        }
        with self.engine.begin() as conn:
            conn.execute(
                insert(managed_file_repositories_table)
                .values(**payload)
                .prefix_with("OR REPLACE")
            )

    def list_repositories(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(select(managed_file_repositories_table)).mappings().all()
        return [dict(row) for row in rows]

    def record_operation_receipt(self, receipt: FileOperationReceipt) -> None:
        payload = {
            "receipt_id": receipt.receipt_id,
            "task_run_id": receipt.task_run_id,
            "agent_run_id": receipt.agent_run_id,
            "repository_id": receipt.repository_id,
            "logical_path": receipt.logical_path,
            "access_decision": json.dumps(receipt.identity_payload(), ensure_ascii=False, sort_keys=True),
        }
        with self.engine.begin() as conn:
            conn.execute(
                insert(managed_file_operation_receipts_table)
                .values(**payload)
                .prefix_with("OR REPLACE")
            )

    def list_operation_receipts(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(select(managed_file_operation_receipts_table)).mappings().all()
        return [dict(row) for row in rows]


