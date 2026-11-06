from __future__ import annotations

from collections import Counter
from pathlib import Path

from capability_system.tools.workspace_file_service import WorkspaceFileService
from core.project_layout import ProjectLayout

from .repository import ProjectStructureRepository, content_hash, stable_project_structure_id
from .skeleton_extractors import extract_file_tree_facts, extract_git_snapshot_facts, extract_python_deep_ast_facts
from .skeleton_models import SkeletonExtractionReport, SkeletonGenerationRecord
from .skeleton_normalizer import normalize_skeleton_facts


class ProjectStructureIndexService:
    authority = "file_management.project_structure.index_service"

    def __init__(
        self,
        *,
        repository: ProjectStructureRepository,
        file_service: WorkspaceFileService,
        project_root: str | Path,
    ) -> None:
        self.repository = repository
        self.file_service = file_service
        self.project_root = Path(project_root).resolve()

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "ProjectStructureIndexService":
        layout = ProjectLayout.from_backend_dir(base_dir)
        return cls(
            repository=ProjectStructureRepository(base_dir),
            file_service=WorkspaceFileService(base_dir),
            project_root=layout.project_root,
        )

    def build_skeleton_generation(
        self,
        *,
        build_id: str,
        scope_roots: tuple[str, ...] | list[str] = (),
        generation: int | None = None,
        include_git_snapshot: bool = True,
    ) -> SkeletonExtractionReport:
        resolved_build_id = str(build_id or "").strip()
        if not resolved_build_id:
            raise ValueError("ProjectStructureIndexService.build_skeleton_generation requires build_id")
        resolved_generation = int(generation or 0) or _next_skeleton_generation(self.repository, resolved_build_id)
        roots = tuple(str(item or "").strip().replace("\\", "/") for item in tuple(scope_roots or ()) if str(item or "").strip())
        facts = [
            *extract_file_tree_facts(
                file_service=self.file_service,
                build_id=resolved_build_id,
                generation=resolved_generation,
                scope_roots=roots,
            ),
            *extract_python_deep_ast_facts(
                file_service=self.file_service,
                build_id=resolved_build_id,
                generation=resolved_generation,
                scope_roots=roots,
            ),
        ]
        if include_git_snapshot:
            facts.extend(
                extract_git_snapshot_facts(
                    project_root=self.project_root,
                    build_id=resolved_build_id,
                    generation=resolved_generation,
                )
            )
        self.repository.upsert_skeleton_facts(tuple(facts))
        nodes, edges = normalize_skeleton_facts(build_id=resolved_build_id, generation=resolved_generation, facts=tuple(facts))
        self.repository.upsert_skeleton_nodes(nodes)
        self.repository.upsert_skeleton_edges(edges)
        extractor_counts = dict(Counter(fact.source_kind for fact in facts))
        source_snapshot_ref = content_hash(
            {
                "build_id": resolved_build_id,
                "generation": resolved_generation,
                "scope_roots": roots,
                "fact_hashes": [fact.content_hash for fact in facts],
            }
        )
        self.repository.upsert_skeleton_generation(
            SkeletonGenerationRecord(
                skeleton_generation_id=stable_project_structure_id("pnskelgen", resolved_build_id, resolved_generation),
                build_id=resolved_build_id,
                generation=resolved_generation,
                status="candidate",
                source_snapshot_ref=source_snapshot_ref,
                fact_count=len(facts),
                node_count=len(nodes),
                edge_count=len(edges),
                payload={
                    "scope_roots": list(roots),
                    "extractor_counts": extractor_counts,
                    "physical_layer_only": True,
                    "semantic_overlay_source": "project_structure_semantic_overlays",
                },
            )
        )
        return SkeletonExtractionReport(
            build_id=resolved_build_id,
            generation=resolved_generation,
            scope_roots=roots,
            fact_count=len(facts),
            node_count=len(nodes),
            edge_count=len(edges),
            extractor_counts=extractor_counts,
            limitations=_limitations(facts=tuple(facts)),
        )


def _next_skeleton_generation(repository: ProjectStructureRepository, build_id: str) -> int:
    generations = repository.list_skeleton_generations(build_id=build_id, limit=1)
    if not generations:
        return 1
    return max(1, int(generations[0].generation or 0) + 1)


def _limitations(*, facts: tuple[object, ...]) -> tuple[str, ...]:
    has_unresolved = any(str(getattr(fact, "confidence", "")) == "unresolved" for fact in facts)
    limitations = ["semantic_role_not_inferred_by_physical_skeleton"]
    if has_unresolved:
        limitations.append("some_code_links_are_text_candidates_until_symbol_resolution")
    return tuple(limitations)
