import type { ContractSpec } from "@/lib/api";

export function contractSpecTitle(spec: Pick<ContractSpec, "contract_id" | "title_zh" | "title_en"> | null | undefined) {
  if (!spec) return "未选择契约";
  return spec.title_zh || spec.title_en || spec.contract_id;
}

export function newContractSpec(kind = "workflow"): ContractSpec {
  return {
    contract_id: "contract.custom.new",
    title_zh: "新契约",
    title_en: "New Contract",
    contract_kind: kind,
    description: "",
    input_fields: [],
    output_fields: [],
    artifact_requirements: [],
    acceptance_rules: [],
    runtime_requirements: [],
    context_visibility_policy: {
      main_session_history: "summary",
      upstream_outputs: "summary",
      sibling_nodes: "status_only",
      artifact_access: "refs_only",
      memory_scopes: [],
      model_visible_sections: [],
      hidden_sections: [],
      metadata: {},
    },
    handoff_policy: {
      handoff_mode: "structured_handoff",
      include_artifact_refs: true,
      include_raw_messages: false,
      ack_required: true,
      timeout_policy: "fail_closed",
      metadata: {},
    },
    failure_policy: {
      failure_mode: "fail_closed",
      retry_allowed: false,
      retry_limit: 0,
      escalate_to: "coordinator",
      fallback_contract_id: "",
      metadata: {},
    },
    human_gate_policy: {
      required: false,
      gate_type: "none",
      reviewer_role: "",
      decision_contract_id: "",
      metadata: {},
    },
    allowed_agent_kinds: [],
    version: "1.0.0",
    enabled: true,
    metadata: { managed_by: "task_contract_console" },
  };
}

export function normalizeContractSpec(spec: ContractSpec): ContractSpec {
  const fallback = newContractSpec(spec.contract_kind || "workflow");
  return {
    ...fallback,
    ...spec,
    input_fields: spec.input_fields ?? [],
    output_fields: spec.output_fields ?? [],
    artifact_requirements: spec.artifact_requirements ?? [],
    acceptance_rules: spec.acceptance_rules ?? [],
    runtime_requirements: spec.runtime_requirements ?? [],
    context_visibility_policy: {
      ...fallback.context_visibility_policy,
      ...(spec.context_visibility_policy ?? {}),
    },
    handoff_policy: {
      ...fallback.handoff_policy,
      ...(spec.handoff_policy ?? {}),
    },
    failure_policy: {
      ...fallback.failure_policy,
      ...(spec.failure_policy ?? {}),
    },
    human_gate_policy: {
      ...fallback.human_gate_policy,
      ...(spec.human_gate_policy ?? {}),
    },
    allowed_agent_kinds: spec.allowed_agent_kinds ?? [],
    metadata: spec.metadata ?? {},
  };
}

