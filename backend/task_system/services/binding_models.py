from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class StructuredDatasetBinding:
    dataset_path: str = ""
    target_object: str = ""
    source: str = ""
    confidence: float = 0.0
    binding_identity: str = ""
    derived_from_task_id: str = ""
    explicit_switch: bool = False

    def is_bound(self) -> bool:
        return bool(self.dataset_path.strip())

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


