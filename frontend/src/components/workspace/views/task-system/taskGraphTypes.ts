import type { Dispatch, SetStateAction } from "react";

import type {
  ContractSpec,
  CoordinationGraphSpec,
  CoordinationTask,
  SpecificTaskRecord,
  TaskCommunicationProtocol,
  TaskSystemOverview,
  TopologyTemplate,
} from "@/lib/api";

export type TaskGraphKind = "single_agent" | "multi_agent" | "coordination";

export type TaskGraphNode = Record<string, unknown> & {
  node_id: string;
  node_type?: string;
  title?: string;
  label?: string;
  task_id?: string;
  agent_id?: string;
  role?: string;
  work_posture?: string;
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

export type TaskGraphDraft = {
  graph_id: string;
  task_id: string;
  domain_id: string;
  graph_kind: TaskGraphKind;
  title: string;
  coordination_task_id: string;
  topology_template_id: string;
  protocol_id: string;
  entry_node_id: string;
  output_node_id: string;
  agent_group_id: string;
  coordination_mode: string;
  nodes: TaskGraphNode[];
  edges: TaskGraphEdge[];
  communication_modes: string[];
  publish_state: "draft" | "published";
  metadata: Record<string, unknown>;
};

export type LegacyTaskGraphStack = {
  coordinationDraft: CoordinationTask & { stop_conditions_text: string };
  topologyDraft: TopologyTemplate & {
    nodes_text: string;
    edges_text: string;
    handoff_rules_text: string;
  };
  protocolDraft: TaskCommunicationProtocol & {
    message_types_text: string;
    payload_contracts_text: string;
    signal_rules_text: string;
    handoff_rules_text: string;
  };
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

export type TaskGraphWorkbenchAgentCatalog = NonNullable<TaskSystemOverview["coordination_management"]["a2a"]>;

export type TaskGraphWorkbenchProps = {
  selectedDomain: TaskGraphDomainRecordLike | null;
  coordinationTasks: CoordinationTask[];
  selectedCoordinationId: string;
  setSelectedCoordinationId: (value: string) => void;
  taskGraphDraft: TaskGraphDraft;
  selectedCoordination: CoordinationTask | null;
  saving: string;
  applyTaskGraphTemplate: (template: "single_agent" | "multi_sequence" | "multi_parallel_merge") => void;
  duplicateTaskGraphDraft: () => Promise<void>;
  sendTaskGraphToChat: (task: CoordinationTask | null, domain: TaskGraphDomainRecordLike | null) => void;
  saveTaskGraphDraft: () => void;
  saveTaskGraphStack: (nextPublished?: boolean) => Promise<void>;
  editorValid: boolean;
  editorIssueCount: number;
  editorPublished: boolean;
  taskGraphDirty: boolean;
  activeGraphNodes: Array<Record<string, unknown>>;
  activeGraphEdges: Array<Record<string, unknown>>;
  selectedDomainTasks: SpecificTaskRecord[];
  boundCoordinationTaskIds: Set<string>;
  addTaskGraphTaskNode: (task: SpecificTaskRecord, role?: string) => void;
  addTaskGraphRoleNode: (role: string) => void;
  addTaskGraphNode: () => void;
  addTaskGraphEdge: () => void;
  linkingFromNodeId: string;
  setLinkingFromNodeId: (value: string) => void;
  selectedGraphNodeId: string;
  selectedGraphEdgeId: string;
  setSelectedGraphEdgeId: (value: string) => void;
  setSelectedGraphNodeId: (value: string) => void;
  handleTopologyNodeClick: (nodeId: string) => void;
  reverseTaskGraphEdge: (edgeId: string) => void;
  cycleTaskGraphEdgeMode: (edgeId: string, currentMode: string) => void;
  removeTaskGraphEdge: (edgeId: string) => void;
  addTaskGraphSuccessorNode: (nodeId: string) => void;
  cycleTaskGraphNodeRole: (nodeId: string, currentRole: string) => void;
  removeTaskGraphNode: (nodeId: string) => void;
  connectSelectedNodeTo: (targetNodeId: string) => void;
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphEdge: Record<string, unknown> | null;
  legacyDrafts: LegacyTaskGraphStack;
  setCoordinationDraft: Dispatch<SetStateAction<LegacyTaskGraphStack["coordinationDraft"]>>;
  agentGroupOptions: string[];
  setTaskGraphPublished: (enabled: boolean) => void;
  setTopologyDraft: Dispatch<SetStateAction<LegacyTaskGraphStack["topologyDraft"]>>;
  setProtocolDraft: Dispatch<SetStateAction<LegacyTaskGraphStack["protocolDraft"]>>;
  domainTaskOptions: Array<{ value: string; label: string }>;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
  updateTaskGraphEdge: (edgeId: string, patch: Record<string, unknown>) => void;
  selectedTaskGraphSpec: CoordinationGraphSpec | null;
  a2aCatalog: TaskGraphWorkbenchAgentCatalog | null;
  contractSpecs: ContractSpec[];
};
