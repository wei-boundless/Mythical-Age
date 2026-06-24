import type { TaskGraphNodeRecord } from "@/lib/api";

export type ValidationIssue = {
  code: string;
  severity: "info" | "warning" | "error" | "blocker";
  message: string;
};

export type ValidationContext = {
  nodes: TaskGraphNodeRecord[];
};

export type TaskGraphNodeRegistration = {
  kind: string;
  displayName: string;
  category: "agent" | "memory" | "artifact" | "gate" | "loop" | "external";
  visual: {
    icon: string;
    tone: "agent" | "reviewer" | "planner" | "memory" | "artifact" | "approval" | "loop" | "external" | "operator" | "custom";
    shape?: "rectangle" | "rounded" | "circle" | "diamond";
  };
  backendMapping: {
    nodeTypes: string[];
    defaultExecutionMode?: string;
    defaultWaitPolicy?: string;
    defaultJoinPolicy?: string;
  };
  defaultNodeConfig: Partial<TaskGraphNodeRecord>;
  validate?: (node: TaskGraphNodeRecord, context: ValidationContext) => ValidationIssue[];
};

export const taskGraphNodeRegistrations: TaskGraphNodeRegistration[] = [
  {
    kind: "agent",
    displayName: "Agent 节点",
    category: "agent",
    visual: { icon: "bot", tone: "agent", shape: "rounded" },
    backendMapping: { nodeTypes: ["agent"], defaultExecutionMode: "sync" },
    defaultNodeConfig: {
      node_type: "agent",
      title: "新 Agent",
      execution_mode: "sync",
      contract_bindings: {
        prompt: {
          role_prompt: "你是一个被图显式连接的 agent。你只处理输入契约允许的任务，并把输出交给图中明确连接的后续节点。",
        },
      },
    },
  },
  {
    kind: "reviewer",
    displayName: "审核 Agent",
    category: "agent",
    visual: { icon: "badge-check", tone: "reviewer", shape: "rounded" },
    backendMapping: { nodeTypes: ["agent"], defaultExecutionMode: "sync" },
    defaultNodeConfig: {
      node_type: "agent",
      title: "审核 Agent",
      execution_mode: "sync",
      contract_bindings: {
        prompt: {
          role_prompt: "你是一名审核 agent。你负责检查输入是否满足质量标准，给出问题、裁决和是否允许进入下一阶段。",
        },
      },
    },
  },
  {
    kind: "planner",
    displayName: "规划 Agent",
    category: "agent",
    visual: { icon: "list-tree", tone: "planner", shape: "rounded" },
    backendMapping: { nodeTypes: ["agent"], defaultExecutionMode: "sync" },
    defaultNodeConfig: {
      node_type: "agent",
      title: "规划 Agent",
      execution_mode: "sync",
      contract_bindings: {
        prompt: {
          role_prompt: "你是一名规划 agent。你负责把目标拆成清晰步骤、输入要求、输出要求和后续交接条件。",
        },
      },
    },
  },
  {
    kind: "manual_gate",
    displayName: "人工门控",
    category: "gate",
    visual: { icon: "shield-check", tone: "approval", shape: "diamond" },
    backendMapping: { nodeTypes: ["manual_gate"], defaultExecutionMode: "manual_gate" },
    defaultNodeConfig: {
      node_type: "manual_gate",
      title: "人工门控",
      execution_mode: "manual_gate",
      human_gate_policy: {
        allowed_decisions: ["pass", "revise", "replace"],
      },
    },
  },
  {
    kind: "artifact",
    displayName: "产物节点",
    category: "artifact",
    visual: { icon: "file-output", tone: "artifact", shape: "rectangle" },
    backendMapping: { nodeTypes: ["artifact"], defaultExecutionMode: "sync" },
    defaultNodeConfig: {
      node_type: "artifact",
      title: "产物节点",
      execution_mode: "sync",
    },
  },
  {
    kind: "memory",
    displayName: "记忆资源",
    category: "memory",
    visual: { icon: "database", tone: "memory", shape: "rectangle" },
    backendMapping: { nodeTypes: ["memory"], defaultExecutionMode: "sync" },
    defaultNodeConfig: {
      node_type: "memory",
      title: "记忆资源",
      execution_mode: "sync",
    },
  },
  {
    kind: "external",
    displayName: "外部资源",
    category: "external",
    visual: { icon: "plug", tone: "external", shape: "rectangle" },
    backendMapping: { nodeTypes: ["external"], defaultExecutionMode: "sync" },
    defaultNodeConfig: {
      node_type: "external",
      title: "外部资源",
      execution_mode: "sync",
    },
  },
];

export function taskGraphNodeRegistrationForNode(node: Pick<TaskGraphNodeRecord, "node_type" | "metadata" | "role">) {
  const tone = String(node.metadata?.visual_tone ?? "").trim();
  const byTone = tone ? taskGraphNodeRegistrations.find((item) => item.visual.tone === tone || item.kind === tone) : null;
  if (byTone) return byTone;
  return taskGraphNodeRegistrations.find((item) => item.backendMapping.nodeTypes.includes(String(node.node_type || "")))
    ?? taskGraphNodeRegistrations[0];
}

export function createNodeFromRegistration(registration: TaskGraphNodeRegistration, index: number): TaskGraphNodeRecord {
  const idSuffix = `${registration.kind}_${String(index + 1).padStart(2, "0")}`;
  return {
    node_id: `node.${idSuffix}`,
    node_type: registration.defaultNodeConfig.node_type || "agent",
    title: registration.defaultNodeConfig.title || registration.displayName,
    role: registration.defaultNodeConfig.role || registration.kind,
    execution_mode: registration.backendMapping.defaultExecutionMode || "sync",
    ...registration.defaultNodeConfig,
    metadata: {
      ...(registration.defaultNodeConfig.metadata ?? {}),
      visual_tone: registration.visual.tone,
    },
  };
}
