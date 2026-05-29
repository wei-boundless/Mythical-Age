"use client";

import { Save } from "lucide-react";
import { useEffect, useState } from "react";

import { TaskSystemField, TaskSystemSelectField, TaskSystemToolbarButton } from "./TaskSystemWorkbenchUi";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nodeTitle(node: Record<string, unknown>) {
  return String(node.title ?? node.label ?? node.node_id ?? "节点");
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function metadataAfterRolePromptSave(metadata: Record<string, unknown>, prompt: string) {
  const {
    role_identity: roleIdentity,
    responsibility_scope: responsibilityScope,
    responsibility_exclusions: responsibilityExclusions,
    definition_of_done: definitionOfDone,
    ...rest
  } = metadata;
  const consolidatedFieldNames = [
    roleIdentity ? "role_identity" : "",
    responsibilityScope ? "responsibility_scope" : "",
    responsibilityExclusions ? "responsibility_exclusions" : "",
    definitionOfDone ? "definition_of_done" : "",
  ].filter(Boolean);
  return {
    ...rest,
    role_prompt: prompt,
    legacy_prompt_migration: {
      legacy_field_names: consolidatedFieldNames,
      migration_status: consolidatedFieldNames.length ? "role_prompt_consolidated" : "role_prompt_native",
    },
  };
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
  const executorPolicy = asRecord(selectedGraphNode?.executor_policy ?? nodeMetadata.executor_policy);
  const [promptDraft, setPromptDraft] = useState("");

  useEffect(() => {
    if (!selectedGraphNode || !selectedGraphNodeId) {
      setPromptDraft("");
      return;
    }
    const metadata = asRecord(selectedGraphNode.metadata);
    const prompt = String(selectedGraphNode.role_prompt ?? metadata.role_prompt ?? "").trim();
    setPromptDraft(prompt || buildNodeResponsibilityPrompt(metadata));
  }, [selectedGraphNode, selectedGraphNodeId]);

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
  const patchExecutorPolicy = (patch: Record<string, unknown>) => {
    updateTaskGraphNode(selectedGraphNodeId, {
      executor_policy: {
        ...executorPolicy,
        ...patch,
      },
    });
  };

  const legacyMigration = asRecord(nodeMetadata.legacy_prompt_migration);
  const legacyFieldNames = Array.isArray(legacyMigration.legacy_field_names)
    ? legacyMigration.legacy_field_names.map((value) => String(value ?? "").trim()).filter(Boolean)
    : [];
  const rolePrompt = String(selectedGraphNode.role_prompt ?? nodeMetadata.role_prompt ?? "").trim();
  const saveRolePrompt = () => {
    const prompt = promptDraft.trim() || buildNodeResponsibilityPrompt(nodeMetadata);
    updateTaskGraphNode(selectedGraphNodeId, {
      role_prompt: prompt,
      metadata: metadataAfterRolePromptSave(nodeMetadata, prompt),
    });
  };

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
        <p><span>执行器</span><strong>{String(executorPolicy.default_executor ?? "agent")}</strong></p>
        <p><span>角色 Prompt</span><strong>{rolePrompt ? "已配置" : "草稿待保存"}</strong></p>
        <p><span>Legacy Prompt</span><strong>{legacyFieldNames.length > 0 ? "待收口" : "无"}</strong></p>
      </div>

      <div className="boundary-form">
        <TaskSystemSelectField
          label="默认执行器"
          onChange={(value) => patchExecutorPolicy({ default_executor: value, allowed_executors: Array.from(new Set(["agent", value])) })}
          options={uniqueStrings(["agent", "human", "tool", "graph_module", String(executorPolicy.default_executor ?? "")])}
          value={String(executorPolicy.default_executor ?? "agent")}
        />
        <TaskSystemSelectField
          label="运行时切换策略"
          onChange={(value) => patchExecutorPolicy({ override_policy: value })}
          options={["never", "before_dispatch", "on_failure", "cancel_and_reopen"]}
          value={String(executorPolicy.override_policy ?? "before_dispatch")}
        />
        <TaskSystemField label="人工工作单角色">
          <input
            onChange={(event) => patchExecutorPolicy({ human_profile_id: event.target.value })}
            placeholder="人工审核员 / 人工写手 / 人工修订者 / 自定义"
            value={String(executorPolicy.human_profile_id ?? "")}
          />
        </TaskSystemField>
        <TaskSystemField label="人工交互说明">
          <textarea
            onChange={(event) => patchExecutorPolicy({ instruction: event.target.value })}
            placeholder="告诉人类执行者如何使用输入包、如何填写输出字段、提交后会进入哪条边。"
            value={String(executorPolicy.instruction ?? "")}
          />
        </TaskSystemField>
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
        <TaskSystemField label="角色 Prompt">
          <textarea
            onChange={(event) => setPromptDraft(event.target.value)}
            placeholder="你是一名审核员。你只负责...你不负责...你必须输出..."
            value={promptDraft}
          />
        </TaskSystemField>
        <div className="boundary-actions">
          <TaskSystemToolbarButton onClick={saveRolePrompt}>
            <Save size={14} />保存角色 Prompt
          </TaskSystemToolbarButton>
        </div>
        <div className="task-graph-note">
          <strong>Prompt 边界</strong>
          <span>节点职责直接写入任务图节点，运行时按角色 Prompt、输入契约和输出契约装配，不再通过旧身份字段选择职责。</span>
        </div>
      </div>
    </article>
  );
}
