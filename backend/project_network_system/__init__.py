"""Project network asset, semantic graph, and maintenance system."""

from __future__ import annotations

from .build_contract_models import (
    ProjectNetworkBuildContract,
    ProjectNetworkPublicationPolicy,
    ProjectNetworkScope,
    ProjectNetworkSourceSnapshots,
)
from .directory_render_models import (
    DirectoryChildReturnEnvelope,
    DirectoryFrameMaterializationPackage,
    DirectoryManifestProduct,
    DirectoryRenderBudget,
    DirectoryRenderFrame,
    DirectoryRenderProjection,
)
from .lifecycle_policy import (
    GraphMaterializationBudget,
    GraphMaterializationModeDecision,
    choose_materialization_mode,
    validate_generation_status_transition,
)
from .projection import ProjectNetworkBuildProjection, build_project_network_projection, build_project_network_store_projection
from .repository import ProjectNetworkRepository
from .semantic_artifact_materializer import (
    ProjectNetworkSemanticArtifactMaterializer,
    ProjectNetworkSemanticArtifactSet,
)
from .service import (
    ProjectNetworkBuildService,
    ProjectNetworkGenerationMaterializationResult,
    ProjectNetworkRepairQueueResult,
    ProjectNetworkWorkProductIngestResult,
)
from .shard_models import (
    SemanticShardSpec,
    ShardAssignment,
    ShardComplexity,
    ShardComplexityPolicy,
    ShardPlan,
)
from .store_models import (
    ProjectNetworkBuildRecord,
    ProjectNetworkCandidateRecord,
    ProjectNetworkChannelState,
    ProjectNetworkEvidenceRecord,
    ProjectNetworkGenerationRecord,
    ProjectNetworkLayerIndexRecord,
    ProjectNetworkMaintenanceSignalRecord,
    ProjectNetworkRepairWorkItemRecord,
    ProjectNetworkStoreSnapshot,
    ProjectNetworkTraceRecord,
)
from .work_product_extractor import extract_graph_build_work_products
from .work_product_models import (
    GraphBuildWorkProductEnvelope,
    WorkProductChannel,
    WorkProductRef,
    reduce_work_products,
)

__all__ = [
    "DirectoryChildReturnEnvelope",
    "DirectoryFrameMaterializationPackage",
    "DirectoryManifestProduct",
    "DirectoryRenderBudget",
    "DirectoryRenderFrame",
    "DirectoryRenderProjection",
    "GraphBuildWorkProductEnvelope",
    "GraphMaterializationBudget",
    "GraphMaterializationModeDecision",
    "ProjectNetworkBuildContract",
    "ProjectNetworkBuildProjection",
    "ProjectNetworkBuildRecord",
    "ProjectNetworkBuildService",
    "ProjectNetworkCandidateRecord",
    "ProjectNetworkChannelState",
    "ProjectNetworkEvidenceRecord",
    "ProjectNetworkGenerationRecord",
    "ProjectNetworkGenerationMaterializationResult",
    "ProjectNetworkLayerIndexRecord",
    "ProjectNetworkMaintenanceSignalRecord",
    "ProjectNetworkPublicationPolicy",
    "ProjectNetworkRepairQueueResult",
    "ProjectNetworkRepairWorkItemRecord",
    "ProjectNetworkRepository",
    "ProjectNetworkScope",
    "ProjectNetworkSemanticArtifactMaterializer",
    "ProjectNetworkSemanticArtifactSet",
    "ProjectNetworkSourceSnapshots",
    "ProjectNetworkStoreSnapshot",
    "ProjectNetworkTraceRecord",
    "ProjectNetworkWorkProductIngestResult",
    "SemanticShardSpec",
    "ShardAssignment",
    "ShardComplexity",
    "ShardComplexityPolicy",
    "ShardPlan",
    "WorkProductChannel",
    "WorkProductRef",
    "build_project_network_projection",
    "build_project_network_store_projection",
    "choose_materialization_mode",
    "extract_graph_build_work_products",
    "reduce_work_products",
    "validate_generation_status_transition",
]
