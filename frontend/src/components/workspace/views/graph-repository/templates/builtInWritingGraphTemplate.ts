import type { TaskGraphEdgeRecord, TaskGraphNodeRecord } from "@/lib/api";

import type { GraphTemplateRecord } from "./graphTemplateTypes";

const writingNodes: TaskGraphNodeRecord[] = [
  {
    node_id: "node.project_brief",
    node_type: "input",
    title: "项目启动包",
    role: "project_intake",
    execution_mode: "manual_gate",
    contract_bindings: {
      schema: {
        output_contract_id: "contract.writing.project_brief",
      },
    },
    metadata: {
      visual_tone: "artifact",
      summary: "收集题材、目标读者、风格、篇幅和禁区。",
    },
  },
  {
    node_id: "node.main_agent",
    node_type: "agent",
    title: "主 agent",
    agent_id: "agent.writing.main",
    role: "creative_owner",
    execution_mode: "sync",
    contract_bindings: {
      execution: {
        node_contract_id: "contract.writing.main_agent",
      },
      prompt: {
        role_prompt: [
          "你是这个创作世界里的主创作 agent。",
          "你负责理解用户的创作意图，维护作品目标、读者期待、风格边界和阶段性优先级。",
          "你可以把工作交给其他明确连接的 agent，但你不能凭空调用没有通过图边连接的节点。",
          "你需要尊重图中显式边和契约；坐标只表示画布位置，不代表任何节点对你的从属关系。",
          "如果输入不足，你需要指出缺口，并把需要补齐的内容交给图中合适的后续节点或等待用户确认。",
        ].join("\n"),
      },
    },
    metadata: {
      visual_tone: "agent",
      summary: "默认放置在自由世界坐标 (0,0)，只作为 home 视角锚点。",
    },
  },
  {
    node_id: "node.world_review",
    node_type: "agent",
    title: "世界观审核",
    agent_id: "agent.writing.world_reviewer",
    role: "world_review",
    execution_mode: "sync",
    contract_bindings: {
      execution: {
        node_contract_id: "contract.writing.world_review",
      },
      prompt: {
        role_prompt: [
          "你是一名世界观审核员。",
          "你只负责评审当前世界观设定是否完整、一致、可支撑后续写作。",
          "你不负责替创作者扩写设定。",
          "你需要指出问题、给出裁决、说明是否允许进入下一阶段。",
          "你需要以商业流行为目标，在有新意的同时符合大众口味。",
        ].join("\n"),
      },
    },
    metadata: {
      visual_tone: "reviewer",
      summary: "判断设定是否能支撑后续大纲和章节生产。",
    },
  },
  {
    node_id: "node.outline_planner",
    node_type: "agent",
    title: "大纲生成",
    agent_id: "agent.writing.outline_planner",
    role: "outline_planner",
    execution_mode: "sync",
    contract_bindings: {
      prompt: {
        role_prompt: [
          "你是一名商业长篇小说大纲策划。",
          "你负责把已通过审核的项目设定拆成清晰、可持续连载的主线、阶段目标、人物推动和冲突升级。",
          "你必须保留用户设定的核心趣味，不能用模板化套路覆盖作品特色。",
          "你输出的大纲需要让后续章节规划 agent 能直接继续工作。",
        ].join("\n"),
      },
    },
    metadata: {
      visual_tone: "planner",
      summary: "输出主线、大阶段和关键转折。",
    },
  },
  {
    node_id: "node.chapter_plan",
    node_type: "agent",
    title: "章节规划",
    agent_id: "agent.writing.chapter_planner",
    role: "chapter_planner",
    execution_mode: "sync",
    contract_bindings: {
      prompt: {
        role_prompt: [
          "你是一名章节规划 agent。",
          "你负责把当前大纲拆解为具体章节目标、场景顺序、信息释放、冲突推进和结尾钩子。",
          "你不直接写正文。",
          "你的输出必须让章节写作 agent 明确知道本章应该完成什么，以及不能偏离什么。",
        ].join("\n"),
      },
    },
    metadata: {
      visual_tone: "planner",
      summary: "把大纲变成可写作的章节任务。",
    },
  },
  {
    node_id: "node.chapter_writer",
    node_type: "agent",
    title: "章节写作",
    agent_id: "agent.writing.chapter_writer",
    role: "chapter_writer",
    execution_mode: "sync",
    artifact_target: "03_chapters/{chapter_id}/draft.md",
    contract_bindings: {
      prompt: {
        role_prompt: [
          "你是一名章节正文写作 agent。",
          "你只负责根据章节规划写出本章正文。",
          "你需要保持人物动机、世界规则、情绪节奏和商业可读性。",
          "你不能擅自推翻已通过的大纲和世界观；如发现冲突，必须在输出中标明冲突并等待审核节点处理。",
        ].join("\n"),
      },
    },
    metadata: {
      visual_tone: "agent",
      summary: "生成章节正文草稿。",
    },
  },
  {
    node_id: "node.chapter_review",
    node_type: "agent",
    title: "章节审核",
    agent_id: "agent.writing.chapter_reviewer",
    role: "chapter_review",
    execution_mode: "sync",
    contract_bindings: {
      prompt: {
        role_prompt: [
          "你是一名章节审核员。",
          "你负责判断章节正文是否满足章节规划、人物一致性、节奏、爽点、信息释放和读者期待。",
          "你不能替写作 agent 重写整章。",
          "你必须给出通过、返修或需要用户裁决的明确结果，并说明理由。",
        ].join("\n"),
      },
    },
    metadata: {
      visual_tone: "reviewer",
      summary: "判断章节草稿是否可进入正式入库。",
    },
  },
  {
    node_id: "node.revision_gate",
    node_type: "manual_gate",
    title: "返修裁决",
    role: "human_gate",
    execution_mode: "manual_gate",
    human_gate_policy: {
      allowed_decisions: ["pass", "revise", "replace"],
    },
    metadata: {
      visual_tone: "approval",
      summary: "用户或人工门控决定通过、返修或替换。",
    },
  },
  {
    node_id: "node.publish_chapter",
    node_type: "artifact",
    title: "正式入库",
    role: "published_artifact",
    execution_mode: "sync",
    artifact_target: "04_published/{chapter_id}.md",
    metadata: {
      visual_tone: "artifact",
      summary: "把已通过章节写入发布区。",
    },
  },
];

const writingEdges: TaskGraphEdgeRecord[] = [
  edge("edge.brief_to_main", "node.project_brief", "node.main_agent", "brief_handoff"),
  edge("edge.main_to_world_review", "node.main_agent", "node.world_review", "quality_gate"),
  edge("edge.world_to_outline", "node.world_review", "node.outline_planner", "approved_handoff"),
  edge("edge.outline_to_chapter_plan", "node.outline_planner", "node.chapter_plan", "plan_handoff"),
  edge("edge.plan_to_writer", "node.chapter_plan", "node.chapter_writer", "writing_handoff"),
  edge("edge.writer_to_review", "node.chapter_writer", "node.chapter_review", "review_handoff"),
  edge("edge.review_to_gate", "node.chapter_review", "node.revision_gate", "human_decision"),
  edge("edge.gate_to_writer", "node.revision_gate", "node.chapter_writer", "revision_loop", {
    loop: true,
    decision: "revise",
  }),
  edge("edge.gate_to_publish", "node.revision_gate", "node.publish_chapter", "publish_handoff", {
    decision: "pass",
  }),
];

export const builtInWritingGraphTemplate: GraphTemplateRecord = {
  template_id: "builtin.writing.novel_pipeline",
  title: "长篇写作图任务",
  description: "从项目启动包、世界观审核、大纲、章节规划、章节写作、章节审核到正式入库的内置写作流程。",
  category: "writing",
  source: "builtin",
  version: "2.0.0",
  readonly: true,
  graph_seed: {
    graph_id: "graph.template.writing.novel_pipeline",
    title: "长篇写作图任务",
    domain_id: "domain.writing",
    graph_kind: "multi_agent",
    entry_node_id: "node.project_brief",
    output_node_id: "node.publish_chapter",
    nodes: writingNodes,
    edges: writingEdges,
    graph_contract_id: "contract.writing.pipeline",
    contract_bindings: {
      schema: {
        graph_contract_id: "contract.writing.pipeline",
      },
      runtime: {
        relation_authority: "explicit_edges_only",
      },
    },
    default_protocol_id: "protocol.graph.structured_handoff",
    working_memory_policy_profile_id: "memory.profile.writing.project",
    working_memory_policy: {
      scope: "graph_task_instance",
      writeback: "explicit_artifacts_only",
    },
    runtime_policy: {
      coordinator_agent_id: "",
      participant_agent_ids: [
        "agent.writing.main",
        "agent.writing.world_reviewer",
        "agent.writing.outline_planner",
        "agent.writing.chapter_planner",
        "agent.writing.chapter_writer",
        "agent.writing.chapter_reviewer",
      ],
      agent_group_id: "agent_group.writing.pipeline",
      coordination_mode: "explicit_graph_edges",
      human_gate_mode: "manual_required",
    },
    context_policy: {
      shared_context_policy: "explicit_refs_only",
      memory_sharing_policy: "file_role_scoped",
      handoff_policy: "edge_contract",
    },
    loop_frames: [
      {
        loop_id: "loop.chapter_revision",
        source_node_id: "node.revision_gate",
        target_node_id: "node.chapter_writer",
        exit_edge_id: "edge.gate_to_publish",
      },
    ],
    publish_state: "draft",
    enabled: false,
    metadata: {
      category: "writing",
      builtin_template: true,
      graph_world_contract: {
        coordinate_authority: "layout_only",
        relation_authority: "explicit_nodes_edges_and_contracts",
      },
    },
  },
  editor_layout: {
    home_node_id: "node.main_agent",
    viewport: { x: 0, y: 0, zoom: 0.88 },
    node_positions: {
      "node.project_brief": { x: -300, y: 0 },
      "node.main_agent": { x: 0, y: 0 },
      "node.world_review": { x: 300, y: -120 },
      "node.outline_planner": { x: 610, y: -120 },
      "node.chapter_plan": { x: 910, y: -120 },
      "node.chapter_writer": { x: 1210, y: -120 },
      "node.chapter_review": { x: 1510, y: -120 },
      "node.revision_gate": { x: 1810, y: -10 },
      "node.publish_chapter": { x: 2110, y: -10 },
    },
    world_positions: {
      "agent.writing.main": { x: 0, y: 0, layer: "agent" },
      "resource.writing.file_space": { x: 0, y: 220, layer: "resource" },
      "resource.writing.memory": { x: 310, y: 220, layer: "resource" },
    },
    active_world_layers: ["graph", "agent", "resource"],
    selected_layer: "graph",
  },
  file_space_template: {
    file_roles: [
      role("project_brief", "项目启动包", "source", "00_project/brief.md", "markdown", true, [], ["node.main_agent"], true),
      role("world_bible", "世界观设定", "source", "01_world/world_bible.md", "markdown", true, ["node.world_review"], ["node.outline_planner"]),
      role("outline", "主线大纲", "draft", "02_outline/main_outline.md", "markdown", true, ["node.outline_planner"], ["node.chapter_plan"]),
      role("chapter_plan", "章节规划", "draft", "03_chapters/{chapter_id}/plan.md", "markdown", true, ["node.chapter_plan"], ["node.chapter_writer"]),
      role("chapter_draft", "章节草稿", "draft", "03_chapters/{chapter_id}/draft.md", "markdown", true, ["node.chapter_writer"], ["node.chapter_review"]),
      role("chapter_review", "章节审核", "review", "03_chapters/{chapter_id}/review.md", "markdown", true, ["node.chapter_review"], ["node.revision_gate"]),
      role("published_chapter", "正式章节", "published", "04_published/{chapter_id}.md", "markdown", false, ["node.publish_chapter"], [], false),
    ],
  },
  workspace_extensions: [
    {
      extension_id: "builtin.writing.chapter_desk",
      displayName: "写作台",
      appliesToTemplateCategory: ["writing"],
      componentKey: "writing_chapter_desk",
      requiredFileRoles: ["chapter_draft", "chapter_review", "published_chapter"],
    },
  ],
  default_run_config: {
    dispatch_ready: true,
    run_mode: "dispatch_only",
    runner_budget: {
      max_node_executions: 12,
      max_loop_iterations: 3,
    },
  },
  metadata: {
    system_template: true,
    relation_authority: "explicit_graph",
  },
};

function edge(
  edge_id: string,
  source_node_id: string,
  target_node_id: string,
  edge_type: string,
  metadata: Record<string, unknown> = {},
): TaskGraphEdgeRecord {
  return {
    edge_id,
    source_node_id,
    target_node_id,
    edge_type,
    ack_required: true,
    wait_policy: "source_completed",
    result_delivery_policy: "payload_ref",
    contract_bindings: {
      handoff: {
        edge_contract_id: `contract.${edge_type}`,
      },
    },
    metadata: {
      visual_tone: metadata.loop ? "loop" : edge_type.includes("review") || edge_type.includes("gate") ? "approval" : "handoff",
      ...metadata,
    },
  };
}

function role(
  role: string,
  displayName: string,
  category: "source" | "draft" | "review" | "artifact" | "published" | "runtime",
  pathPattern: string,
  contentKind: "markdown" | "json" | "text" | "code" | "binary",
  editable: boolean,
  producedBy: string[] = [],
  consumedBy: string[] = [],
  required = false,
) {
  return {
    role,
    displayName,
    category,
    pathPattern,
    contentKind,
    editable,
    producedBy,
    consumedBy,
    required,
  };
}
