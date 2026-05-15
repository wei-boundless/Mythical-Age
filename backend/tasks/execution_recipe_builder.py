from __future__ import annotations

from pathlib import Path
from typing import Any

from .execution_recipe_models import ExecutionRecipe, execution_recipe_from_template
from .execution_shape_resolver import ExecutionShape
from .template_registry import TaskTemplateRegistry


def build_execution_recipe(
    *,
    base_dir: Path,
    execution_shape: ExecutionShape,
) -> ExecutionRecipe:
    template_registry = TaskTemplateRegistry(base_dir)
    template = template_registry.get_template(execution_shape.recipe_preset_id)
    if template is None:
        raise ValueError(f"Unknown execution recipe preset: {execution_shape.recipe_preset_id}")
    recipe = execution_recipe_from_template(
        template,
        execution_kind=execution_shape.execution_kind,
        source_kind=execution_shape.source_kind,
        artifact_policy=execution_shape.artifact_policy,
        finalization_policy=execution_shape.finalization_policy,
    )
    metadata = {
        **dict(recipe.metadata or {}),
        "execution_shape": execution_shape.to_dict(),
    }
    return ExecutionRecipe(
        recipe_id=recipe.recipe_id,
        title=recipe.title,
        description=recipe.description,
        execution_kind=recipe.execution_kind,
        task_family=recipe.task_family,
        task_mode=recipe.task_mode,
        source_kind=recipe.source_kind,
        input_schema=dict(recipe.input_schema),
        output_schema=dict(recipe.output_schema),
        default_agent_id=recipe.default_agent_id,
        allowed_agent_ids=tuple(recipe.allowed_agent_ids),
        required_capability_tags=tuple(recipe.required_capability_tags),
        required_operations=tuple(recipe.required_operations),
        optional_operations=tuple(recipe.optional_operations),
        step_blueprints=tuple(recipe.step_blueprints),
        validation_rules=tuple(recipe.validation_rules),
        safety_policy=dict(recipe.safety_policy),
        artifact_policy=dict(recipe.artifact_policy),
        finalization_policy=dict(recipe.finalization_policy),
        ui_manifest=dict(recipe.ui_manifest),
        enabled=bool(recipe.enabled),
        metadata=metadata,
        legacy_template_id=recipe.legacy_template_id,
    )
