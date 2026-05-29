from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..shared.artifact_refs import ArtifactRefIndex, collect_task_result_output_refs, dedupe_refs
from .continuation_policy import TaskGraphStageContract


@dataclass(frozen=True, slots=True)
class ContinuationInputBindingResult:
    explicit_inputs: dict[str, Any] = field(default_factory=dict)
    missing_required_inputs: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return bool(self.missing_required_inputs)


@dataclass(slots=True)
class ContinuationInputBinder:
    artifact_ref_index: ArtifactRefIndex

    def bind(
        self,
        *,
        stage_contract: TaskGraphStageContract,
        current_task_result: dict[str, Any] | None = None,
        current_task_ref: str = "",
        stage_outputs: dict[str, Any] | None = None,
        inherited_inputs: dict[str, Any] | None = None,
        artifact_root: str = "",
    ) -> ContinuationInputBindingResult:
        current_output_refs = collect_task_result_output_refs(dict(current_task_result or {}))
        current_task_ref = str(current_task_ref or "").strip()
        explicit_inputs = dict(inherited_inputs or {})
        resolved_stage_outputs = dict(stage_outputs or {})
        if artifact_root:
            explicit_inputs.setdefault("artifact_root", artifact_root)
            explicit_inputs.setdefault("workspace_root", artifact_root)
        diagnostics: dict[str, Any] = {
            "stage_id": stage_contract.stage_id,
            "task_ref": stage_contract.task_ref,
            "binding_count": len(stage_contract.input_bindings),
        }
        for binding in stage_contract.input_bindings:
            input_key = str(binding.get("input_key") or "").strip()
            if not input_key:
                continue
            value = self._resolve_binding(
                binding,
                current_output_refs=current_output_refs,
                current_task_ref=current_task_ref,
                stage_outputs=resolved_stage_outputs,
                inherited_inputs=explicit_inputs,
            )
            if value in ("", None, [], {}):
                if binding.get("required") is True:
                    continue
                if "default" in binding:
                    value = binding.get("default")
                else:
                    continue
            explicit_inputs[input_key] = value
        missing = self._missing_required_inputs(stage_contract=stage_contract, explicit_inputs=explicit_inputs)
        explicit_inputs.setdefault("upstream_output_refs", current_output_refs)
        return ContinuationInputBindingResult(
            explicit_inputs=explicit_inputs,
            missing_required_inputs=tuple(missing),
            diagnostics=diagnostics,
        )

    def _resolve_binding(
        self,
        binding: dict[str, Any],
        *,
        current_output_refs: list[str],
        current_task_ref: str,
        stage_outputs: dict[str, Any],
        inherited_inputs: dict[str, Any],
    ) -> Any:
        source = str(binding.get("source") or "").strip()
        if source == "current_output":
            return current_output_refs[0] if binding.get("single", True) is not False and current_output_refs else current_output_refs
        if source == "latest_output":
            task_ref = str(binding.get("task_ref") or "").strip()
            if task_ref and task_ref == current_task_ref and current_output_refs:
                return current_output_refs[0] if binding.get("single", True) is not False else current_output_refs
            refs = self.artifact_ref_index.latest_output_refs(task_ref=task_ref)
            return refs[0] if binding.get("single", True) is not False and refs else refs
        if source == "latest_output_by_contract":
            output_contract_id = str(binding.get("output_contract_id") or "").strip()
            refs = self.artifact_ref_index.latest_output_refs_by_contract(output_contract_id=output_contract_id)
            return refs[0] if binding.get("single", True) is not False and refs else refs
        if source == "inherited_input":
            key = str(binding.get("from_key") or binding.get("input_key") or "").strip()
            return inherited_inputs.get(key)
        if source == "stage_output":
            key = str(binding.get("output_key") or binding.get("from_key") or binding.get("input_key") or "").strip()
            return stage_outputs.get(key)
        if source == "literal":
            return binding.get("value")
        if source == "collect":
            values: list[Any] = []
            for item in list(binding.get("items") or []):
                if not isinstance(item, dict):
                    continue
                value = self._resolve_binding(
                    item,
                    current_output_refs=current_output_refs,
                    current_task_ref=current_task_ref,
                    stage_outputs=stage_outputs,
                    inherited_inputs=inherited_inputs,
                )
                if isinstance(value, list):
                    values.extend(value)
                elif value not in ("", None, [], {}):
                    values.append(value)
            return dedupe_refs(values)
        return None

    @staticmethod
    def _missing_required_inputs(
        *,
        stage_contract: TaskGraphStageContract,
        explicit_inputs: dict[str, Any],
    ) -> list[str]:
        required = set(stage_contract.required_inputs)
        for binding in stage_contract.input_bindings:
            if binding.get("required") is True:
                key = str(binding.get("input_key") or "").strip()
                if key:
                    required.add(key)
        missing: list[str] = []
        for key in sorted(required):
            value = explicit_inputs.get(key)
            if value in ("", None, [], {}):
                missing.append(key)
        return missing


