export type TaskGraphPolicySource =
  | "node_explicit"
  | "edge_explicit"
  | "phase_explicit"
  | "graph_default"
  | "agent_role_preset"
  | "agent_profile_default"
  | "system_default"
  | "unset";

export type TaskGraphEffectivePolicyResult = {
  key: string;
  value: unknown;
  source: TaskGraphPolicySource;
  source_label: string;
  configured: boolean;
};

export type ResolveTaskGraphEffectivePolicyInput = {
  key: string;
  node?: Record<string, unknown> | null;
  edge?: Record<string, unknown> | null;
  phase?: Record<string, unknown> | null;
  graph?: Record<string, unknown> | null;
  agentRolePreset?: Record<string, unknown> | null;
  agentProfile?: Record<string, unknown> | null;
  systemDefault?: unknown;
};

const SOURCE_LABELS: Record<TaskGraphPolicySource, string> = {
  node_explicit: "节点显式配置",
  edge_explicit: "边显式配置",
  phase_explicit: "阶段显式配置",
  graph_default: "图级默认策略",
  agent_role_preset: "Agent 角色预设",
  agent_profile_default: "Agent Profile 默认能力",
  system_default: "系统默认值",
  unset: "未配置",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function hasConfiguredValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(asRecord(value)).length > 0;
  return true;
}

function readPath(record: Record<string, unknown> | null | undefined, key: string): unknown {
  if (!record) return undefined;
  if (Object.prototype.hasOwnProperty.call(record, key)) return record[key];
  return key.split(".").reduce<unknown>((current, part) => {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    return (current as Record<string, unknown>)[part];
  }, record);
}

function readPolicyValue(record: Record<string, unknown> | null | undefined, key: string): unknown {
  const direct = readPath(record, key);
  if (hasConfiguredValue(direct)) return direct;
  const metadata = asRecord(record?.metadata);
  return readPath(metadata, key);
}

export function resolveTaskGraphEffectivePolicy({
  key,
  node,
  edge,
  phase,
  graph,
  agentRolePreset,
  agentProfile,
  systemDefault,
}: ResolveTaskGraphEffectivePolicyInput): TaskGraphEffectivePolicyResult {
  const candidates: Array<[TaskGraphPolicySource, unknown]> = [
    ["node_explicit", readPolicyValue(node, key)],
    ["edge_explicit", readPolicyValue(edge, key)],
    ["phase_explicit", readPolicyValue(phase, key)],
    ["graph_default", readPolicyValue(graph, key)],
    ["agent_role_preset", readPolicyValue(agentRolePreset, key)],
    ["agent_profile_default", readPolicyValue(agentProfile, key)],
    ["system_default", systemDefault],
  ];
  const matched = candidates.find(([, value]) => hasConfiguredValue(value));
  if (!matched) {
    return {
      key,
      value: undefined,
      source: "unset",
      source_label: SOURCE_LABELS.unset,
      configured: false,
    };
  }
  const [source, value] = matched;
  return {
    key,
    value,
    source,
    source_label: SOURCE_LABELS[source],
    configured: true,
  };
}

export function effectivePolicyDisplayValue(value: unknown): string {
  if (!hasConfiguredValue(value)) return "未配置";
  if (Array.isArray(value)) return value.map((item) => String(item)).join(" / ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
