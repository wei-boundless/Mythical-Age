import { Cable, GitBranch, Layers3, Plus } from "lucide-react";

import type { TaskGraphDraftV2 } from "./taskGraphDraftV2";
import { TaskGraphContractBindingInspector } from "./TaskGraphContractBindingInspector";
import {
  TaskGraphInspectorSection,
  TaskGraphInspectorSummary,
  TaskGraphObjectSelectField,
} from "./TaskGraphInspectorPrimitives";
import { TaskSystemField, TaskSystemSelectField } from "./TaskSystemWorkbenchUi";

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

export function TaskGraphRootInspector({
  activeGraphNodes,
  addOverlayPortEdge,
  addTimelineBlock,
  agentOptions,
  contractOptions,
  formatAgent,
  formatContract,
  graphDraft,
  graphName,
  interfaceCount,
  nodeTitle,
  portEdgeCount,
  unitsCount,
  graphUnitCount,
  updateTaskGraphDraft,
  updateTaskGraphRuntimePolicy,
}: {
  activeGraphNodes: Array<Record<string, unknown>>;
  addOverlayPortEdge: () => void;
  addTimelineBlock: () => void;
  agentOptions: string[];
  contractOptions: string[];
  formatAgent: (agentId: string) => string;
  formatContract: (contractId: string) => string;
  graphDraft: TaskGraphDraftV2;
  graphName: string;
  graphUnitCount: number;
  interfaceCount: number;
  nodeTitle: (node: Record<string, unknown> | null, fallback?: string) => string;
  portEdgeCount: number;
  unitsCount: number;
  updateTaskGraphDraft: (patch: Partial<TaskGraphDraftV2>) => void;
  updateTaskGraphRuntimePolicy: (patch: Partial<TaskGraphDraftV2["runtime_policy"]>) => void;
}) {
  const nodeOptions = activeGraphNodes.map((node) => stringValue(node.node_id)).filter(Boolean);
  const formatNode = (value: string) => nodeTitle(activeGraphNodes.find((node) => stringValue(node.node_id) === value) ?? null, value);
  void formatContract;
  return (
    <>
      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="任务图" aside={graphDraft.graph_id}>
        <TaskGraphInspectorSummary
          caption="任务图是流程结构；运行时会按节点时序点生成任务动作。"
          metrics={[
            { label: "节点/Unit", value: unitsCount },
            { label: "接口", value: interfaceCount },
            { label: "交接边", value: portEdgeCount },
            { label: "图节点", value: graphUnitCount },
          ]}
          overline="当前任务图"
          title={graphName}
        />
      </TaskGraphInspectorSection>

      <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="任务图配置">
        <div className="boundary-form task-graph-composer-inspector-form">
          <TaskSystemField label="中文名 / 标题" wide>
            <input onChange={(event) => updateTaskGraphDraft({ title: event.target.value })} value={graphDraft.title} />
          </TaskSystemField>
          <TaskGraphObjectSelectField
            formatOption={formatNode}
            label="入口节点"
            onChange={(value) => updateTaskGraphDraft({ entry_node_id: value })}
            options={nodeOptions}
            value={graphDraft.entry_node_id}
          />
          <TaskGraphObjectSelectField
            formatOption={formatNode}
            label="出口节点"
            onChange={(value) => updateTaskGraphDraft({ output_node_id: value })}
            options={nodeOptions}
            value={graphDraft.output_node_id}
          />
          <TaskGraphObjectSelectField
            formatOption={formatAgent}
            label="协调 Agent"
            onChange={(value) => updateTaskGraphRuntimePolicy({ coordinator_agent_id: value })}
            options={agentOptions}
            value={stringValue(graphDraft.runtime_policy.coordinator_agent_id, "agent:0")}
            wide
          />
          <TaskSystemSelectField
            label="协作模式"
            onChange={(value) => updateTaskGraphRuntimePolicy({ coordination_mode: value })}
            options={["review_merge", "pipeline", "parallel_review"]}
            value={stringValue(graphDraft.runtime_policy.coordination_mode, "review_merge")}
          />
        </div>
      </TaskGraphInspectorSection>

      <TaskGraphContractBindingInspector
        contractOptions={contractOptions}
        fieldKeysBySection={{
          schema: ["graph_contract_id"],
          runtime: ["model_requirement.profile_ref", "model_requirement.provider_family", "model_requirement.min_output_tokens", "model_requirement.preferred_output_tokens", "model_requirement.capability_tags"],
          memory: ["memory_read_policy_ref", "dynamic_memory_read_policy_ref", "memory_writeback_policy_ref"],
          handoff: ["wait_policy", "failure_propagation_policy", "result_delivery_policy"],
          acceptance: ["human_gate_policy.mode", "human_gate_policy.blocking", "acceptance_policy_ref"],
          governance: ["thread_ledger_policy_ref", "issue_ledger_policy_ref", "context_boundary_policy_ref"],
        }}
        formatContract={formatContract}
        onChange={(patch) => updateTaskGraphDraft(patch)}
        sections={["schema", "runtime", "memory", "handoff", "acceptance", "governance"]}
        target={graphDraft}
      />

      <TaskGraphInspectorSection icon={<Plus aria-hidden="true" size={15} />} title="结构动作">
        <div className="task-graph-topology-actions task-graph-topology-actions--stacked">
          <button onClick={addTimelineBlock} type="button">
            <Layers3 aria-hidden="true" size={14} />
            <span>新增图节点来源</span>
          </button>
          <button disabled={!unitsCount} onClick={addOverlayPortEdge} type="button">
            <Cable aria-hidden="true" size={14} />
            <span>新增显式端口边</span>
          </button>
        </div>
      </TaskGraphInspectorSection>
    </>
  );
}
