"""Project network build contracts and graph materialization helpers."""

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
from .directory_render_service import DirectoryRenderService
from .directory_run_models import (
    DirectoryFrameGraphPublishResult,
    DirectoryFrameSchedulerDecision,
)
from .directory_runtime_service import DirectoryRuntimeService
from .graph_builder import ProjectNetworkGraphBuilder
from .layer_plan_models import (
    GraphGenerationLineage,
    NextGraphMaterializationPackage,
    NodeRouteDecision,
    ProjectNetworkBootstrapPlan,
    ProjectNetworkBuildPlan,
    ProjectNetworkLayerPlan,
    ProjectStructureIntakeProduct,
    StaticGraphMaterializationPackage,
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
from .service import ProjectNetworkBuildService, ProjectNetworkWorkProductIngestResult
from .shard_models import (
    SemanticShardSpec,
    ShardAssignment,
    ShardComplexity,
    ShardComplexityPolicy,
    ShardExecutorPolicy,
    ShardPlan,
)
from .store_models import (
    ProjectNetworkBuildRecord,
    ProjectNetworkCandidateRecord,
    ProjectNetworkChannelState,
    ProjectNetworkEvidenceRecord,
    ProjectNetworkGenerationRecord,
    ProjectNetworkLayerIndexRecord,
    ProjectNetworkStoreSnapshot,
    ProjectNetworkTraceRecord,
)
from .shard_planner import build_next_layer_shard_plan, build_static_shard_plan
from .template_catalog import (
    ProjectNetworkNodeTemplate,
    build_project_network_template_catalog,
    resolve_project_network_node_template,
)
from .work_product_extractor import extract_graph_build_work_products
from .work_product_models import (
    GraphBuildWorkProductEnvelope,
    WorkProductChannel,
    WorkProductRef,
    reduce_work_products,
)


__all__ = [
    "GraphBuildWorkProductEnvelope",
    "DirectoryChildReturnEnvelope",
    "DirectoryFrameMaterializationPackage",
    "DirectoryManifestProduct",
    "DirectoryRenderBudget",
    "DirectoryRenderFrame",
    "DirectoryRenderProjection",
    "DirectoryRenderService",
    "DirectoryFrameGraphPublishResult",
    "DirectoryFrameSchedulerDecision",
    "DirectoryRuntimeService",
    "GraphGenerationLineage",
    "GraphMaterializationBudget",
    "GraphMaterializationModeDecision",
    "NextGraphMaterializationPackage",
    "NodeRouteDecision",
    "ProjectNetworkBootstrapPlan",
    "ProjectNetworkBuildContract",
    "ProjectNetworkBuildPlan",
    "ProjectNetworkBuildProjection",
    "ProjectNetworkBuildRecord",
    "ProjectNetworkBuildService",
    "ProjectNetworkGraphBuilder",
    "ProjectNetworkLayerPlan",
    "ProjectNetworkLayerIndexRecord",
    "ProjectNetworkNodeTemplate",
    "ProjectNetworkPublicationPolicy",
    "ProjectNetworkRepository",
    "ProjectNetworkSemanticArtifactMaterializer",
    "ProjectNetworkSemanticArtifactSet",
    "ProjectNetworkScope",
    "ProjectNetworkSourceSnapshots",
    "ProjectNetworkStoreSnapshot",
    "ProjectStructureIntakeProduct",
    "ProjectNetworkCandidateRecord",
    "ProjectNetworkChannelState",
    "ProjectNetworkEvidenceRecord",
    "ProjectNetworkGenerationRecord",
    "ProjectNetworkTraceRecord",
    "ProjectNetworkWorkProductIngestResult",
    "SemanticShardSpec",
    "ShardAssignment",
    "ShardComplexity",
    "ShardComplexityPolicy",
    "ShardExecutorPolicy",
    "ShardPlan",
    "StaticGraphMaterializationPackage",
    "WorkProductChannel",
    "WorkProductRef",
    "build_next_layer_shard_plan",
    "build_project_network_projection",
    "build_project_network_store_projection",
    "build_project_network_template_catalog",
    "build_static_shard_plan",
    "choose_materialization_mode",
    "extract_graph_build_work_products",
    "reduce_work_products",
    "resolve_project_network_node_template",
    "validate_generation_status_transition",
]
