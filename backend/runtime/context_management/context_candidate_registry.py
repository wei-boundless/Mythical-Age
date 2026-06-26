from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .context_candidates import ContextCandidate


class ContextCandidateContributor(Protocol):
    contributor_id: str

    def collect_context_candidates(self, request: dict[str, Any]) -> tuple[ContextCandidate, ...]:
        ...


@dataclass(slots=True)
class ContextCandidateRegistry:
    contributors: dict[str, ContextCandidateContributor] = field(default_factory=dict)

    def register(self, contributor: ContextCandidateContributor) -> None:
        contributor_id = str(getattr(contributor, "contributor_id", "") or "").strip()
        if not contributor_id:
            raise ValueError("context candidate contributor requires contributor_id")
        self.contributors[contributor_id] = contributor

    def collect(self, request: dict[str, Any] | None = None) -> tuple[ContextCandidate, ...]:
        payload = dict(request or {})
        candidates: list[ContextCandidate] = []
        for contributor in self.contributors.values():
            for candidate in tuple(contributor.collect_context_candidates(payload) or ()):
                if isinstance(candidate, ContextCandidate):
                    candidates.append(candidate)
        return tuple(candidates)
