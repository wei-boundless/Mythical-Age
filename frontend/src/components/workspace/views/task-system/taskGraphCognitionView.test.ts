import { describe, expect, it } from "vitest";

import { buildTaskGraphCognitionModel } from "./taskGraphCognitionView";

describe("TaskGraph cognition view", () => {
  it("assembles a node execution cognition package from role prompt, memory, handoff, and outputs", () => {
    const nodes = [
      {
        node_id: "memory.project",
        node_type: "memory_repository",
        metadata: {
          memory_repository: {
            repository_id: "memory.project",
            collections: [{ collection_id: "requirements" }],
          },
        },
      },
      {
        node_id: "draft",
        title: "Draft",
        agent_id: "agent.writer",
        phase_id: "phase.plan",
        sequence_index: 2,
        contract_bindings: {
          schema: { output_contract_id: "contract.output" },
        },
        artifact_target: "artifacts/draft.md",
        metadata: {
          role_identity: "你是一名任务执行员。",
          responsibility_scope: "完成当前节点交付的草案。",
          definition_of_done: "输出可被下游审核的草案。",
        },
      },
      {
        node_id: "review",
        title: "Review",
        agent_id: "agent.review",
      },
    ];
    const edges = [
      {
        edge_id: "edge.memory.draft",
        source_node_id: "memory.project",
        target_node_id: "draft",
        edge_type: "memory_read",
        metadata: {
          repository: "memory.project",
          collection: "requirements",
          selector: { collection: "requirements" },
          model_visible_label: "已确认需求",
          usage_instruction: "你必须以这些需求作为约束。",
        },
      },
      {
        edge_id: "edge.draft.review",
        source_node_id: "draft",
        target_node_id: "review",
        edge_type: "structured_handoff",
        contract_bindings: {
          schema: { payload_contract_id: "contract.handoff" },
        },
        metadata: {
          model_visible_label: "草案交接包",
          usage_instruction: "审核当前草案是否满足契约。",
        },
      },
    ];

    const model = buildTaskGraphCognitionModel({ nodes, edges });
    const draft = model.packageByNodeId.get("draft");
    const review = model.packageByNodeId.get("review");

    expect(draft?.timelineScope).toBe("phase.plan/S2");
    expect(draft?.inputPackets.some((packet) => packet.kind === "memory_snapshot")).toBe(true);
    expect(draft?.outputs.some((output) => output.kind === "artifact")).toBe(true);
    expect(draft?.outputs.some((output) => output.targetId === "review")).toBe(true);
    expect(draft?.promptPreview).toContain("你会收到以下输入包");
    expect(review?.inputPackets.some((packet) => packet.kind === "handoff_packet")).toBe(true);
  });

  it("reports missing packet usage instructions as package issues", () => {
    const model = buildTaskGraphCognitionModel({
      nodes: [
        {
          node_id: "memory.project",
          node_type: "memory_repository",
          metadata: { memory_repository: { repository_id: "memory.project", collections: ["facts"] } },
        },
        { node_id: "worker", agent_id: "agent.worker" },
      ],
      edges: [
        {
          edge_id: "edge.memory.worker",
          source_node_id: "memory.project",
          target_node_id: "worker",
          edge_type: "memory_read",
          metadata: { repository: "memory.project", collection: "facts", selector: { collection: "facts" } },
        },
      ],
    });

    expect(model.packageByNodeId.get("worker")?.issues).toContain("MemorySnapshot 缺少 usage_instruction");
  });

  it("uses contract_bindings as the visible contract source", () => {
    const model = buildTaskGraphCognitionModel({
      nodes: [
        {
          node_id: "draft",
          title: "Draft",
          contract_bindings: {
            schema: {
              input_contract_id: "contract.binding.input",
              output_contract_id: "contract.binding.output",
            },
          },
          artifact_target: "artifacts/draft.md",
        },
        { node_id: "review", title: "Review" },
      ],
      edges: [
        {
          edge_id: "edge.draft.review",
          source_node_id: "draft",
          target_node_id: "review",
          edge_type: "structured_handoff",
          contract_bindings: { schema: { payload_contract_id: "contract.binding.payload" } },
          metadata: { usage_instruction: "审核绑定契约下的交接包。" },
        },
      ],
    });

    const draft = model.packageByNodeId.get("draft");
    const review = model.packageByNodeId.get("review");

    expect(draft?.inputContractId).toBe("contract.binding.input");
    expect(draft?.outputContractId).toBe("contract.binding.output");
    expect(draft?.outputs.find((output) => output.kind === "artifact")?.contractId).toBe("contract.binding.output");
    expect(draft?.outputs.find((output) => output.kind === "timeline_result")?.contractId).toBe("contract.binding.output");
    expect(review?.inputPackets.find((packet) => packet.kind === "handoff_packet")?.contractId).toBe("contract.binding.payload");
  });
});
