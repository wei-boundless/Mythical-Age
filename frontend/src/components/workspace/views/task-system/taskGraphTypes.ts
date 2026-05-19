import type {
  ReactNode,
} from "react";

import type {
  ContractSpec,
  OrchestrationAgentRuntimeCatalog,
  SpecificTaskRecord,
  TaskGraphRecord,
  TaskGraphStandardView,
  TaskSystemOverview,
} from "@/lib/api";
import type { TaskGraphTemplateBuildInput, TaskGraphTemplateId } from "./taskGraphTemplates";
import type { TaskGraphDraftV2, TaskGraphPublishStateV2 } from "./taskGraphDraftV2";

export type TaskGraphKind = "single_agent" | "multi_agent" | "coordination";

export type TaskGraphNode = Record<string, unknown> & {
  node_id: string;
  node_type?: string;
  title?: string;
  label?: string;
  task_id?: string;
  agent_id?: string;
  projection_id?: string;
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
  loop_policy?: Record<string, unknown>;
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
  task_family: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  metadata?: Record<string, unknown>;
  task_modes: string[];
  tasks: SpecificTaskRecord[];
  entry_policy: TaskSystemOverview["task_management"]["entry_policies"][number] | null;
};

export type TaskGraphWorkbenchAgentCatalog = NonNullable<NonNullable<TaskSystemOverview["task_graph_management"]>["a2a"]>;

export type TaskGraphAgentCardCatalog = TaskGraphWorkbenchAgentCatalog & {
  agent_cards: Array<Record<string, unknown>>;
};

export type TaskGraphWorkbenchProps = {
  selectedDomain: TaskGraphDomainRecordLike | null;
  workspaceSlot?: ReactNode;
  taskGraphs: TaskGraphRecord[];
  selectedTaskGraphId: string;
  setSelectedTaskGraphId: (value: string) => void;
  taskGraphDraftV2: TaskGraphDraftV2;
  selectedTaskGraph: TaskGraphRecord | null;
  saving: string;
  applyTaskGraphTemplate: (template: TaskGraphTemplateId, options?: Partial<TaskGraphTemplateBuildInput>) => void;
  duplicateTaskGraphDraft: () => Promise<void>;
  sendTaskGraphToChat: (task: TaskGraphRecord | null, domain: TaskGraphDomainRecordLike | null) => void;
  saveTaskGraphStack: (nextPublished?: boolean, nextEditorPublishState?: TaskGraphPublishStateV2) => Promise<void>;
  editorValid: boolean;
  editorIssueCount: number;
  editorPublished: boolean;
  taskGraphDirty: boolean;
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  selectedDomainTasks: SpecificTaskRecord[];
  boundTaskGraphTaskIds: Set<string>;
  addTaskGraphTaskNode: (task: SpecificTaskRecord, role?: string) => void;
  addTaskGraphRoleNode: (role: string) => void;
  addTaskGraphNode: () => void;
  linkingFromNodeId: string;
  setLinkingFromNodeId: (value: string) => void;
  selectedGraphNodeId: string;
  selectedGraphEdgeId: string;
  setSelectedGraphEdgeId: (value: string) => void;
  setSelectedGraphNodeId: (value: string) => void;
  handleTopologyNodeClick: (nodeId: string) => void;
  reverseTaskGraphEdge: (edgeId: string) => void;
  removeTaskGraphEdge: (edgeId: string) => void;
  addTaskGraphSuccessorNode: (nodeId: string) => void;
  removeTaskGraphNode: (nodeId: string) => void;
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphEdge: Record<string, unknown> | null;
  agentGroupOptions: string[];
  domainTaskOptions: Array<{ value: string; label: string }>;
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphMetadata: (patch: Record<string, unknown>) => void;
  updateTaskGraphRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
  updateTaskGraphPublishState: (state: TaskGraphPublishStateV2) => void;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  taskGraphStandardView: TaskGraphStandardView | null;
  taskGraphStandardViewLoading: boolean;
  taskGraphStandardViewError: string;
  refreshTaskGraphStandardView: () => Promise<void>;
  a2aCatalog: TaskGraphAgentCardCatalog | null;
  orchestrationAgentCatalog: OrchestrationAgentRuntimeCatalog | null;
  onCreateProjectionFromPrompt?: (input: { node: Record<string, unknown>; nodeId: string; prompt: string }) => Promise<string>;
  contractSpecs: ContractSpec[];
  projectionCards?: Array<{ projection_id: string; title?: string; soul_name?: string; soul_id?: string }>;
};
