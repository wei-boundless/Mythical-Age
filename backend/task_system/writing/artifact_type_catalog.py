from __future__ import annotations

from task_system.writing.artifact_projection_models import (
    ArtifactProjectionRule,
    ArtifactProjectionTarget,
    ArtifactTypeSpec,
    DesignSystemSection,
    LifecycleAdoptionRule,
)


def default_writing_artifact_types() -> tuple[ArtifactTypeSpec, ...]:
    return (
        ArtifactTypeSpec("world_design_candidate", "World design candidate", "design_init", project_memory_allowed=True, committed_readable_by_execution=True),
        ArtifactTypeSpec("power_system_candidate", "Power system candidate", "design_init", project_memory_allowed=True, committed_readable_by_execution=True),
        ArtifactTypeSpec("faction_design_candidate", "Faction design candidate", "design_init", project_memory_allowed=True, committed_readable_by_execution=True),
        ArtifactTypeSpec("character_profile_candidate", "Character profile candidate", "design_init", project_memory_allowed=True, committed_readable_by_execution=True),
        ArtifactTypeSpec("plot_outline_candidate", "Plot outline candidate", "design_init", project_memory_allowed=True, committed_readable_by_execution=True),
        ArtifactTypeSpec("chapter_draft", "Chapter draft", "chapter_cycle", project_memory_allowed=False),
        ArtifactTypeSpec("review_report", "Review report", "review", requires_review=False, project_memory_allowed=False),
        ArtifactTypeSpec("memory_commit_candidate", "Memory commit candidate", "memory_commit", project_memory_allowed=True),
        ArtifactTypeSpec("continuity_issue", "Continuity issue", "review", project_memory_allowed=True),
        ArtifactTypeSpec("style_rule_candidate", "Style rule candidate", "design_init", project_memory_allowed=True, environment_memory_candidate_allowed=True),
    )


def default_writing_design_sections() -> tuple[DesignSystemSection, ...]:
    return (
        DesignSystemSection("positioning", "Positioning", accepted_artifact_types=("world_design_candidate", "style_rule_candidate")),
        DesignSystemSection("worldbuilding", "Worldbuilding", accepted_artifact_types=("world_design_candidate",)),
        DesignSystemSection("worldbuilding.power_system", "Power system", parent_section_id="worldbuilding", accepted_artifact_types=("power_system_candidate",)),
        DesignSystemSection("worldbuilding.factions", "Factions", parent_section_id="worldbuilding", accepted_artifact_types=("faction_design_candidate",)),
        DesignSystemSection("characters", "Characters", accepted_artifact_types=("character_profile_candidate",)),
        DesignSystemSection("plot", "Plot", accepted_artifact_types=("plot_outline_candidate",)),
        DesignSystemSection("style", "Style guide", accepted_artifact_types=("style_rule_candidate",)),
        DesignSystemSection("continuity", "Continuity", accepted_artifact_types=("continuity_issue",)),
    )


def default_writing_projection_rules() -> tuple[ArtifactProjectionRule, ...]:
    return (
        _rule("projection.world_design.to_design_system", "world_design_candidate", "worldbuilding"),
        _rule("projection.power_system.to_design_system", "power_system_candidate", "worldbuilding.power_system"),
        _rule("projection.faction_design.to_design_system", "faction_design_candidate", "worldbuilding.factions"),
        _rule("projection.character_profile.to_design_system", "character_profile_candidate", "characters"),
        _rule("projection.plot_outline.to_design_system", "plot_outline_candidate", "plot"),
        _rule("projection.style_rule.to_design_system", "style_rule_candidate", "style"),
        _rule("projection.continuity_issue.to_design_system", "continuity_issue", "continuity"),
    )


def default_writing_adoption_rules() -> tuple[LifecycleAdoptionRule, ...]:
    return (
        _adoption("adopt.world_design_candidate", "world_design_candidate", "worldbuilding"),
        _adoption("adopt.power_system_candidate", "power_system_candidate", "worldbuilding.power_system"),
        _adoption("adopt.faction_design_candidate", "faction_design_candidate", "worldbuilding.factions"),
        _adoption("adopt.character_profile_candidate", "character_profile_candidate", "characters"),
        _adoption("adopt.plot_outline_candidate", "plot_outline_candidate", "plot"),
        _adoption("adopt.style_rule_candidate", "style_rule_candidate", "style"),
    )


def _rule(rule_id: str, artifact_type: str, section_id: str) -> ArtifactProjectionRule:
    return ArtifactProjectionRule(
        rule_id=rule_id,
        artifact_type=artifact_type,
        environment_id="env.creation.writing",
        project_kind="long_novel",
        target=ArtifactProjectionTarget(
            repository_id="repo.writing.memory_repository",
            section_id=section_id,
            state="candidate",
        ),
        adoption_graph_id="project.lifecycle.promote_design_artifact",
    )


def _adoption(rule_id: str, artifact_type: str, section_id: str) -> LifecycleAdoptionRule:
    return LifecycleAdoptionRule(
        rule_id=rule_id,
        artifact_type=artifact_type,
        required_review_artifact_type="review_report",
        required_verdict="approved",
        write_targets=(
            ArtifactProjectionTarget("repo.writing.memory_repository", section_id=section_id, state="committed"),
        ),
        post_actions=("refresh_file_index", "refresh_memory_index", "record_provenance"),
    )
