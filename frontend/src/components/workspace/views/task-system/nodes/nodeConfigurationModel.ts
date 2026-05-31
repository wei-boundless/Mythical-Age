import type { OrchestrationCapabilityItem, TaskNodeConfigurationSpec } from "@/lib/api";

export function nodeConfigTitle(spec: TaskNodeConfigurationSpec | null | undefined) {
  if (!spec) return "未选择节点配置";
  return spec.title || spec.node_config_id;
}

export function newNodeConfiguration(): TaskNodeConfigurationSpec {
  return {
    node_config_id: "nodecfg.custom.agent",
    title: "新节点配置",
    description: "",
    node_kind: "agent",
    environment_scope: [],
    role_prompt: "你是一名任务节点执行员。\n你只负责当前节点契约声明的职责。\n你必须按输入契约理解任务，按输出契约交付结果。\n当资源、权限或上游输入不足时，你需要停止并说明缺口。",
    executor_ref: {
      agent_selection_policy: "explicit_agent",
    },
    contract_bindings: {},
    model_requirements: {},
    tool_policy: {},
    memory_policy: {},
    artifact_policy: {},
    failure_policy: {
      failure_mode: "fail_closed",
      retry_allowed: false,
    },
    human_gate_policy: {
      required: false,
      gate_type: "none",
    },
    metadata: { managed_by: "task_node_configuration_console" },
    enabled: true,
  };
}

export function normalizeNodeConfiguration(spec: TaskNodeConfigurationSpec): TaskNodeConfigurationSpec {
  const fallback = newNodeConfiguration();
  return {
    ...fallback,
    ...spec,
    environment_scope: spec.environment_scope ?? [],
    executor_ref: spec.executor_ref ?? {},
    contract_bindings: spec.contract_bindings ?? {},
    model_requirements: spec.model_requirements ?? {},
    tool_policy: spec.tool_policy ?? {},
    memory_policy: spec.memory_policy ?? {},
    artifact_policy: spec.artifact_policy ?? {},
    failure_policy: spec.failure_policy ?? {},
    human_gate_policy: spec.human_gate_policy ?? {},
    metadata: spec.metadata ?? {},
    enabled: spec.enabled ?? true,
  };
}

export function recordId(value: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const raw = String(value[key] ?? "").trim();
    if (raw) return raw;
  }
  return "";
}

export function capabilityLabel(item: OrchestrationCapabilityItem) {
  return item.title ? `${item.title} · ${item.capability_id}` : item.capability_id;
}
