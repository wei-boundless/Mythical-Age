"use client";

import { Gauge, Save, Trash2 } from "lucide-react";

import {
  OrchestrationBadge,
  OrchestrationField,
  OrchestrationReadinessCard,
  OrchestrationToolbarButton,
} from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";
import { Panel } from "@/ui/Panel";

type AgentCategory = "main_agent" | "builtin_agent" | "custom_agent";

type AgentDraftLike = {
  agent_id: string;
  agent_name: string;
  agent_category?: AgentCategory | string;
  interface_target?: string;
  description?: string;
  enabled?: boolean;
  editable?: boolean;
  default_projection_id?: string;
};

type RuntimeDraftLike = {
  agent_profile_id: string;
};

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  return String(value);
}

export function OrchestrationRegistryWorkbench({
  agentDraft,
  patchAgentDraft,
  agentMode,
  selectedAgentBuiltin,
  runtimeDraft,
  profileMissing,
  overlapOps,
  categoryLabels,
  saving,
  saveAgent,
  saveRuntimeProfile,
  removeAgent,
  runtimeSaveBlocked,
  agentDeleteBlocked,
}: {
  agentDraft: AgentDraftLike;
  patchAgentDraft: (patch: Partial<AgentDraftLike>) => void;
  agentMode: "existing" | "new";
  selectedAgentBuiltin: boolean;
  runtimeDraft: RuntimeDraftLike;
  profileMissing: boolean;
  overlapOps: string[];
  categoryLabels: Record<AgentCategory, string>;
  saving: "" | "agent" | "runtime" | "group" | "create" | "delete";
  saveAgent: () => Promise<void>;
  saveRuntimeProfile: () => Promise<void>;
  removeAgent: () => Promise<void>;
  runtimeSaveBlocked: boolean;
  agentDeleteBlocked: boolean;
}) {
  return (
    <>
      <section className="boundary-layer-grid boundary-layer-grid--wide">
        <Panel as="div" variant="summary">
          <header>
            <strong>{agentDraft.agent_name || agentDraft.agent_id || "新 Agent 草稿"}</strong>
            <OrchestrationBadge tone={agentDraft.enabled ? "ok" : "warn"}>{agentDraft.enabled ? "启用" : "停用"}</OrchestrationBadge>
          </header>
          <div className="boundary-metric-grid">
            <OrchestrationReadinessCard
              label="类别"
              ready={Boolean(agentDraft.agent_category)}
              value={categoryLabels[agentDraft.agent_category as AgentCategory] ?? "未配置"}
            />
            <OrchestrationReadinessCard label="运行" ready={!profileMissing && Boolean(runtimeDraft.agent_profile_id)} value={runtimeDraft.agent_profile_id || "未配置"} />
            <OrchestrationReadinessCard label="准入冲突" ready={!overlapOps.length} value={overlapOps.length ? String(overlapOps.length) : "0"} />
          </div>
        </Panel>
        <Panel as="aside">
          <header><strong>保存</strong></header>
          <div className="boundary-actions boundary-actions--stack">
            <OrchestrationToolbarButton disabled={saving === "agent"} onClick={() => void saveAgent()} variant="primary">
              <Save size={15} />
              保存 Agent 名册
            </OrchestrationToolbarButton>
            <OrchestrationToolbarButton disabled={saving === "runtime" || runtimeSaveBlocked} onClick={() => void saveRuntimeProfile()} variant="primary">
              <Gauge size={15} />
              保存运行档案
            </OrchestrationToolbarButton>
            <OrchestrationToolbarButton
              disabled={
                saving === "delete" ||
                agentDeleteBlocked ||
                agentMode === "new"
              }
              onClick={() => void removeAgent()}
              variant="danger"
            >
              <Trash2 size={15} />
              删除 Agent
            </OrchestrationToolbarButton>
          </div>
        </Panel>
      </section>

      <Panel>
        <header>
          <strong>Agent 属性</strong>
          <OrchestrationBadge>{agentMode === "new" ? "草稿" : text(selectedAgentBuiltin ? "内置" : "自定义")}</OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>这里定义 Agent 身份本体。</span>
          <strong>{selectedAgentBuiltin ? "这是系统预置来源的 Agent，默认会对接既定会话口；除此之外按普通 Agent 管理。" : "子 Agent 可定义名称、入口、投影和职责说明。"}</strong>
        </div>
        <div className="boundary-form">
          <OrchestrationField label="Agent 标识">
            <input readOnly value={agentDraft.agent_id} />
          </OrchestrationField>
          <OrchestrationField label="名称">
            <input value={agentDraft.agent_name} onChange={(event) => patchAgentDraft({ agent_name: event.target.value })} />
          </OrchestrationField>
          <OrchestrationField label="类别">
            <input readOnly value={categoryLabels[agentDraft.agent_category as AgentCategory] ?? text(agentDraft.agent_category, "未配置")} />
          </OrchestrationField>
          <OrchestrationField label="入口位置">
            <input
              value={agentDraft.interface_target || ""}
              onChange={(event) => patchAgentDraft({ interface_target: event.target.value })}
            />
          </OrchestrationField>
          <OrchestrationField label="默认投影">
            <input
              value={agentDraft.default_projection_id || ""}
              onChange={(event) => patchAgentDraft({ default_projection_id: event.target.value })}
            />
          </OrchestrationField>
          <OrchestrationField label="职责说明" wide>
            <textarea
              value={agentDraft.description || ""}
              onChange={(event) => patchAgentDraft({ description: event.target.value })}
            />
          </OrchestrationField>
          <label className="boundary-check">
            <input
              checked={Boolean(agentDraft.enabled)}
              onChange={(event) => patchAgentDraft({ enabled: event.target.checked })}
              type="checkbox"
            />
            启用 Agent
          </label>
          <label className="boundary-check">
            <input
              checked={Boolean(agentDraft.editable)}
              onChange={(event) => patchAgentDraft({ editable: event.target.checked })}
              type="checkbox"
            />
            允许编辑
          </label>
        </div>
      </Panel>
    </>
  );
}
