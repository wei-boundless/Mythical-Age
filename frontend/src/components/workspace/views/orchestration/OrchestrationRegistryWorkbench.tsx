"use client";

import { Gauge, Save, Trash2 } from "lucide-react";

import type { SoulProjectionCard, SoulSystemSeed } from "@/lib/api";
import {
  OrchestrationBadge,
  OrchestrationField,
  OrchestrationReadinessCard,
  OrchestrationToolbarButton,
} from "@/components/workspace/views/orchestration/OrchestrationWorkbenchUi";

type AgentCategory = "main_agent" | "system_management_agent" | "worker_sub_agent";

type AgentDraftLike = {
  agent_id: string;
  agent_name: string;
  agent_category?: AgentCategory | string;
  interface_target?: string;
  description?: string;
  enabled?: boolean;
  editable?: boolean;
  default_soul_id?: string;
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

function projectionLabel(value: string, cards: SoulProjectionCard[] = []) {
  const raw = String(value || "").trim();
  if (!raw) return "不使用投影";
  const card = cards.find((item) => item.projection_id === raw);
  if (!card) return raw;
  const owner = card.soul_name || card.soul_id || "灵魂系统";
  return `${card.title || card.projection_id} · ${owner}`;
}

function soulLabel(value: string, seeds: SoulSystemSeed[] = []) {
  const raw = String(value || "").trim();
  if (!raw) return "未选择灵魂";
  const seed = seeds.find((item) => item.key === raw || item.soul_id === raw);
  return seed?.name || seed?.profile?.display_name || raw;
}

function projectionBelongsToSoul(card: SoulProjectionCard, soulId: string) {
  const raw = String(soulId || "").trim();
  if (!raw) return true;
  return card.soul_id === raw || card.soul_name === raw;
}

function ProjectionSelectField({
  cards,
  disabled = false,
  label,
  onChange,
  value,
}: {
  cards: SoulProjectionCard[];
  disabled?: boolean;
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const options = Array.from(new Set(["", value, ...cards.map((item) => item.projection_id).filter(Boolean)]));
  return (
    <OrchestrationField label={label}>
      <select disabled={disabled} value={value || ""} onChange={(event) => onChange(event.target.value)}>
        {options.map((item) => (
          <option key={item || "none"} value={item}>
            {projectionLabel(item, cards)}
          </option>
        ))}
      </select>
    </OrchestrationField>
  );
}

function SoulSelectField({
  disabled = false,
  onChange,
  seeds,
  value,
}: {
  disabled?: boolean;
  onChange: (value: string) => void;
  seeds: SoulSystemSeed[];
  value: string;
}) {
  const options = Array.from(new Set(["", value, ...seeds.map((item) => item.soul_id || item.key).filter(Boolean)]));
  return (
    <OrchestrationField label="选择灵魂">
      <select disabled={disabled} value={value || ""} onChange={(event) => onChange(event.target.value)}>
        {options.map((item) => (
          <option key={item || "none"} value={item}>
            {soulLabel(item, seeds)}
          </option>
        ))}
      </select>
    </OrchestrationField>
  );
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
  projectionCards,
  soulSeeds,
  legacySystemKey,
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
  projectionCards: SoulProjectionCard[];
  soulSeeds: SoulSystemSeed[];
  legacySystemKey: string;
}) {
  const selectedSoulProjectionCards = projectionCards.filter((card) => projectionBelongsToSoul(card, agentDraft.default_soul_id || ""));

  return (
    <>
      <section className="boundary-layer-grid boundary-layer-grid--wide">
        <div className="boundary-card boundary-card--summary">
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
            <OrchestrationReadinessCard label="权限冲突" ready={!overlapOps.length} value={overlapOps.length ? String(overlapOps.length) : "0"} />
          </div>
        </div>
        <aside className="boundary-card">
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
        </aside>
      </section>

      <section className="boundary-card">
        <header>
          <strong>Agent 属性</strong>
          <OrchestrationBadge>{agentMode === "new" ? "草稿" : text(selectedAgentBuiltin ? "内置" : "自定义")}</OrchestrationBadge>
        </header>
        <div className="orchestration-identity-note">
          <span>这里定义 Agent 身份本体。</span>
          <strong>{selectedAgentBuiltin ? "这是系统预置来源的 Agent，默认会对接既定会话口；除此之外按普通 Agent 管理。" : "子 Agent 可自由定义名称、入口、选择灵魂/投影和职责说明。"}</strong>
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
          <SoulSelectField
            onChange={(value) => {
              const currentProjection = projectionCards.find((card) => card.projection_id === agentDraft.default_projection_id);
              patchAgentDraft({
                default_soul_id: value,
                default_projection_id: currentProjection && projectionBelongsToSoul(currentProjection, value) ? agentDraft.default_projection_id : "",
              });
            }}
            seeds={soulSeeds}
            value={agentDraft.default_soul_id || ""}
          />
          <ProjectionSelectField
            cards={selectedSoulProjectionCards}
            disabled={!agentDraft.default_soul_id}
            label="选择投影"
            onChange={(value) => {
              patchAgentDraft({ default_projection_id: value });
            }}
            value={agentDraft.default_projection_id || ""}
          />
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
        {legacySystemKey ? <div className="boundary-legacy">legacy system_key：{legacySystemKey}</div> : null}
      </section>
    </>
  );
}
