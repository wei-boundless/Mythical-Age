"use client";

import { Wand2 } from "lucide-react";

import { TaskSystemField, TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

export function buildNodeResponsibilityPrompt(metadata: Record<string, unknown>) {
  const roleIdentity = String(metadata.role_identity ?? "").trim();
  const responsibilityScope = String(metadata.responsibility_scope ?? "").trim();
  const responsibilityExclusions = String(metadata.responsibility_exclusions ?? "").trim();
  const definitionOfDone = String(metadata.definition_of_done ?? "").trim();
  return [
    roleIdentity || "你是一名任务协作者。",
    responsibilityScope ? `你只负责${responsibilityScope.replace(/^你只负责/, "")}` : "你只负责完成当前节点明确交付给你的职责。",
    responsibilityExclusions ? `你不负责${responsibilityExclusions.replace(/^你不负责/, "")}` : "你不负责扩展未经确认的任务范围。",
    definitionOfDone ? `你必须${definitionOfDone.replace(/^你必须/, "")}` : "你必须输出清晰结论、依据、遗留问题和下一步建议。",
  ].join("\n");
}

export function NodeResponsibilityCard({
  selectedGraphNode,
  selectedGraphNodeId,
  updateTaskGraphNode,
}: {
  selectedGraphNode: Record<string, unknown> | null;
  selectedGraphNodeId: string;
  updateTaskGraphNode: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const nodeMetadata = asRecord(selectedGraphNode?.metadata);

  if (!selectedGraphNode || !selectedGraphNodeId) {
    return (
      <article className="boundary-card">
        <header><strong>节点职责</strong></header>
        <div className="task-graph-note">
          <strong>未选择节点</strong>
          <span>请在拓扑页选择一个节点，再回到本页配置职责说明。</span>
        </div>
      </article>
    );
  }

  const patchMetadata = (patch: Record<string, unknown>) => {
    updateTaskGraphNode(selectedGraphNodeId, {
      metadata: {
        ...nodeMetadata,
        ...patch,
      },
    });
  };

  const promptPreview = String(nodeMetadata.role_prompt ?? "");

  return (
    <article className="boundary-card task-graph-responsibility-card">
      <header>
        <div className="boundary-identity-stack">
          <span>节点职责</span>
          <strong>{nodeTitle(selectedGraphNode)}</strong>
        </div>
        <small>{selectedGraphNodeId}</small>
      </header>

      <div className="task-graph-responsibility-preview">
        <p><span>角色</span><strong>{String(selectedGraphNode.role ?? selectedGraphNode.work_posture ?? "participant")}</strong></p>
        <p><span>Agent</span><strong>{String(selectedGraphNode.agent_id ?? "未绑定")}</strong></p>
        <p><span>Prompt</span><strong>{promptPreview ? "已配置" : "未配置"}</strong></p>
      </div>

      <div className="boundary-form">
        <TaskSystemField label="你是谁（角色身份）">
          <input
            onChange={(event) => patchMetadata({ role_identity: event.target.value })}
            placeholder="你是一名世界观审核员。"
            value={String(nodeMetadata.role_identity ?? "")}
          />
        </TaskSystemField>
        <TaskSystemField label="只负责什么">
          <textarea
            onChange={(event) => patchMetadata({ responsibility_scope: event.target.value })}
            placeholder="评审设定完整性、一致性、可执行性。"
            value={String(nodeMetadata.responsibility_scope ?? "")}
          />
        </TaskSystemField>
        <TaskSystemField label="不负责什么">
          <textarea
            onChange={(event) => patchMetadata({ responsibility_exclusions: event.target.value })}
            placeholder="扩写剧情，不替作者创作。"
            value={String(nodeMetadata.responsibility_exclusions ?? "")}
          />
        </TaskSystemField>
        <TaskSystemField label="完成标准">
          <textarea
            onChange={(event) => patchMetadata({ definition_of_done: event.target.value })}
            placeholder="明确列出问题、给出通过/驳回裁决，并说明下一步建议。"
            value={String(nodeMetadata.definition_of_done ?? "")}
          />
        </TaskSystemField>
        <div className="boundary-actions">
          <TaskSystemToolbarButton onClick={() => patchMetadata({ role_prompt: buildNodeResponsibilityPrompt(nodeMetadata) })}>
            <Wand2 size={14} />生成职责 Prompt
          </TaskSystemToolbarButton>
        </div>
        <TaskSystemField label="节点 Prompt 预览">
          <textarea
            onChange={(event) => patchMetadata({ role_prompt: event.target.value })}
            placeholder="你是一名审核员。你只负责...你不负责...你必须输出..."
            value={promptPreview}
          />
        </TaskSystemField>
      </div>
    </article>
  );
}
