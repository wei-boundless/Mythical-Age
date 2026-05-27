from __future__ import annotations

from pathlib import Path
from typing import Callable

from task_system.registry.flow_models import TaskDomainRecord
from task_system.repositories.common import merge_default_overlay_by_key
from task_system.storage import TaskSystemStorage


class TaskDomainRepository:
    def __init__(
        self,
        base_dir: Path,
        *,
        default_domains: Callable[[], tuple[TaskDomainRecord, ...]],
    ) -> None:
        self.storage = TaskSystemStorage(base_dir)
        self.default_domains = default_domains

    def list(self) -> list[TaskDomainRecord]:
        default_payload = [item.to_dict() for item in self.default_domains()]
        payload = self.storage.read_object(
            "task_domains.json",
            {"task_domains": default_payload},
        )
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip()
        }
        merged_payload = merge_default_overlay_by_key(
            [item for item in default_payload if str(item.get("domain_id") or "").strip() not in deleted_domain_ids],
            [item for item in list(payload.get("task_domains") or []) if isinstance(item, dict)],
            key="domain_id",
        )
        domains: list[TaskDomainRecord] = []
        for item in merged_payload:
            domain_id = str(item.get("domain_id") or "").strip()
            if not domain_id:
                continue
            domains.append(
                TaskDomainRecord(
                    domain_id=domain_id,
                    title=str(item.get("title") or domain_id).strip(),
                    description=str(item.get("description") or "").strip(),
                    enabled=bool(item.get("enabled", True)),
                    sort_order=int(item.get("sort_order", 0) or 0),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        domains = sorted(domains, key=lambda item: (item.sort_order, item.title, item.domain_id))
        normalized = [item.to_dict() for item in domains]
        if payload.get("task_domains") != normalized:
            self.storage.write_object(
                "task_domains.json",
                {
                    "task_domains": normalized,
                    "deleted_domain_ids": sorted(deleted_domain_ids),
                },
            )
        return domains

    def get(self, domain_id: str) -> TaskDomainRecord | None:
        target = str(domain_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list() if item.domain_id == target), None)

    def upsert(
        self,
        *,
        domain_id: str,
        title: str,
        description: str = "",
        enabled: bool = True,
        sort_order: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> TaskDomainRecord:
        normalized_domain_id = str(domain_id or "").strip()
        if not normalized_domain_id.startswith("domain."):
            raise ValueError("domain_id must start with domain.")
        record = TaskDomainRecord(
            domain_id=normalized_domain_id,
            title=str(title or normalized_domain_id).strip(),
            description=str(description or "").strip(),
            enabled=bool(enabled),
            sort_order=int(sort_order),
            metadata=dict(metadata or {}),
        )
        domains = [item for item in self.list() if item.domain_id != normalized_domain_id]
        domains.append(record)
        domains = sorted(domains, key=lambda item: (item.sort_order, item.title, item.domain_id))
        payload = self.storage.read_object("task_domains.json", {"task_domains": []})
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip() and str(item).strip() != normalized_domain_id
        }
        self.storage.write_object(
            "task_domains.json",
            {
                "task_domains": [item.to_dict() for item in domains],
                "deleted_domain_ids": sorted(deleted_domain_ids),
            },
        )
        return record

    def mark_deleted(self, domain_id: str) -> list[TaskDomainRecord]:
        target = str(domain_id or "").strip()
        domains = [item for item in self.list() if item.domain_id != target]
        payload = self.storage.read_object("task_domains.json", {"task_domains": []})
        deleted_domain_ids = {
            str(item).strip()
            for item in list(payload.get("deleted_domain_ids") or [])
            if str(item).strip()
        }
        deleted_domain_ids.add(target)
        self.storage.write_object(
            "task_domains.json",
            {
                "task_domains": [item.to_dict() for item in domains],
                "deleted_domain_ids": sorted(deleted_domain_ids),
            },
        )
        return domains


