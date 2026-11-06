from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeAlgorithmPostprocessResult:
    progress_receipts: tuple[dict[str, Any], ...] = ()
    postprocess_errors: tuple[dict[str, Any], ...] = ()
    quality_acceptance: dict[str, Any] = field(default_factory=dict)
    side_effects: tuple[dict[str, Any], ...] = ()
    output_patch: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
