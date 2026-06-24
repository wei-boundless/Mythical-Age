import type { TaskGraphRecord } from "@/lib/api";

import {
  emptyTaskGraphDraftV2,
  inferTaskGraphBoundaryNodes,
  taskGraphRecordToDraftV2,
  type TaskGraphDraftV2,
} from "../../task-system/taskGraphDraftV2";

export type GraphTemplateCategory = "writing" | "review" | "research" | "automation" | "custom";
export type GraphTemplateSource = "builtin" | "user" | "plugin" | "mcp";
export type GraphWorldLayer = "graph" | "agent" | "resource" | "runtime";

export type GraphEditorLayout = {
  home_node_id?: string;
  viewport: { x: number; y: number; zoom: number };
  node_positions: Record<string, { x: number; y: number }>;
  world_positions?: Record<string, { x: number; y: number; layer: "agent" | "resource" | "template" }>;
  active_world_layers?: GraphWorldLayer[];
  collapsed_groups?: string[];
  selected_layer?: string;
};

export type GraphFileRoleRegistration = {
  role: string;
  displayName: string;
  category: "source" | "draft" | "review" | "artifact" | "published" | "runtime";
  pathPattern: string;
  contentKind: "markdown" | "json" | "text" | "code" | "binary";
  editable: boolean;
  producedBy?: string[];
  consumedBy?: string[];
  required?: boolean;
};

export type GraphInstanceFileSpaceTemplate = {
  file_roles: GraphFileRoleRegistration[];
};

export type GraphInstanceWorkspaceExtension = {
  extension_id: string;
  displayName: string;
  appliesToTemplateCategory: string[];
  componentKey: "writing_chapter_desk" | "default_file_desk" | string;
  requiredFileRoles?: string[];
};

export type GraphConversationPortBinding = {
  mode: "graph_assistant" | "node_config" | "node_session" | "resource" | "edge_contract";
  graph_id: string;
  graph_task_instance_id?: string;
  graph_run_id?: string;
  node_id?: string;
  edge_id?: string;
  session_id?: string;
  scope?: {
    workspace_view: "graph_task";
    project_id?: string;
    node_id?: string;
  };
};

export type GraphTemplateRecord = {
  template_id: string;
  title: string;
  description?: string;
  category: GraphTemplateCategory;
  source: GraphTemplateSource;
  version: string;
  readonly: boolean;
  graph_seed: TaskGraphRecord;
  editor_layout?: GraphEditorLayout;
  file_space_template?: GraphInstanceFileSpaceTemplate;
  workspace_extensions?: GraphInstanceWorkspaceExtension[];
  default_run_config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export function cloneGraphRecord(graph: TaskGraphRecord): TaskGraphRecord {
  return JSON.parse(JSON.stringify(graph)) as TaskGraphRecord;
}

export function graphTemplateDraftId(template: GraphTemplateRecord, now = Date.now()) {
  const base = template.template_id
    .replace(/^builtin\./, "")
    .replace(/[^a-zA-Z0-9_.-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `graph.${base || "custom"}.${now.toString(36)}`;
}

export function createDraftFromTemplate(
  template: GraphTemplateRecord,
  options: { graphId?: string; title?: string; now?: number } = {},
): TaskGraphDraftV2 {
  const graphId = options.graphId || graphTemplateDraftId(template, options.now);
  const seed = cloneGraphRecord(template.graph_seed);
  const editorLayout = normalizeGraphEditorLayout(template.editor_layout, seed);
  const boundaries = inferTaskGraphBoundaryNodes(seed.nodes ?? [], seed.edges ?? [], {
    fallback_entry_node_id: seed.entry_node_id,
    fallback_output_node_id: seed.output_node_id,
  });
  const record: TaskGraphRecord = {
    ...seed,
    graph_id: graphId,
    title: options.title || `${template.title} 副本`,
    entry_node_id: boundaries.entry_node_id,
    output_node_id: boundaries.output_node_id,
    publish_state: "draft",
    enabled: false,
    metadata: {
      ...(seed.metadata ?? {}),
      template_id: template.template_id,
      template_version: template.version,
      template_source: template.source,
      editor_publish_state: "draft",
      editor_layout: editorLayout,
      file_space_template: template.file_space_template,
      workspace_extensions: template.workspace_extensions ?? [],
      default_run_config: template.default_run_config ?? {},
      graph_world_contract: {
        coordinate_authority: "layout_only",
        relation_authority: "explicit_nodes_edges_and_contracts",
        home_node_is_not_entry_or_scheduler: true,
      },
    },
  };
  const draft = taskGraphRecordToDraftV2(record);
  return {
    ...emptyTaskGraphDraftV2(),
    ...draft,
    metadata: record.metadata ?? {},
    publish_state: "draft",
    ui_state: {
      ...draft.ui_state,
      selected_node_id: editorLayout.home_node_id || draft.ui_state.selected_node_id,
      active_layer: "graph",
    },
  };
}

export function createDraftFromGraph(graph: TaskGraphRecord, options: { duplicate?: boolean; now?: number } = {}) {
  const source = cloneGraphRecord(graph);
  if (options.duplicate) {
    const suffix = (options.now ?? Date.now()).toString(36);
    source.graph_id = `${source.graph_id}.copy.${suffix}`;
    source.title = `${source.title || source.graph_id} 副本`;
    source.enabled = false;
    source.publish_state = "draft";
    source.metadata = {
      ...(source.metadata ?? {}),
      source_graph_id: graph.graph_id,
      editor_publish_state: "draft",
      duplicated_at: new Date(options.now ?? Date.now()).toISOString(),
    };
  }
  const layout = normalizeGraphEditorLayout(
    (source.metadata?.editor_layout ?? null) as GraphEditorLayout | null,
    source,
  );
  return {
    ...taskGraphRecordToDraftV2({
      ...source,
      metadata: {
        ...(source.metadata ?? {}),
        editor_layout: layout,
      },
    }),
    metadata: {
      ...(source.metadata ?? {}),
      editor_layout: layout,
    },
  };
}

export function normalizeGraphEditorLayout(layout: GraphEditorLayout | null | undefined, graph: TaskGraphRecord): GraphEditorLayout {
  const sourcePositions = layout?.node_positions && typeof layout.node_positions === "object"
    ? layout.node_positions
    : {};
  const nodes = graph.nodes ?? [];
  const node_positions = nodes.reduce<Record<string, { x: number; y: number }>>((acc, node, index) => {
    const nodeId = node.node_id;
    const existing = sourcePositions[nodeId];
    const metadataPosition = node.metadata?.editor_position as { x?: unknown; y?: unknown } | undefined;
    const x = finiteNumber(existing?.x) ?? finiteNumber(metadataPosition?.x) ?? (index % 3) * 280;
    const y = finiteNumber(existing?.y) ?? finiteNumber(metadataPosition?.y) ?? Math.floor(index / 3) * 150;
    acc[nodeId] = { x, y };
    return acc;
  }, {});
  const homeNodeId = String(layout?.home_node_id || "").trim();
  const validHomeNodeId = homeNodeId && nodes.some((node) => node.node_id === homeNodeId) ? homeNodeId : "";
  if (validHomeNodeId && !sourcePositions[validHomeNodeId]) {
    node_positions[validHomeNodeId] = { x: 0, y: 0 };
  }
  return {
    home_node_id: validHomeNodeId || undefined,
    viewport: {
      x: finiteNumber(layout?.viewport?.x) ?? 0,
      y: finiteNumber(layout?.viewport?.y) ?? 0,
      zoom: finiteNumber(layout?.viewport?.zoom) ?? 0.92,
    },
    node_positions,
    world_positions: layout?.world_positions ?? {},
    active_world_layers: layout?.active_world_layers ?? ["graph", "agent", "resource"],
    collapsed_groups: layout?.collapsed_groups ?? [],
    selected_layer: layout?.selected_layer ?? "graph",
  };
}

export function draftEditorLayout(draft: TaskGraphDraftV2): GraphEditorLayout {
  return normalizeGraphEditorLayout(
    (draft.metadata?.editor_layout ?? null) as GraphEditorLayout | null,
    {
      graph_id: draft.graph_id,
      title: draft.title,
      domain_id: draft.domain_id,
      graph_kind: draft.graph_kind,
      entry_node_id: draft.entry_node_id,
      output_node_id: draft.output_node_id,
      nodes: draft.nodes,
      edges: draft.edges,
      publish_state: draft.publish_state === "published" || draft.publish_state === "run_bound" ? "published" : "draft",
      enabled: draft.publish_state === "published" || draft.publish_state === "run_bound",
      metadata: draft.metadata,
    },
  );
}

export function graphTemplateFromDraft(
  draft: TaskGraphDraftV2,
  options: { templateId: string; title: string; description?: string; category?: GraphTemplateCategory },
): GraphTemplateRecord {
  const layout = draftEditorLayout(draft);
  return {
    template_id: options.templateId,
    title: options.title,
    description: options.description,
    category: options.category ?? "custom",
    source: "user",
    version: "1.0.0",
    readonly: false,
    graph_seed: {
      graph_id: draft.graph_id,
      title: draft.title,
      domain_id: draft.domain_id,
      graph_kind: draft.graph_kind,
      entry_node_id: draft.entry_node_id,
      output_node_id: draft.output_node_id,
      nodes: draft.nodes,
      edges: draft.edges,
      graph_contract_id: draft.graph_contract_id,
      contract_bindings: draft.contract_bindings,
      default_protocol_id: draft.default_protocol_id,
      working_memory_policy_profile_id: draft.working_memory_policy_profile_id,
      working_memory_policy: draft.working_memory_policy,
      runtime_policy: draft.runtime_policy,
      context_policy: draft.context_policy,
      loop_frames: draft.loop_frames,
      publish_state: "draft",
      enabled: false,
      metadata: {
        ...(draft.metadata ?? {}),
        editor_layout: layout,
      },
    },
    editor_layout: layout,
    file_space_template: draft.metadata?.file_space_template as GraphInstanceFileSpaceTemplate | undefined,
    workspace_extensions: draft.metadata?.workspace_extensions as GraphInstanceWorkspaceExtension[] | undefined,
    default_run_config: draft.metadata?.default_run_config as Record<string, unknown> | undefined,
  };
}

function finiteNumber(value: unknown): number | undefined {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : undefined;
}
