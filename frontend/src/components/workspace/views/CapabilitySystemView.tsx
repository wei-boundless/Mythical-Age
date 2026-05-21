"use client";

import {
  AlertTriangle,
  Boxes,
  Code2,
  FilePlus2,
  Loader2,
  PlugZap,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wrench
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  createCapabilitySystemSkill,
  deleteCapabilitySystemSkill,
  getCapabilitySystemCatalog,
  refreshCapabilitySystemCatalog,
  saveCapabilitySystemSkill,
  updateCapabilitySystemSkillPromptView,
  updateCapabilitySystemTool,
  type CapabilityUnit,
  type CapabilityEndpoint,
  type CapabilitySystemCatalog,
  type OperationSkill,
  type OperationTool
} from "@/lib/api";

type OperationPanel = "units" | "skills" | "tools" | "endpoints";
type CapabilitySystemViewProps = {
  initialPanel?: OperationPanel;
};

const TOOL_VISIBILITY_LABELS: Record<string, string> = {
  main_runtime: "主运行时",
  agent_internal: "智能体内部"
};

const PROMPT_EXPOSURE_LABELS: Record<string, string> = {
  schema_only: "只暴露调用结构",
  hidden: "不暴露给模型"
};

const RISK_CLASS: Record<string, string> = {
  低: "operation-risk--low",
  中: "operation-risk--medium",
  高: "operation-risk--high",
  极高: "operation-risk--critical"
};

function listText(value: string[]) {
  return value.length ? value.join(" / ") : "未配置";
}

function jsonText(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function defaultSkillDraft(name: string, title: string, description: string) {
  return `---
name: ${name || "new-skill"}
description: ${description || "描述这个 skill 的用途。"}
metadata:
  display_name: ${title || "新 Skill"}
  supported_modalities:
    - text
  supported_task_kinds: []
  supported_source_kinds: []
  capability_tags: []
  preferred_route: capability_authoring
  requires_operations:
    - op.read_file
    - op.write_file
    - op.edit_file
  requires_capabilities:
    - tool:read_file
    - tool:write_file
    - tool:edit_file
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
---

# ${title || "新 Skill"}

${description || "描述这个 skill 如何帮助智能体完成任务。"}

## 适用场景

- 在这里写清楚模型什么时候应该使用这个 skill。

## 执行准则

- 如果这个 skill 需要工具、MCP 或文件能力，先声明 \`requires_operations\` 和 \`requires_capabilities\`，不要假设权限会自动扩大。
- 直接完成用户任务，不暴露内部路由、工具协议或调度细节。
`;
}

function skillSearchText(skill: OperationSkill) {
  return [
    skill.runtime.name,
    skill.runtime.title,
    skill.runtime.description,
    skill.runtime.capability_tags.join(" "),
    skill.runtime.supported_task_kinds.join(" "),
    skill.runtime.supported_source_kinds.join(" "),
    skill.runtime.routing_hints.join(" "),
    skill.prompt_block
  ].join(" ").toLowerCase();
}

function toolSearchText(tool: OperationTool) {
  return [
    tool.name,
    tool.display_name,
    tool.operation_metadata.llm_description,
    tool.module,
    tool.operation_metadata.tool_type,
    tool.operation_metadata.tool_boundary,
    tool.operation_metadata.adapter_type,
    tool.operation_metadata.risk_level,
    tool.operation_metadata.ownership_label,
    tool.capability_tags.join(" "),
    tool.safety_tags.join(" "),
    tool.route_hints.join(" ")
  ].join(" ").toLowerCase();
}

function endpointSearchText(endpoint: CapabilityEndpoint) {
  return [
    endpoint.endpoint_id,
    endpoint.kind,
    endpoint.name,
    endpoint.title,
    endpoint.description,
    endpoint.operation_id,
    endpoint.protocol_family,
    endpoint.server_name,
    endpoint.transport,
    endpoint.runtime_lane,
    endpoint.invocation_mode,
    endpoint.model_visibility,
    endpoint.tags.join(" ")
  ].join(" ").toLowerCase();
}

function unitSearchText(unit: CapabilityUnit) {
  return [
    unit.capability_id,
    unit.kind,
    unit.title,
    unit.summary,
    unit.provider,
    unit.provider_kind,
    unit.transport,
    unit.runtime_visibility,
    unit.model_visibility,
    unit.status,
    unit.operation_ids.join(" "),
    unit.risk.join(" "),
    unit.source_ref
  ].join(" ").toLowerCase();
}

function compactList(value: string[], fallback = "未配置") {
  return value.length ? value.join(" / ") : fallback;
}

function toolDisplayName(tool: OperationTool) {
  return tool.display_name || tool.name;
}

function unitTone(unit: CapabilityUnit) {
  if (unit.status === "unsupported" || unit.status === "failed" || unit.health?.status === "failed") {
    return "operation-unit-card--blocked";
  }
  if (unit.permission_view?.approval_state === "pending" || unit.risk.some((item) => item.includes("write") || item.includes("execution"))) {
    return "operation-unit-card--attention";
  }
  return "";
}

export function CapabilitySystemView({ initialPanel = "units" }: CapabilitySystemViewProps = {}) {
  const [catalog, setCatalog] = useState<CapabilitySystemCatalog | null>(null);
  const [activePanel, setActivePanel] = useState<OperationPanel>(initialPanel);
  const [selectedUnitId, setSelectedUnitId] = useState("");
  const [selectedSkillName, setSelectedSkillName] = useState("");
  const [selectedToolName, setSelectedToolName] = useState("");
  const [selectedEndpointId, setSelectedEndpointId] = useState("");
  const [skillDraft, setSkillDraft] = useState("");
  const [promptDraft, setPromptDraft] = useState({ title: "", capability: "", use_when: "", output_rule: "" });
  const [promptEditing, setPromptEditing] = useState(false);
  const [toolNoteDraft, setToolNoteDraft] = useState("");
  const [toolLlmDescriptionDraft, setToolLlmDescriptionDraft] = useState("");
  const [skillEditing, setSkillEditing] = useState(false);
  const [query, setQuery] = useState("");
  const [toolBoundaryFilter, setToolBoundaryFilter] = useState("全部边界");
  const [toolRiskFilter, setToolRiskFilter] = useState("全部风险");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [newSkill, setNewSkill] = useState({ name: "", title: "", description: "" });

  useEffect(() => {
    setActivePanel(initialPanel);
  }, [initialPanel]);

  async function loadCatalog(refresh = false) {
    setLoading(true);
    setError("");
    try {
      const payload = refresh ? await refreshCapabilitySystemCatalog() : await getCapabilitySystemCatalog();
      setCatalog(payload);
      setSelectedUnitId((current) => (payload.capability_units ?? []).some((unit) => unit.capability_id === current) ? current : payload.capability_units?.[0]?.capability_id ?? "");
      setSelectedSkillName((current) => payload.skills.some((skill) => skill.runtime.name === current) ? current : payload.skills[0]?.runtime.name ?? "");
      setSelectedToolName((current) => payload.tools.some((tool) => tool.name === current) ? current : payload.tools[0]?.name ?? "");
      setSelectedEndpointId((current) => (payload.capability_endpoints ?? []).some((endpoint) => endpoint.endpoint_id === current) ? current : payload.capability_endpoints?.[0]?.endpoint_id ?? "");
      if (refresh) {
        setNotice("能力系统目录已刷新。");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载能力系统失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
  }, []);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleSkills = useMemo(
    () => (catalog?.skills ?? []).filter((skill) => !normalizedQuery || skillSearchText(skill).includes(normalizedQuery)),
    [catalog?.skills, normalizedQuery]
  );
  const visibleUnits = useMemo(
    () => (catalog?.capability_units ?? []).filter((unit) => !normalizedQuery || unitSearchText(unit).includes(normalizedQuery)),
    [catalog?.capability_units, normalizedQuery]
  );
  const toolBoundaryOptions = useMemo(
    () => ["全部边界", ...Object.keys(catalog?.summary.tool_boundaries ?? {})],
    [catalog?.summary.tool_boundaries]
  );
  const toolRiskOptions = useMemo(
    () => ["全部风险", ...Object.keys(catalog?.summary.tool_risks ?? {})],
    [catalog?.summary.tool_risks]
  );
  const visibleTools = useMemo(
    () => (catalog?.tools ?? []).filter((tool) => {
      const matchesQuery = !normalizedQuery || toolSearchText(tool).includes(normalizedQuery);
      const matchesBoundary = toolBoundaryFilter === "全部边界" || tool.operation_metadata.tool_boundary === toolBoundaryFilter;
      const matchesRisk = toolRiskFilter === "全部风险" || tool.operation_metadata.risk_level === toolRiskFilter;
      return matchesQuery && matchesBoundary && matchesRisk;
    }),
    [catalog?.tools, normalizedQuery, toolBoundaryFilter, toolRiskFilter]
  );
  const visibleEndpoints = useMemo(
    () => (catalog?.capability_endpoints ?? []).filter((endpoint) => !normalizedQuery || endpointSearchText(endpoint).includes(normalizedQuery)),
    [catalog?.capability_endpoints, normalizedQuery]
  );
  const selectedSkill = (catalog?.skills ?? []).find((skill) => skill.runtime.name === selectedSkillName) ?? visibleSkills[0] ?? null;
  const selectedUnit = (catalog?.capability_units ?? []).find((unit) => unit.capability_id === selectedUnitId) ?? visibleUnits[0] ?? null;
  const selectedTool = (catalog?.tools ?? []).find((tool) => tool.name === selectedToolName) ?? visibleTools[0] ?? null;
  const selectedEndpoint = (catalog?.capability_endpoints ?? []).find((endpoint) => endpoint.endpoint_id === selectedEndpointId) ?? visibleEndpoints[0] ?? null;

  useEffect(() => {
    if (!selectedSkill || skillEditing) {
      return;
    }
    setSkillDraft(selectedSkill.content);
  }, [selectedSkill, skillEditing]);

  useEffect(() => {
    if (!selectedSkill || promptEditing) {
      return;
    }
    setPromptDraft({
      title: selectedSkill.prompt_view.title || "",
      capability: selectedSkill.prompt_view.capability || "",
      use_when: selectedSkill.prompt_view.use_when || "",
      output_rule: selectedSkill.prompt_view.output_rule || ""
    });
  }, [selectedSkill, promptEditing]);

  useEffect(() => {
    setToolNoteDraft(selectedTool?.operation_metadata.note ?? "");
    setToolLlmDescriptionDraft(selectedTool?.operation_metadata.llm_description ?? "");
  }, [selectedTool?.name, selectedTool?.operation_metadata.llm_description, selectedTool?.operation_metadata.note]);

  async function saveSkill() {
    if (!selectedSkill) {
      return;
    }
    setSaving(`skill:${selectedSkill.runtime.name}`);
    setError("");
    try {
      const payload = await saveCapabilitySystemSkill(selectedSkill.runtime.name, skillDraft);
      setCatalog(payload);
      setSkillEditing(false);
      setNotice(`${selectedSkill.runtime.title || selectedSkill.runtime.name} 已保存，模型可见提示已重新生成。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存 skill 失败");
    } finally {
      setSaving("");
    }
  }

  async function createSkill() {
    if (!newSkill.name.trim() || !newSkill.title.trim() || !newSkill.description.trim()) {
      setError("请填写 skill 名称、标题和描述。");
      return;
    }
    setSaving("create-skill");
    setError("");
    try {
      const payload = await createCapabilitySystemSkill({
        ...newSkill,
        content: defaultSkillDraft(newSkill.name.trim(), newSkill.title.trim(), newSkill.description.trim())
      });
      setCatalog(payload);
      setSelectedSkillName(newSkill.name.trim());
      setNewSkill({ name: "", title: "", description: "" });
      setSkillEditing(true);
      setNotice("新 skill 已创建，可以继续编辑完整提示。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "新建 skill 失败");
    } finally {
      setSaving("");
    }
  }

  async function removeSkill(skill: OperationSkill) {
    const ok = window.confirm(`确定删除「${skill.runtime.title || skill.runtime.name}」吗？这会删除对应 skill 目录。`);
    if (!ok) {
      return;
    }
    setSaving(`delete:${skill.runtime.name}`);
    setError("");
    try {
      const payload = await deleteCapabilitySystemSkill(skill.runtime.name);
      setCatalog(payload);
      setSelectedSkillName(payload.skills[0]?.runtime.name ?? "");
      setSkillEditing(false);
      setNotice("skill 已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除 skill 失败");
    } finally {
      setSaving("");
    }
  }

  async function changeToolType(tool: OperationTool, toolType: string) {
    setSaving(`tool:${tool.name}`);
    setError("");
    try {
      const payload = await updateCapabilitySystemTool(tool.name, {
        tool_type: toolType,
        note: tool.operation_metadata.note,
        llm_description: tool.operation_metadata.llm_description
      });
      setCatalog(payload);
      setNotice(`${tool.name} 已归入「${toolType}」。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存工具类型失败");
    } finally {
      setSaving("");
    }
  }

  async function saveSkillPromptView() {
    if (!selectedSkill) {
      return;
    }
    setSaving(`prompt:${selectedSkill.runtime.name}`);
    setError("");
    try {
      const payload = await updateCapabilitySystemSkillPromptView(selectedSkill.runtime.name, promptDraft);
      setCatalog(payload);
      setPromptEditing(false);
      setNotice(`${selectedSkill.runtime.title || selectedSkill.runtime.name} 的模型可见 Prompt 已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存模型可见 Prompt 失败");
    } finally {
      setSaving("");
    }
  }

  async function saveToolNote(tool: OperationTool) {
    setSaving(`tool-note:${tool.name}`);
    setError("");
    try {
      const payload = await updateCapabilitySystemTool(tool.name, {
        tool_type: tool.operation_metadata.tool_type,
        note: toolNoteDraft,
        llm_description: toolLlmDescriptionDraft
      });
      setCatalog(payload);
      setNotice(`${tool.name} 的治理备注已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存工具备注失败");
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="workspace-view capability-system-console">
      <header className="workspace-view__header">
        <div>
          <h2 className="workspace-view__title">能力系统</h2>
          <p className="workspace-view__subtitle">以能力单元为入口查看执行状态、operation、依赖、权限和来源。</p>
        </div>
        <div className="workspace-view__actions">
          <button className="action-button action-button--ghost" onClick={() => void loadCatalog(true)} type="button">
          {loading ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
            刷新目录
          </button>
        </div>
      </header>

      {error ? <div className="workspace-alert workspace-alert--danger">{error}</div> : null}
      {notice ? <div className="workspace-alert">{notice}</div> : null}

      <nav className="operation-switcher" aria-label="能力系统模块">
        {[
          { id: "units", label: "能力单元", icon: Boxes },
          { id: "skills", label: "Skills", icon: Boxes },
          { id: "tools", label: "工具", icon: Wrench },
          { id: "endpoints", label: "端点", icon: PlugZap }
        ].map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={activePanel === item.id ? "operation-switcher__item operation-switcher__item--active" : "operation-switcher__item"}
              key={item.id}
              onClick={() => setActivePanel(item.id as OperationPanel)}
              type="button"
            >
              <Icon size={16} />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="workspace-search">
        <Search size={17} />
        <input
          onChange={(event) => setQuery(event.target.value)}
          placeholder={activePanel === "units" ? "搜索能力单元 / operation / provider" : activePanel === "skills" ? "搜索 skill" : activePanel === "tools" ? "搜索工具" : "搜索端点"}
          value={query}
        />
      </div>

      {activePanel === "units" ? (
        <section className="operation-layout operation-layout--units">
          <div className="operation-list">
            {visibleUnits.map((unit) => (
              <button
                className={`operation-unit-card ${selectedUnit?.capability_id === unit.capability_id ? "operation-unit-card--active" : ""} ${unitTone(unit)}`}
                key={unit.capability_id}
                onClick={() => setSelectedUnitId(unit.capability_id)}
                type="button"
              >
                <span>{unit.kind} · {unit.provider_kind}</span>
                <strong>{unit.title || unit.capability_id}</strong>
                <p>{unit.operation_ids.join(" / ") || "未声明 operation"}</p>
              </button>
            ))}
          </div>

          <article className="operation-detail operation-detail--plain">
            {selectedUnit ? (
              <>
                <div className="operation-detail__head">
                  <div>
                    <span>{selectedUnit.kind} · {selectedUnit.capability_id}</span>
                    <h3>{selectedUnit.title || selectedUnit.capability_id}</h3>
                    <p>{selectedUnit.summary || "暂无说明"}</p>
                  </div>
                  <div className={`operation-risk-badge ${selectedUnit.status === "active" ? "operation-risk--low" : "operation-risk--medium"}`}>
                    <ShieldCheck size={16} />
                    {selectedUnit.status || "unknown"}
                  </div>
                </div>

                <div className="operation-unit-facts">
                  <article>
                    <span>Operations</span>
                    <strong>{selectedUnit.operation_ids.join(" / ") || "未声明"}</strong>
                  </article>
                  <article>
                    <span>Provider</span>
                    <strong>{selectedUnit.provider}</strong>
                  </article>
                  <article>
                    <span>Visibility</span>
                    <strong>{selectedUnit.model_visibility || selectedUnit.runtime_visibility || "未配置"}</strong>
                  </article>
                  <article>
                    <span>Health</span>
                    <strong>{selectedUnit.health?.reason || selectedUnit.health?.status || "active"}</strong>
                  </article>
                </div>

                <div className="operation-permission-strip">
                  <article><span>Profile</span><strong>{selectedUnit.permission_view?.profile_state ?? "unknown"}</strong></article>
                  <article><span>Turn</span><strong>{selectedUnit.permission_view?.adoption_state ?? "not_checked"}</strong></article>
                  <article><span>Gate</span><strong>{selectedUnit.permission_view?.gate_state ?? "not_checked"}</strong></article>
                  <article><span>Approval</span><strong>{selectedUnit.permission_view?.approval_state ?? "not_required"}</strong></article>
                </div>

                <div className="operation-tool-linked">
                  <article>
                    <strong>依赖</strong>
                    {selectedUnit.dependencies.length ? (
                      <div className="workspace-chip-row">
                        {selectedUnit.dependencies.map((dependency) => (
                          <span className="workspace-mini-chip" key={`${dependency.relation}:${dependency.to_id}`}>{dependency.relation}: {dependency.to_id}</span>
                        ))}
                      </div>
                    ) : <p>没有声明依赖。</p>}
                  </article>
                  <article>
                    <strong>风险标签</strong>
                    <p>{selectedUnit.risk.join(" / ") || "未标注"}</p>
                  </article>
                  <article>
                    <strong>源码来源</strong>
                    <p>{selectedUnit.source_ref || "未配置"}</p>
                  </article>
                </div>

                <div className="operation-contract-grid">
                  <article>
                    <strong>权限视图</strong>
                    <pre>{jsonText(selectedUnit.permission_view)}</pre>
                  </article>
                  <article>
                    <strong>健康诊断</strong>
                    <pre>{jsonText(selectedUnit.health)}</pre>
                  </article>
                  <article>
                    <strong>展示标签</strong>
                    <pre>{jsonText(selectedUnit.display_facets)}</pre>
                  </article>
                </div>
              </>
            ) : (
              <div className="workspace-alert">暂无能力单元。</div>
            )}
          </article>
        </section>
      ) : activePanel === "skills" ? (
        <section className="operation-layout">
          <div className="operation-list">
            <article className="operation-create-card">
              <div>
                <FilePlus2 size={18} />
                <strong>新建 Skill</strong>
              </div>
              <input placeholder="name，例如 pdf-qa" value={newSkill.name} onChange={(event) => setNewSkill((prev) => ({ ...prev, name: event.target.value }))} />
              <input placeholder="中文标题" value={newSkill.title} onChange={(event) => setNewSkill((prev) => ({ ...prev, title: event.target.value }))} />
              <textarea placeholder="一句话描述能力用途" value={newSkill.description} onChange={(event) => setNewSkill((prev) => ({ ...prev, description: event.target.value }))} />
              <button className="action-button action-button--primary" disabled={saving === "create-skill"} onClick={() => void createSkill()} type="button">
                {saving === "create-skill" ? <Loader2 className="animate-spin" size={14} /> : <FilePlus2 size={14} />}
                创建
              </button>
            </article>
            {visibleSkills.map((skill) => (
              <button
                className={selectedSkill?.runtime.name === skill.runtime.name ? "operation-skill-card operation-skill-card--active" : "operation-skill-card"}
                key={skill.runtime.name}
                onClick={() => {
                  setSelectedSkillName(skill.runtime.name);
                  setSkillEditing(false);
                }}
                type="button"
              >
                <strong>{skill.runtime.title || skill.runtime.name}</strong>
              </button>
            ))}
          </div>

          <article className="operation-detail">
            {selectedSkill ? (
              <>
                <div className="operation-detail__head">
                  <div>
                    <span>Skill</span>
                    <h3>{selectedSkill.runtime.title || selectedSkill.runtime.name}</h3>
                    <p>{selectedSkill.runtime.description}</p>
                  </div>
                  <div className="operation-detail__actions">
                    <button className="action-button action-button--ghost" onClick={() => setSkillEditing((value) => !value)} type="button">
                      <Code2 size={14} />
                      {skillEditing ? "退出编辑" : "编辑"}
                    </button>
                    {skillEditing ? (
                      <button className="action-button action-button--primary" disabled={saving === `skill:${selectedSkill.runtime.name}`} onClick={() => void saveSkill()} type="button">
                        {saving === `skill:${selectedSkill.runtime.name}` ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                        保存
                      </button>
                    ) : null}
                    <button className="action-button action-button--danger" disabled={saving === `delete:${selectedSkill.runtime.name}`} onClick={() => void removeSkill(selectedSkill)} type="button">
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                </div>

                <div className="operation-skill-meta">
                  <span>路径：{selectedSkill.runtime.path}</span>
                  <span>路由：{selectedSkill.runtime.preferred_route || "未配置"}</span>
                  <span>任务：{compactList(selectedSkill.runtime.supported_task_kinds)}</span>
                  <span>来源：{compactList(selectedSkill.runtime.supported_source_kinds)}</span>
                </div>

                {selectedSkill.validation_errors.length ? (
                  <div className="workspace-alert workspace-alert--danger">
                    统一契约校验未通过：{selectedSkill.validation_errors.join(" / ")}
                  </div>
                ) : null}

                <div className="operation-prompt-panel">
                  <div>
                    <Sparkles size={16} />
                    <strong>模型提示</strong>
                    <button className="action-button action-button--ghost" onClick={() => setPromptEditing((value) => !value)} type="button">
                      <Code2 size={14} />
                      {promptEditing ? "预览" : "编辑"}
                    </button>
                    {promptEditing ? (
                      <button
                        className="action-button action-button--primary"
                        disabled={saving === `prompt:${selectedSkill.runtime.name}`}
                        onClick={() => void saveSkillPromptView()}
                        type="button"
                      >
                        {saving === `prompt:${selectedSkill.runtime.name}` ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                        保存 Prompt
                      </button>
                    ) : null}
                  </div>
                  {promptEditing ? (
                    <div className="operation-prompt-editor">
                      <label>
                        标题
                        <input value={promptDraft.title} onChange={(event) => setPromptDraft((prev) => ({ ...prev, title: event.target.value }))} />
                      </label>
                      <label>
                        能力说明
                        <textarea value={promptDraft.capability} onChange={(event) => setPromptDraft((prev) => ({ ...prev, capability: event.target.value }))} />
                      </label>
                      <label>
                        使用条件
                        <textarea value={promptDraft.use_when} onChange={(event) => setPromptDraft((prev) => ({ ...prev, use_when: event.target.value }))} />
                      </label>
                      <label>
                        输出规则
                        <textarea value={promptDraft.output_rule} onChange={(event) => setPromptDraft((prev) => ({ ...prev, output_rule: event.target.value }))} />
                      </label>
                    </div>
                  ) : (
                    <pre>{selectedSkill.prompt_block || "这个 skill 暂无模型可见提示。"}</pre>
                  )}
                </div>

                <div className="operation-editor-panel">
                  <div>
                    <Code2 size={16} />
                    <strong>SKILL.md</strong>
                    {!skillEditing ? (
                      <button className="action-button action-button--ghost" onClick={() => setSkillEditing(true)} type="button">
                        <Code2 size={14} />
                        编辑
                      </button>
                    ) : null}
                    {skillEditing ? (
                      <button className="action-button action-button--primary" disabled={saving === `skill:${selectedSkill.runtime.name}`} onClick={() => void saveSkill()} type="button">
                        {saving === `skill:${selectedSkill.runtime.name}` ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                        保存 SKILL.md
                      </button>
                    ) : null}
                  </div>
                  <textarea readOnly={!skillEditing} value={skillDraft} onChange={(event) => setSkillDraft(event.target.value)} />
                </div>
              </>
            ) : (
              <div className="workspace-alert">暂无 skill。</div>
            )}
          </article>
        </section>
      ) : activePanel === "tools" ? (
        <section className="operation-layout operation-layout--tools">
          <div className="operation-list">
            <div className="operation-tool-filters">
              <select value={toolBoundaryFilter} onChange={(event) => setToolBoundaryFilter(event.target.value)}>
                {toolBoundaryOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
              <select value={toolRiskFilter} onChange={(event) => setToolRiskFilter(event.target.value)}>
                {toolRiskOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </div>
            {visibleTools.map((tool) => (
              <button
                className={selectedTool?.name === tool.name ? "operation-tool-card operation-tool-card--active" : "operation-tool-card"}
                key={tool.name}
                onClick={() => setSelectedToolName(tool.name)}
                type="button"
              >
                <strong>{toolDisplayName(tool)}</strong>
                <p>{tool.operation_metadata.tool_type} · {tool.operation_metadata.risk_level}风险</p>
              </button>
            ))}
          </div>

          <article className="operation-detail">
            {selectedTool ? (
              <>
                <div className="operation-detail__head">
                  <div>
                    <span>Tool · {selectedTool.name}</span>
                    <h3>{toolDisplayName(selectedTool)}</h3>
                    <p>{selectedTool.module} · {selectedTool.operation_id}</p>
                  </div>
                  <div className={`operation-risk-badge ${RISK_CLASS[selectedTool.operation_metadata.risk_level] ?? ""}`}>
                    <AlertTriangle size={16} />
                    {selectedTool.operation_metadata.risk_level}风险
                  </div>
                </div>

                <div className="operation-skill-meta">
                  <span>边界：{selectedTool.operation_metadata.tool_boundary}</span>
                  <span>类型：{selectedTool.operation_metadata.tool_type}</span>
                  <span>适配：{selectedTool.operation_metadata.adapter_type}</span>
                  <span>策略：{selectedTool.operation_metadata.runtime_policy}</span>
                </div>

                <div className="operation-tool-control">
                  <label>
                    工具类型
                    <select
                      disabled={saving === `tool:${selectedTool.name}`}
                      onChange={(event) => void changeToolType(selectedTool, event.target.value)}
                      value={selectedTool.operation_metadata.tool_type}
                    >
                      {(catalog?.tool_type_options ?? []).map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    LLM 调用描述
                    <textarea
                      onChange={(event) => setToolLlmDescriptionDraft(event.target.value)}
                      placeholder="写给 LLM 的调用说明：什么时候应该调用这个工具，输入边界和主要限制是什么。"
                      value={toolLlmDescriptionDraft}
                    />
                  </label>
                  <label>
                    治理备注
                    <textarea
                      onChange={(event) => setToolNoteDraft(event.target.value)}
                      placeholder="记录这个工具的使用边界、风险备注或接入计划。"
                      value={toolNoteDraft}
                    />
                  </label>
                  <button
                    className="action-button action-button--ghost"
                    disabled={saving === `tool-note:${selectedTool.name}`}
                    onClick={() => void saveToolNote(selectedTool)}
                    type="button"
                  >
                    {saving === `tool-note:${selectedTool.name}` ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                    保存备注
                  </button>
                </div>

                <div className="operation-tool-linked">
                  <article>
                    <strong>可见性</strong>
                    <p>{TOOL_VISIBILITY_LABELS[selectedTool.runtime_visibility] ?? selectedTool.runtime_visibility}</p>
                  </article>
                  <article>
                    <strong>提示暴露</strong>
                    <p>{PROMPT_EXPOSURE_LABELS[selectedTool.prompt_exposure_policy] ?? selectedTool.prompt_exposure_policy}</p>
                  </article>
                  <article>
                    <strong>资源策略</strong>
                    <p>{selectedTool.resource_exposure_policy}</p>
                  </article>
                </div>

                <div className="operation-contract-grid">
                  <article>
                    <strong>执行契约</strong>
                    <pre>{jsonText(selectedTool.contract)}</pre>
                  </article>
                  <article>
                    <Search size={15} />
                    <strong>解析契约</strong>
                    <pre>{jsonText(selectedTool.resolution_contract)}</pre>
                  </article>
                  <article>
                    <Sparkles size={15} />
                    <strong>输出契约</strong>
                    <pre>{jsonText(selectedTool.output_contract)}</pre>
                  </article>
                </div>
              </>
            ) : (
              <div className="workspace-alert">暂无工具。</div>
            )}
          </article>
        </section>
      ) : activePanel === "endpoints" ? (
        <section className="operation-layout operation-layout--workers">
          <div className="operation-list">
            {visibleEndpoints.map((endpoint) => (
              <button
                className={selectedEndpoint?.endpoint_id === endpoint.endpoint_id ? "operation-tool-card operation-tool-card--active" : "operation-tool-card"}
                key={endpoint.endpoint_id}
                onClick={() => setSelectedEndpointId(endpoint.endpoint_id)}
                type="button"
              >
                <strong>{endpoint.title || endpoint.name}</strong>
              </button>
            ))}
          </div>

          <article className="operation-detail">
            {selectedEndpoint ? (
              <>
                <div className="operation-detail__head">
                  <div>
                    <h3>{selectedEndpoint.title || selectedEndpoint.name}</h3>
                    <p>{selectedEndpoint.description}</p>
                  </div>
                  <div className="operation-risk-badge operation-risk--low">
                    <PlugZap size={16} />
                    能力端点
                  </div>
                </div>

                <div className="operation-skill-meta">
                  <span>类型：{selectedEndpoint.kind}</span>
                  <span>Operation：{selectedEndpoint.operation_id}</span>
                  <span>Lane：{selectedEndpoint.runtime_lane}</span>
                  <span>Transport：{selectedEndpoint.transport}</span>
                </div>

                <div className="operation-tool-linked">
                  <article>
                    <strong>能力单元</strong>
                    {selectedEndpoint.owner_units.length ? (
                      <div className="workspace-chip-row">
                        {selectedEndpoint.owner_units.map((unit) => (
                          <span className="workspace-mini-chip" key={unit.unit_id}>{unit.name || unit.unit_id}</span>
                        ))}
                      </div>
                    ) : (
                      <p>当前没有显式能力单元归属。</p>
                    )}
                  </article>
                  <article>
                    <strong>调用模式</strong>
                    <p>{selectedEndpoint.invocation_mode}</p>
                  </article>
                  <article>
                    <strong>可见性</strong>
                    <p>{selectedEndpoint.model_visibility}</p>
                  </article>
                </div>

                <div className="operation-contract-grid">
                  <article>
                    <PlugZap size={15} />
                    <strong>Input Schema</strong>
                    <pre>{jsonText(selectedEndpoint.input_schema)}</pre>
                  </article>
                  <article>
                    <Code2 size={15} />
                    <strong>Output Schema</strong>
                    <pre>{jsonText(selectedEndpoint.output_schema)}</pre>
                  </article>
                  <article>
                    <Search size={15} />
                    <strong>端点元数据</strong>
                    <pre>{jsonText({ annotations: selectedEndpoint.annotations, metadata: selectedEndpoint.metadata })}</pre>
                  </article>
                </div>
              </>
            ) : (
              <div className="workspace-alert">暂无能力端点。</div>
            )}
          </article>
        </section>
      ) : null}
    </div>
  );
}
