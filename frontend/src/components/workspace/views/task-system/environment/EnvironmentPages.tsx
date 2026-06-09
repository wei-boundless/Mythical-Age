"use client";

import { AlertTriangle, FileText, Package, Save, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  TaskSystemField,
  TaskSystemToolbarButton,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { GraphTaskWorkspace } from "@/components/workspace/views/task-graph-workbench/GraphTaskWorkspace";
import { TaskGraphRunControlPanel } from "@/components/workspace/views/task-system/TaskGraphRunControlPanel";
import { JsonObjectEditor, dictOf, recordFieldText, splitList } from "@/components/workspace/views/task-system/managementPrimitives";
import type { TaskEnvironmentKindTemplate, TaskSystemOverview } from "@/lib/api";

import type { EnvironmentDraft, TaskEnvironmentItem } from "./TaskEnvironmentManagementWorkbench";

function badPromptPhrases(content: string) {
  return [
    "这是 runtime 节点",
    "这是runtime节点",
    "根据任务图执行",
    "这个节点用于",
    "runtime packet",
    "runtime_packet",
  ].filter((phrase) => content.includes(phrase));
}

function policyDisplay(value: string) {
  const labels: Record<string, string> = {
    allowed: "允许",
    denied: "禁止",
    ask: "需确认",
    task_decided: "按任务判断",
    sandboxed: "沙盒内",
    deny_by_default: "默认拒绝",
    environment_boundary: "按环境边界",
    permission_context: "按权限上下文",
    review_commit_required: "审核后发布",
    verification_required: "验证后发布",
  };
  return labels[value] ?? value;
}

export function EnvironmentTypePage({
  draft,
  groupOptions,
  kindTemplates,
  onDeleteKindTemplate,
  onSaveKindTemplate,
  onSetDraft,
}: {
  draft: EnvironmentDraft;
  groupOptions: Array<{ value: string; label: string }>;
  kindTemplates: TaskEnvironmentKindTemplate[];
  onDeleteKindTemplate: (kindId: string) => Promise<void>;
  onSaveKindTemplate: (template: TaskEnvironmentKindTemplate) => Promise<void>;
  onSetDraft: (draft: EnvironmentDraft) => void;
}) {
  const currentTemplate = kindTemplates.find((item) => item.kind_id === draft.environment_kind) ?? kindTemplates[0];
  const [kindDraft, setKindDraft] = useState<TaskEnvironmentKindTemplate>(() => currentTemplate ?? {
    kind_id: "custom",
    title: "Custom",
    description: "",
    group_id: draft.group_id,
    allowed_resource_refs: [],
    allowed_task_graph_kinds: [],
    enabled: true,
  });
  const [error, setError] = useState("");

  useEffect(() => {
    if (currentTemplate) setKindDraft(currentTemplate);
  }, [currentTemplate]);

  async function saveKindTemplate() {
    setError("");
    try {
      if (!kindDraft.kind_id.trim()) throw new Error("环境类型 kind_id 不能为空。");
      await onSaveKindTemplate({
        ...kindDraft,
        allowed_resource_refs: kindDraft.allowed_resource_refs ?? [],
        allowed_task_graph_kinds: kindDraft.allowed_task_graph_kinds ?? [],
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "环境类型保存失败");
    }
  }

  return (
    <section className="task-system-two-column">
      <aside className="task-system-filter-rail">
        <header><strong>环境类型</strong><span>{kindTemplates.length} 类模板</span></header>
        <div className="task-system-list-stack">
          {kindTemplates.map((template) => (
            <button
              className={template.kind_id === kindDraft.kind_id ? "task-system-list-button task-system-list-button--active" : "task-system-list-button"}
              key={template.kind_id}
              onClick={() => {
                setKindDraft(template);
                onSetDraft({ ...draft, environment_kind: template.kind_id, group_id: template.group_id || draft.group_id });
              }}
              type="button"
            >
              <strong>{template.title || template.kind_id}</strong>
              <span>{template.kind_id}</span>
            </button>
          ))}
        </div>
      </aside>
      <section className="task-system-detail-inspector task-system-detail-inspector--flat">
        <header className="task-system-inspector-head">
          <div><span>环境类型</span><strong>{kindDraft.title || kindDraft.kind_id}</strong><small>{kindDraft.kind_id}</small></div>
        </header>
        {error ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />{error}</div> : null}
        <section className="task-system-inspector-section">
          <header><ShieldCheck size={15} /><strong>类型模板</strong><span>默认资源和策略边界</span></header>
          <div className="boundary-form">
            <TaskSystemField label="类型标识"><input value={kindDraft.kind_id} onChange={(event) => setKindDraft({ ...kindDraft, kind_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="名称"><input value={kindDraft.title} onChange={(event) => setKindDraft({ ...kindDraft, title: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="分组">
              <select value={kindDraft.group_id || ""} onChange={(event) => setKindDraft({ ...kindDraft, group_id: event.target.value })}>
                <option value="">不绑定分组</option>
                {groupOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </TaskSystemField>
            <TaskSystemField label="说明缓存范围"><input value={kindDraft.default_prompt_cache_scope || "static_environment"} onChange={(event) => setKindDraft({ ...kindDraft, default_prompt_cache_scope: event.target.value })} /></TaskSystemField>
            <label className="boundary-check"><input checked={kindDraft.enabled !== false} onChange={(event) => setKindDraft({ ...kindDraft, enabled: event.target.checked })} type="checkbox" />启用类型模板</label>
            <TaskSystemField label="说明" wide><textarea value={kindDraft.description || ""} onChange={(event) => setKindDraft({ ...kindDraft, description: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="允许资源" wide><textarea value={(kindDraft.allowed_resource_refs ?? []).join("\n")} onChange={(event) => setKindDraft({ ...kindDraft, allowed_resource_refs: splitList(event.target.value) })} /></TaskSystemField>
            <TaskSystemField label="允许任务图类型" wide><textarea value={(kindDraft.allowed_task_graph_kinds ?? []).join("\n")} onChange={(event) => setKindDraft({ ...kindDraft, allowed_task_graph_kinds: splitList(event.target.value) })} /></TaskSystemField>
            <JsonObjectEditor label="默认沙盒策略" value={kindDraft.default_sandbox_policy ?? {}} onChange={(default_sandbox_policy) => setKindDraft({ ...kindDraft, default_sandbox_policy })} />
            <JsonObjectEditor label="默认执行策略" value={kindDraft.default_execution_policy ?? {}} onChange={(default_execution_policy) => setKindDraft({ ...kindDraft, default_execution_policy })} />
            <JsonObjectEditor label="默认风险策略" value={kindDraft.default_risk_policy ?? {}} onChange={(default_risk_policy) => setKindDraft({ ...kindDraft, default_risk_policy })} />
          </div>
          <div className="boundary-actions">
            <TaskSystemToolbarButton onClick={() => void onDeleteKindTemplate(kindDraft.kind_id)}><Trash2 size={14} />删除类型</TaskSystemToolbarButton>
            <TaskSystemToolbarButton onClick={() => void saveKindTemplate()} variant="primary"><Save size={14} />保存类型</TaskSystemToolbarButton>
          </div>
        </section>
      </section>
    </section>
  );
}

export function EnvironmentLoadoutPage({
  draft,
  onSetDraft,
  selectedItem,
}: {
  draft: EnvironmentDraft;
  onSetDraft: (draft: EnvironmentDraft) => void;
  selectedItem: TaskEnvironmentItem | undefined;
}) {
  const selectedStorageSpace = dictOf(selectedItem?.storage_space);
  const selectedSandboxPolicy = dictOf(selectedItem?.sandbox_policy);
  const selectedExecutionPolicy = dictOf(selectedItem?.execution_policy);
  const selectedRiskPolicy = dictOf(selectedItem?.risk_policy);
  const selectedArtifactPolicy = dictOf(selectedItem?.artifact_policy);
  const selectedFileManagement = dictOf(selectedItem?.file_management);
  const selectedTaskLibrary = dictOf(selectedItem?.task_library);
  const fileAccessTables = Array.isArray(selectedItem?.file_access_tables) ? selectedItem.file_access_tables : [];
  const patch = (next: Partial<EnvironmentDraft>) => onSetDraft({ ...draft, ...next });
  const fileProfileRefs = Array.isArray(selectedFileManagement.file_profile_refs)
    ? selectedFileManagement.file_profile_refs.length
    : splitList(draft.file_profile_refs_text).length;
  const repositoryKindCount = Array.isArray(selectedFileManagement.required_repository_kinds)
    ? selectedFileManagement.required_repository_kinds.length
    : splitList(draft.required_repository_kinds_text).length;
  const memoryLoadCount = splitList(draft.environment_memory_refs_text).length
    + splitList(draft.project_knowledge_refs_text).length
    + splitList(draft.shared_context_refs_text).length
    + splitList(draft.retrieval_index_refs_text).length;
  const promptLoadCount = draft.prompt_content.trim() ? 1 : 0;
  const resourceRefFields: Array<{ key: keyof EnvironmentDraft; label: string }> = [
    { key: "file_profile_refs_text", label: "文件资源" },
    { key: "required_repository_kinds_text", label: "仓库资源" },
    { key: "environment_memory_refs_text", label: "环境记忆" },
    { key: "project_knowledge_refs_text", label: "项目知识" },
    { key: "shared_context_refs_text", label: "共享上下文" },
    { key: "retrieval_index_refs_text", label: "检索索引" },
  ];
  const policySummaryItems = [
    ["命令", policyDisplay(recordFieldText(selectedExecutionPolicy, ["shell_execution_policy"], recordFieldText(selectedSandboxPolicy, ["shell_policy"], "未声明")))],
    ["浏览器", policyDisplay(recordFieldText(selectedExecutionPolicy, ["browser_execution_policy"], recordFieldText(selectedSandboxPolicy, ["browser_policy"], "未声明")))],
    ["网络", policyDisplay(recordFieldText(selectedExecutionPolicy, ["network_execution_policy"], recordFieldText(selectedSandboxPolicy, ["network_policy"], "未声明")))],
    ["权限", policyDisplay(recordFieldText(selectedRiskPolicy, ["default_permission_mode"], "未声明"))],
    ["产物", policyDisplay(recordFieldText(selectedArtifactPolicy, ["publish_policy"], "未声明"))],
  ];
  const policyTextFields: Array<{ key: keyof EnvironmentDraft; label: string }> = [
    { key: "file_management_text", label: "文件资源装载策略" },
    { key: "resource_space_text", label: "资源空间策略" },
    { key: "memory_space_text", label: "记忆资源装载策略" },
    { key: "sandbox_policy_text", label: "沙盒策略" },
    { key: "execution_policy_text", label: "执行策略" },
    { key: "artifact_policy_text", label: "产物策略" },
    { key: "risk_policy_text", label: "风险策略" },
    { key: "observability_policy_text", label: "观测策略" },
    { key: "lifecycle_policy_text", label: "生命周期策略" },
    { key: "metadata_text", label: "Record metadata" },
    { key: "spec_metadata_text", label: "Spec metadata" },
  ];

  return (
    <div className="task-system-inspector-stack">
      <section className="task-system-metric-grid">
        <article className="task-system-metric"><span>文件资源</span><strong>{fileProfileRefs}</strong><small>{repositoryKindCount} 类仓库</small></article>
        <article className="task-system-metric"><span>记忆与检索</span><strong>{memoryLoadCount}</strong><small>记忆 / 知识 / 检索</small></article>
        <article className="task-system-metric"><span>环境说明</span><strong>{promptLoadCount}</strong><small>{promptLoadCount ? "Agent 可读取" : "未配置"}</small></article>
        <article className="task-system-metric"><span>存储空间</span><strong>{recordFieldText(selectedStorageSpace, ["storage_namespace"], draft.storage_namespace || "未声明")}</strong><small>运行时自动分配</small></article>
      </section>
      <section className="task-system-inspector-section">
        <header><Package size={15} /><strong>资源装载</strong><span>选择 Agent 本环境可读取和写入的资源</span></header>
        <div className="boundary-form task-environment-loadout-form">
          <TaskSystemField label="名称"><input value={draft.title} onChange={(event) => patch({ title: event.target.value })} /></TaskSystemField>
          <label className="boundary-check"><input checked={draft.enabled} onChange={(event) => patch({ enabled: event.target.checked })} type="checkbox" />启用任务环境</label>
          <TaskSystemField label="说明" wide><textarea value={draft.description} onChange={(event) => patch({ description: event.target.value })} /></TaskSystemField>
          {resourceRefFields.map((field) => (
            <TaskSystemField key={field.key} label={field.label} wide>
              <textarea value={String(draft[field.key] ?? "")} onChange={(event) => patch({ [field.key]: event.target.value } as Partial<EnvironmentDraft>)} />
            </TaskSystemField>
          ))}
        </div>
        <details className="task-system-advanced-disclosure">
          <summary>高级标识与存储</summary>
          <div className="boundary-form">
            <TaskSystemField label="环境标识"><input value={draft.environment_id} onChange={(event) => patch({ environment_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="环境分组"><input value={draft.group_id} onChange={(event) => patch({ group_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="环境类型"><input value={draft.environment_kind} onChange={(event) => patch({ environment_kind: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="存储命名空间"><input value={draft.storage_namespace} onChange={(event) => patch({ storage_namespace: event.target.value })} /></TaskSystemField>
          </div>
        </details>
      </section>
      <section className="task-system-inspector-section">
        <header><ShieldCheck size={15} /><strong>执行边界</strong><span>运行、浏览器、网络、权限和产物发布</span></header>
        <div className="task-environment-policy-strip">
          {policySummaryItems.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}
        </div>
        <details className="task-system-advanced-disclosure">
          <summary>高级策略与元数据</summary>
          <div className="boundary-form boundary-form--json">
            {policyTextFields.map((field) => (
              <TaskSystemField key={field.key} label={field.label} wide>
                <textarea value={String(draft[field.key] ?? "")} onChange={(event) => patch({ [field.key]: event.target.value } as Partial<EnvironmentDraft>)} />
              </TaskSystemField>
            ))}
          </div>
          <div className="task-system-usage-list">
            {fileAccessTables.slice(0, 5).map((table, index) => (
              <article className="task-system-usage-row" key={`${String(table.profile_id ?? "")}-${index}`}>
                <strong>{String(table.profile_id ?? "file profile")}</strong>
                <span>{String(table.authority ?? "")}</span>
              </article>
            ))}
          </div>
        </details>
        <div className="boundary-empty">环境内任务数：{String(selectedTaskLibrary.task_count ?? 0)}</div>
      </section>
    </div>
  );
}

export function EnvironmentPromptPage({
  draft,
  onSetDraft,
  selectedItem,
}: {
  draft: EnvironmentDraft;
  onSetDraft: (draft: EnvironmentDraft) => void;
  selectedItem: TaskEnvironmentItem | undefined;
}) {
  const patch = (next: Partial<EnvironmentDraft>) => onSetDraft({ ...draft, ...next });
  const badPhrases = badPromptPhrases(draft.prompt_content);
  const prompts = Array.isArray(selectedItem?.environment_prompts) ? selectedItem.environment_prompts : [];
  return (
    <section className="task-system-two-column">
      <section className="task-system-detail-inspector task-system-detail-inspector--flat">
        <header className="task-system-inspector-head">
          <div><span>环境说明</span><strong>{draft.prompt_id || "未命名说明"}</strong><small>{badPhrases.length ? `${badPhrases.length} 个表达需要修正` : "Agent 可见"}</small></div>
        </header>
        {badPhrases.length ? <div className="boundary-notice boundary-notice--error"><AlertTriangle size={16} />环境 Prompt 含开发说明表达：{badPhrases.join("、")}</div> : null}
        <section className="task-system-inspector-section">
          <header><FileText size={15} /><strong>说明编辑</strong><span>必须写成 Agent 能直接执行的环境说明</span></header>
          <div className="boundary-form">
            <TaskSystemField label="说明标识"><input value={draft.prompt_id} onChange={(event) => patch({ prompt_id: event.target.value })} /></TaskSystemField>
            <TaskSystemField label="Prompt 内容" wide><textarea className="task-system-role-prompt" value={draft.prompt_content} onChange={(event) => patch({ prompt_content: event.target.value })} /></TaskSystemField>
          </div>
        </section>
      </section>
      <aside className="task-system-filter-rail">
        <header><strong>Agent 可见预览</strong><span>{prompts.length || (draft.prompt_content.trim() ? 1 : 0)} 条说明</span></header>
        <pre className="task-system-runtime-preview">{draft.prompt_content.trim() || "当前环境没有 prompt，agent 无法从环境配置感知资源边界。"}</pre>
        <div className="task-system-usage-list">
          {prompts.map((prompt, index) => (
            <article className="task-system-usage-row" key={`${String(prompt.prompt_id ?? "")}-${index}`}>
              <strong>{String(prompt.prompt_id ?? "prompt")}</strong>
              <span>{String(prompt.cache_scope ?? prompt.prompt_kind ?? "")}</span>
            </article>
          ))}
        </div>
      </aside>
    </section>
  );
}

export function EnvironmentTaskInventoryPage({
  environmentItems,
  onAssignTaskEnvironment,
  selectedEnvironmentId,
  taskSystemOverview,
}: {
  environmentItems: TaskEnvironmentItem[];
  onAssignTaskEnvironment: (record: Record<string, unknown>, environmentId: string) => Promise<void>;
  selectedEnvironmentId: string;
  taskSystemOverview: TaskSystemOverview | null;
}) {
  const inventory = taskSystemOverview?.environment_task_inventory?.items ?? [];
  const assignmentById = new Map((taskSystemOverview?.task_management.task_assignments ?? []).map((item) => [String(item.task_id ?? ""), item]));
  const [draftEnvByTask, setDraftEnvByTask] = useState<Record<string, string>>({});
  const rows = inventory.filter((item) => String(item.environment_id || "") === selectedEnvironmentId || !String(item.environment_id || ""));
  const envOptions = environmentItems.map((item) => ({ value: item.record.environment_id, label: item.record.title || item.record.environment_id }));

  return (
    <section className="task-system-detail-inspector task-system-detail-inspector--flat">
      <header className="task-system-inspector-head">
        <div><span>环境任务</span><strong>环境内任务</strong><small>{rows.length} 项</small></div>
      </header>
      <div className="task-system-catalog-table task-system-catalog-table--full">
        <header className="task-system-table-head">
          <span>任务</span>
          <span>流程</span>
          <span>输入/输出契约</span>
          <span>环境归属</span>
          <span>操作</span>
        </header>
        <div className="task-system-table-body">
          {rows.map((row) => {
            const taskId = String(row.task_id ?? "");
            const assignment = assignmentById.get(taskId) ?? row;
            const nextEnv = draftEnvByTask[taskId] ?? String(row.environment_id ?? "");
            return (
              <article className="task-system-table-row task-system-table-row--static" key={taskId}>
                <strong>{String(row.task_title || taskId)}<small>{taskId}</small></strong>
                <span>{String(row.flow_id || "-")}</span>
                <span>{String(row.input_contract_id || "-")} / {String(row.output_contract_id || "-")}</span>
                <span>
                  <select value={nextEnv} onChange={(event) => setDraftEnvByTask({ ...draftEnvByTask, [taskId]: event.target.value })}>
                    <option value="">未归属</option>
                    {envOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                </span>
                <em><TaskSystemToolbarButton onClick={() => void onAssignTaskEnvironment(assignment, nextEnv)}><Save size={14} />保存归属</TaskSystemToolbarButton></em>
              </article>
            );
          })}
          {!rows.length ? <div className="boundary-empty">当前环境没有任务，且没有未归属任务可绑定。</div> : null}
        </div>
      </div>
    </section>
  );
}

export function EnvironmentGraphInventoryPage({
  onSelectGraph,
  selectedGraphId,
  taskSystemOverview,
}: {
  onSelectGraph: (graphId: string) => void;
  selectedGraphId: string;
  taskSystemOverview: TaskSystemOverview | null;
}) {
  const rows = taskSystemOverview?.environment_graph_inventory?.items ?? [];
  const activeGraphId = rows.some((row) => String(row.graph_id ?? "") === selectedGraphId)
    ? selectedGraphId
    : String(rows[0]?.graph_id ?? "");

  useEffect(() => {
    if (activeGraphId && activeGraphId !== selectedGraphId) {
      onSelectGraph(activeGraphId);
    }
  }, [activeGraphId, onSelectGraph, selectedGraphId]);

  return (
    <section className="task-environment-graph-workbench" aria-label="图任务工作区">
      <aside className="task-environment-graph-workbench__inventory">
        <header className="task-system-inspector-head">
          <div><span>图任务</span><strong>图任务工作区</strong><small>{rows.length} 张图</small></div>
        </header>
        <div className="task-system-catalog-table task-system-catalog-table--full">
          <header className="task-system-table-head task-system-table-head--graphs">
            <span>任务图</span>
            <span>类型</span>
            <span>入口/出口</span>
            <span>节点/边</span>
            <span>操作</span>
          </header>
          <div className="task-system-table-body">
            {rows.map((row) => {
              const graphId = String(row.graph_id ?? "");
              const active = graphId === activeGraphId;
              return (
                <button
                  aria-current={active ? "page" : undefined}
                  className={active ? "task-system-table-row task-system-table-row--graph task-system-table-row--active" : "task-system-table-row task-system-table-row--graph"}
                  key={graphId}
                  onClick={() => onSelectGraph(graphId)}
                  type="button"
                >
                  <strong>{String(row.title || row.graph_id)}<small>{graphId}</small></strong>
                  <span>{String(row.graph_kind || "-")}</span>
                  <span>{String(row.entry_node_id || "-")} / {String(row.output_node_id || "-")}</span>
                  <span>{String(row.node_count ?? 0)} / {String(row.edge_count ?? 0)}</span>
                  <em className="task-system-graph-row__actions">
                    <span className="task-system-status">{String(row.publish_state || "-")}</span>
                    <span>{active ? "编辑中" : "编辑"}</span>
                  </em>
                </button>
              );
            })}
            {!rows.length ? <div className="boundary-empty">当前项目还没有任务图。</div> : null}
          </div>
        </div>
      </aside>
      <div className="task-environment-graph-workbench__editor">
        <TaskGraphRunControlPanel
          className="task-environment-graph-workbench__monitor"
          graphId={activeGraphId}
          title="当前图运行监控"
        />
        {activeGraphId ? (
          <GraphTaskWorkspace
            requestedGraphId={activeGraphId}
            onSelectedGraphChange={onSelectGraph}
          />
        ) : (
          <div className="boundary-empty">选择一个任务图后编辑拓扑、节点和发布设置。</div>
        )}
      </div>
    </section>
  );
}
