"use client";

import {
  AlertTriangle,
  Boxes,
  Code2,
  FilePlus2,
  Hammer,
  Link2,
  Loader2,
  Network,
  PlugZap,
  RefreshCw,
  Route,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wrench
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  createOperationSkill,
  deleteOperationSkill,
  getOperationCatalog,
  refreshOperationCatalog,
  saveOperationSkill,
  updateOperationSkillPromptView,
  updateOperationTool,
  type CapabilityEndpoint,
  type OperationCatalog,
  type OperationSkill,
  type OperationTool
} from "@/lib/api";

type OperationPanel = "skills" | "tools" | "endpoints";
type OperationsViewProps = {
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
  allowed_tools: []
  supported_modalities:
    - text
  supported_task_kinds: []
  supported_source_kinds: []
  capability_tags: []
  preferred_route: rag
  activation_policy: model_visible
  context_mode: inline
  route_authority: candidate_only
---

# ${title || "新 Skill"}

${description || "描述这个 skill 如何帮助智能体完成任务。"}

## 适用场景

- 在这里写清楚模型什么时候应该使用这个 skill。

## 执行准则

- 直接完成用户任务，不暴露内部路由、工具协议或调度细节。
`;
}

function skillSearchText(skill: OperationSkill) {
  return [
    skill.runtime.name,
    skill.runtime.title,
    skill.runtime.description,
    skill.runtime.allowed_tools.join(" "),
    skill.runtime.capability_tags.join(" "),
    skill.prompt_block
  ].join(" ").toLowerCase();
}

function toolSearchText(tool: OperationTool) {
  return [
    tool.name,
    tool.module,
    tool.operation_metadata.tool_type,
    tool.operation_metadata.tool_boundary,
    tool.operation_metadata.adapter_type,
    tool.operation_metadata.risk_level,
    tool.operation_metadata.ownership_label,
    tool.operation_metadata.bound_skills.map((skill) => skill.title || skill.name).join(" "),
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

export function OperationsView({ initialPanel = "skills" }: OperationsViewProps = {}) {
  const [catalog, setCatalog] = useState<OperationCatalog | null>(null);
  const [activePanel, setActivePanel] = useState<OperationPanel>(initialPanel);
  const [selectedSkillName, setSelectedSkillName] = useState("");
  const [selectedToolName, setSelectedToolName] = useState("");
  const [selectedEndpointId, setSelectedEndpointId] = useState("");
  const [skillDraft, setSkillDraft] = useState("");
  const [promptDraft, setPromptDraft] = useState({ title: "", capability: "", use_when: "", output_rule: "" });
  const [promptEditing, setPromptEditing] = useState(false);
  const [toolNoteDraft, setToolNoteDraft] = useState("");
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
      const payload = refresh ? await refreshOperationCatalog() : await getOperationCatalog();
      setCatalog(payload);
      setSelectedSkillName((current) => payload.skills.some((skill) => skill.runtime.name === current) ? current : payload.skills[0]?.runtime.name ?? "");
      setSelectedToolName((current) => payload.tools.some((tool) => tool.name === current) ? current : payload.tools[0]?.name ?? "");
      setSelectedEndpointId((current) => (payload.capability_endpoints ?? []).some((endpoint) => endpoint.endpoint_id === current) ? current : payload.capability_endpoints?.[0]?.endpoint_id ?? "");
      if (refresh) {
        setNotice("操作系统目录已刷新。");
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载操作系统失败");
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
  }, [selectedTool?.name, selectedTool?.operation_metadata.note]);

  async function saveSkill() {
    if (!selectedSkill) {
      return;
    }
    setSaving(`skill:${selectedSkill.runtime.name}`);
    setError("");
    try {
      const payload = await saveOperationSkill(selectedSkill.runtime.name, skillDraft);
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
      const payload = await createOperationSkill({
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
      const payload = await deleteOperationSkill(skill.runtime.name);
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
      const payload = await updateOperationTool(tool.name, {
        tool_type: toolType,
        note: tool.operation_metadata.note
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
      const payload = await updateOperationSkillPromptView(selectedSkill.runtime.name, promptDraft);
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
      const payload = await updateOperationTool(tool.name, {
        tool_type: tool.operation_metadata.tool_type,
        note: toolNoteDraft
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
    <div className="workspace-view operation-system-console">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">能力控制面</p>
          <h2 className="workspace-view__title">操作系统</h2>
          <p className="workspace-view__subtitle">管理 Skills 提示模板和 Tools 注册目录，维护能力说明、工具元数据和治理备注。</p>
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

      <section className="operation-hero">
        <article>
          <span>模型可见 Skills</span>
          <strong>{catalog?.summary.model_visible_skills ?? "-"}</strong>
          <p>这些 skill 会被压缩成能力提示，用于描述可复用方法和适用场景。</p>
        </article>
        <article>
          <span>工具目录</span>
          <strong>{catalog?.summary.tool_count ?? "-"}</strong>
          <p>这里展示后端已注册工具，便于维护分类、风险、边界和备注。</p>
        </article>
        <article>
          <span>Capability Endpoints</span>
          <strong>{catalog?.summary.capability_endpoint_count ?? catalog?.capability_endpoints?.length ?? "-"}</strong>
          <p>这里收纳 local workers 和未来的 MCP 端点，不和工具注册目录重复。</p>
        </article>
        <article>
          <span>调用边界</span>
          <strong>{Object.keys(catalog?.summary.tool_boundaries ?? {}).length || "-"}</strong>
          <p>{Object.entries(catalog?.summary.tool_boundaries ?? {}).map(([name, count]) => `${name}${count}`).join(" / ") || "等待加载"}</p>
        </article>
      </section>

      <nav className="operation-switcher" aria-label="操作系统模块">
        {[
          { id: "skills", label: "Skills 管理", icon: Boxes },
          { id: "tools", label: "工具管理", icon: Wrench },
          { id: "endpoints", label: "能力端点", icon: PlugZap }
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
          placeholder={activePanel === "skills" ? "搜索 skill、能力标签或模型可见提示" : activePanel === "tools" ? "搜索工具、类型、安全标签或契约字段" : "搜索 endpoint、worker、MCP server、operation 或调用模式"}
          value={query}
        />
      </div>

      {activePanel === "skills" ? (
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
                <span>{skill.runtime.preferred_route || "route"}</span>
                <strong>{skill.runtime.title || skill.runtime.name}</strong>
                <p>{skill.runtime.description}</p>
                <small>{listText(skill.runtime.allowed_tools)}</small>
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
                  <span>激活：{selectedSkill.runtime.activation_policy}</span>
                <span>上下文：{selectedSkill.runtime.context_mode}</span>
                  <span>候选工具：{listText(selectedSkill.runtime.allowed_tools)}</span>
                </div>

                {selectedSkill.validation_errors.length ? (
                  <div className="workspace-alert workspace-alert--danger">
                    统一契约校验未通过：{selectedSkill.validation_errors.join(" / ")}
                  </div>
                ) : (
                  <div className="workspace-alert">统一 SkillContract 校验通过。Skill 用于维护方法提示、候选工具和能力标签。</div>
                )}

                <div className="operation-prompt-panel">
                  <div>
                    <Sparkles size={16} />
                    <strong>模型可见 Prompt</strong>
                    <span>由 Prompt 视图字段生成</span>
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
                    <strong>{skillEditing ? "编辑 SKILL.md" : "SKILL.md 只读预览"}</strong>
                  </div>
                  {skillEditing ? (
                    <textarea value={skillDraft} onChange={(event) => setSkillDraft(event.target.value)} />
                  ) : (
                    <pre>{selectedSkill.content}</pre>
                  )}
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
                <span>{tool.operation_metadata.tool_boundary} · {tool.operation_metadata.tool_type}</span>
                <strong>{tool.name}</strong>
                <p>{tool.operation_metadata.visibility_label} · {tool.operation_metadata.adapter_type}</p>
                <small className={RISK_CLASS[tool.operation_metadata.risk_level] ?? ""}>
                  风险：{tool.operation_metadata.risk_level} · {tool.operation_metadata.runtime_policy}
                </small>
              </button>
            ))}
          </div>

          <article className="operation-detail">
            {selectedTool ? (
              <>
                <div className="operation-detail__head">
                  <div>
                    <span>{selectedTool.operation_metadata.tool_boundary}</span>
                    <h3>{selectedTool.name}</h3>
                    <p>{selectedTool.module} · {selectedTool.operation_metadata.editable_policy}</p>
                  </div>
                  <div className={`operation-risk-badge ${RISK_CLASS[selectedTool.operation_metadata.risk_level] ?? ""}`}>
                    <AlertTriangle size={16} />
                    {selectedTool.operation_metadata.risk_level}风险
                  </div>
                </div>

                <div className="operation-tool-map" aria-label="工具调用链">
                  <article>
                    <Link2 size={16} />
                    <span>Skill 候选</span>
                    <strong>{selectedTool.operation_metadata.bound_skills.length || "无"}</strong>
                  </article>
                  <i />
                  <article>
                    <Network size={16} />
                    <span>调用边界</span>
                    <strong>{selectedTool.operation_metadata.tool_boundary}</strong>
                  </article>
                  <i />
                  <article>
                    <ShieldCheck size={16} />
                    <span>契约门</span>
                    <strong>{selectedTool.operation_metadata.runtime_policy}</strong>
                  </article>
                  <i />
                  <article>
                    <Route size={16} />
                    <span>运行适配</span>
                    <strong>{selectedTool.operation_metadata.adapter_type}</strong>
                  </article>
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
                  <div>
                    <span>{selectedTool.operation_metadata.visibility_label}</span>
                    <span>{TOOL_VISIBILITY_LABELS[selectedTool.runtime_visibility] ?? selectedTool.runtime_visibility}</span>
                    <span>{PROMPT_EXPOSURE_LABELS[selectedTool.prompt_exposure_policy] ?? selectedTool.prompt_exposure_policy}</span>
                    <span>资源策略：{selectedTool.resource_exposure_policy}</span>
                  </div>
                </div>

                <div className="operation-tool-flags">
                  <span>{selectedTool.operation_metadata.runtime_policy}</span>
                  <span>{selectedTool.is_read_only ? "只读工具" : "写入工具"}</span>
                  <span>{selectedTool.is_destructive ? "有破坏性风险" : "非破坏性"}</span>
                  <span>{selectedTool.is_concurrency_safe ? "并发安全" : "需串行谨慎"}</span>
                </div>

                <div className="operation-tool-linked">
                  <article>
                    <strong>候选 Skills</strong>
                    {selectedTool.operation_metadata.bound_skills.length ? (
                      <div className="workspace-chip-row">
                        {selectedTool.operation_metadata.bound_skills.map((skill) => (
                          <span className="workspace-mini-chip" key={skill.name}>
                            {skill.title || skill.name} · {skill.activation_policy}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p>当前没有 skill 声明这个工具为候选能力；工具仍然保留在注册目录中。</p>
                    )}
                  </article>
                  <article>
                    <strong>注册可见性</strong>
                    <p>{selectedTool.operation_metadata.visibility_label}</p>
                  </article>
                  <article>
                    <strong>治理提示</strong>
                    <div className="workspace-chip-row">
                      {selectedTool.operation_metadata.governance_hints.map((hint) => (
                        <span className="workspace-mini-chip" key={hint}>{hint}</span>
                      ))}
                    </div>
                  </article>
                </div>

                <div className="operation-contract-grid">
                  <article>
                    <Hammer size={15} />
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

                <div className="workspace-chip-row">
                  {selectedTool.capability_tags.map((tag) => <span className="workspace-mini-chip" key={tag}>{tag}</span>)}
                  {selectedTool.safety_tags.map((tag) => <span className="workspace-mini-chip" key={tag}>{tag}</span>)}
                  {selectedTool.route_hints.map((tag) => <span className="workspace-mini-chip" key={tag}>{tag}</span>)}
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
                <span>{endpoint.kind} · {endpoint.server_name}</span>
                <strong>{endpoint.title || endpoint.name}</strong>
                <p>{endpoint.operation_id} · {endpoint.invocation_mode}</p>
                <small>{endpoint.runtime_lane} · {endpoint.model_visibility}</small>
              </button>
            ))}
          </div>

          <article className="operation-detail">
            {selectedEndpoint ? (
              <>
                <div className="operation-detail__head">
                  <div>
                    <span>{selectedEndpoint.protocol_family}</span>
                    <h3>{selectedEndpoint.title || selectedEndpoint.name}</h3>
                    <p>{selectedEndpoint.description}</p>
                  </div>
                  <div className="operation-risk-badge operation-risk--low">
                    <PlugZap size={16} />
                    能力端点
                  </div>
                </div>

                <div className="operation-tool-map" aria-label="能力端点调度链">
                  <article>
                    <Route size={16} />
                    <span>Endpoint Kind</span>
                    <strong>{selectedEndpoint.kind}</strong>
                  </article>
                  <i />
                  <article>
                    <ShieldCheck size={16} />
                    <span>Operation</span>
                    <strong>{selectedEndpoint.operation_id}</strong>
                  </article>
                  <i />
                  <article>
                    <Network size={16} />
                    <span>Runtime Lane</span>
                    <strong>{selectedEndpoint.runtime_lane}</strong>
                  </article>
                  <i />
                  <article>
                    <PlugZap size={16} />
                    <span>Transport</span>
                    <strong>{selectedEndpoint.transport}</strong>
                  </article>
                </div>

                <div className="operation-tool-flags">
                  <span>{selectedEndpoint.invocation_mode}</span>
                  <span>{selectedEndpoint.model_visibility}</span>
                  <span>{selectedEndpoint.prompt_exposure_policy}</span>
                  <span>{selectedEndpoint.resource_exposure_policy}</span>
                </div>

                <div className="operation-tool-linked">
                  <article>
                    <strong>宿主 Agent</strong>
                    {selectedEndpoint.owner_agents.length ? (
                      <div className="workspace-chip-row">
                        {selectedEndpoint.owner_agents.map((agent) => (
                          <span className="workspace-mini-chip" key={agent.agent_id}>{agent.name || agent.agent_id}</span>
                        ))}
                      </div>
                    ) : (
                      <p>当前没有显式宿主 agent。</p>
                    )}
                  </article>
                  <article>
                    <strong>服务名</strong>
                    <p>{selectedEndpoint.server_name}</p>
                  </article>
                  <article>
                    <strong>来源</strong>
                    <p>{selectedEndpoint.source_ref}</p>
                  </article>
                </div>

                <div className="operation-contract-grid">
                  <article>
                    <PlugZap size={15} />
                    <strong>Input Schema</strong>
                    <pre>{jsonText(selectedEndpoint.input_schema)}</pre>
                  </article>
                  <article>
                    <ShieldCheck size={15} />
                    <strong>Output Schema</strong>
                    <pre>{jsonText(selectedEndpoint.output_schema)}</pre>
                  </article>
                  <article>
                    <Search size={15} />
                    <strong>Endpoint Metadata</strong>
                    <pre>{jsonText({ annotations: selectedEndpoint.annotations, metadata: selectedEndpoint.metadata })}</pre>
                  </article>
                </div>

                <div className="workspace-chip-row">
                  {selectedEndpoint.tags.map((tag) => <span className="workspace-mini-chip" key={tag}>{tag}</span>)}
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
