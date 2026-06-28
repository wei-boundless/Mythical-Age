from __future__ import annotations

from capability_system.capabilities.document_processing.projections.evidence_projection import build_evidence_projection
from capability_system.capabilities.document_processing.projections.office_projection import build_office_projection
from capability_system.capabilities.document_processing.projections.rag_projection import RagProjectionBuilder

__all__ = [
    "RagProjectionBuilder",
    "build_evidence_projection",
    "build_office_projection",
]
