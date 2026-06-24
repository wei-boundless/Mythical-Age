import type {
  SpecificTaskRecord,
  TaskSystemOverview,
} from "@/lib/api";

export type TaskGraphKind = "single_agent" | "multi_agent" | "coordination";

export type TaskGraphNode = Record<string, unknown> & {
  node_id: string;
  node_type?: string;
  title?: string;
  label?: string;
  task_id?: string;
  agent_id?: string;
  executor_policy?: Record<string, unknown>;
  role?: string;
  work_posture?: string;
  phase_id?: string;
  sequence_index?: number;
  timeline_group_id?: string;
  main_chain?: boolean;
  start_policy?: string;
  completion_policy?: string;
  blocks_phase_exit?: boolean;
  loop?: Record<string, unknown>;
  review_gate_policy?: Record<string, unknown>;
};

export type TaskGraphEdge = Record<string, unknown> & {
  edge_id?: string;
  from?: string;
  to?: string;
  source_node_id?: string;
  target_node_id?: string;
  edge_type?: string;
  mode?: string;
};

export type TaskGraphDomainRecordLike = {
  domain_id: string;
  title: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
  task_modes: string[];
  tasks: SpecificTaskRecord[];
  entry_policy: TaskSystemOverview["task_management"]["entry_policies"][number] | null;
};
