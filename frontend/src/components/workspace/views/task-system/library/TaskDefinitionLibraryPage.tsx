"use client";

import { Plus, Save, Trash2 } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import type { ContractSpec, SpecificTaskRecord, TaskContractDescriptor, TaskSystemOverview } from "@/lib/api";

import { contractSpecTitle } from "../ContractLibraryPanel";
import { TaskDefinitionPage } from "../TaskSystemPages";
import {
  TaskSystemField as Field,
  TaskSystemSelectField as SelectField,
  TaskSystemToolbarButton as ToolbarButton,
  taskSystemDisplayLabel,
} from "../TaskSystemWorkbenchUi";

type TaskConfigPanel = "definition";

type TaskDefinitionDomain = {
  title: string;
};

type ArtifactPolicyDraft = {
  artifact_root: string;
  enabled: boolean;
  materializer: string;
  optional_files_text: string;
  required_files_text: string;
  subdir_template: string;
};

type TaskGraphReference = {
  graph: {
    graph_id: string;
    publish_state?: string;
    title?: string;
  };
  nodeRefs: Array<{
    nodeId: string;
    title: string;
  }>;
};

type LayerNavItem<T extends string> = {
  detail: string;
  label: string;
  meta: string;
  value: T;
};

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

function displayId(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const registeredLabel = taskSystemDisplayLabel(raw, fallback);
  if (registeredLabel !== raw) return registeredLabel;
  const labels: Record<string, string> = {
    AssistantFinalAnswer: "最终回答",
    LightWebGameResult: "网页游戏产物",
    UserMessage: "用户消息",
    WorkspaceTaskInput: "工作区任务输入",
    bounded: "受限准入",
    fail_closed: "失败即关闭",
    main_agent: "主 Agent",
    orchestration_default: "编排默认选择",
    standard: "标准级",
    task_default: "任务默认",
    workflow_compatible_or_task_default: "流程兼容优先",
  };
  return labels[raw] ? `${labels[raw]} · ${raw}` : raw;
}

function contractLabel(value: string, specs: ContractSpec[] = [], legacyContracts: TaskContractDescriptor[] = []) {
  const spec = specs.find((item) => item.contract_id === value);
  if (spec) return `${contractSpecTitle(spec)} · ${value}`;
  const contract = legacyContracts.find((item) => item.contract_id === value);
  return contract?.title || displayId(value);
}

function SystemFields({ children }: { children: ReactNode }) {
  return (
    <details className="boundary-system-fields">
      <summary>系统字段</summary>
      <div className="boundary-form">{children}</div>
    </details>
  );
}

function LayerNav<T extends string>({
  ariaLabel,
  items,
  onChange,
  value,
  variant = "primary",
}: {
  ariaLabel: string;
  items: Array<LayerNavItem<T>>;
  onChange: (value: T) => void;
  value: T;
  variant?: "primary" | "secondary";
}) {
  return (
    <nav className={variant === "secondary" ? "task-system-layer-nav task-system-layer-nav--secondary" : "task-system-layer-nav"} aria-label={ariaLabel}>
      {items.map((item) => (
        <button
          className={value === item.value ? "task-system-layer-nav__item task-system-layer-nav__item--active" : "task-system-layer-nav__item"}
          key={item.value}
          onClick={() => onChange(item.value)}
          type="button"
        >
          <span>{item.label}</span>
          <strong>{item.meta}</strong>
          <small>{item.detail}</small>
        </button>
      ))}
    </nav>
  );
}

function ContractSelectField({
  contracts,
  label,
  legacyContracts,
  onChange,
  options,
  value,
  wide = false,
}: {
  contracts: ContractSpec[];
  label: string;
  legacyContracts?: TaskContractDescriptor[];
  onChange: (value: string) => void;
  options: string[];
  value: string;
  wide?: boolean;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <Field label={label} wide={wide}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => (
          <option key={item} value={item}>{contractLabel(item, contracts, legacyContracts)}</option>
        ))}
      </select>
    </Field>
  );
}

function FlowContractSelect({
  flows,
  label,
  onChange,
  value,
}: {
  flows: TaskSystemOverview["task_management"]["task_flow_definitions"];
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const known = flows.map((flow) => String(flow.flow_id || "")).filter(Boolean);
  const resolvedOptions = uniqueStrings([value, ...known]);
  return (
    <Field label={label}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => {
          const flow = flows.find((candidate) => candidate.flow_id === item);
          return <option key={item} value={item}>{flow?.title || displayId(item)}</option>;
        })}
      </select>
    </Field>
  );
}

export function TaskDefinitionLibraryPage({
  artifactPolicyDraft,
  commonContractOptions,
  contractCatalog,
  domainContractSpecs,
  eligibilityRows,
  onCreateTask,
  onDeleteTask,
  onOpenTaskGraph,
  onSaveTask,
  onSelectTask,
  onSendTaskToChat,
  onSetArtifactPolicyDraft,
  onSetTaskConfigPanel,
  onSetTaskDraft,
  onSetTaskPolicyText,
  saving,
  selectedDomain,
  selectedTask,
  selectedTaskGraphReferences,
  selectedTaskId,
  taskConfigPanel,
  taskDetailPanelItems,
  taskDraft,
  taskFlowDefinitions,
  taskPolicyError,
  taskPolicyText,
  tasks,
  workflowOptions,
}: {
  artifactPolicyDraft: ArtifactPolicyDraft;
  commonContractOptions: string[];
  contractCatalog: TaskContractDescriptor[];
  domainContractSpecs: ContractSpec[];
  eligibilityRows: Array<{ label: string; value: string }>;
  onCreateTask: () => void;
  onDeleteTask: () => void;
  onOpenTaskGraph: (graphId: string) => void;
  onSaveTask: () => void;
  onSelectTask: (taskId: string) => void;
  onSendTaskToChat: () => void | Promise<void>;
  onSetArtifactPolicyDraft: Dispatch<SetStateAction<ArtifactPolicyDraft>>;
  onSetTaskConfigPanel: (panel: TaskConfigPanel) => void;
  onSetTaskDraft: Dispatch<SetStateAction<SpecificTaskRecord>>;
  onSetTaskPolicyText: (value: string) => void;
  saving: string;
  selectedDomain: TaskDefinitionDomain | null;
  selectedTask: SpecificTaskRecord | null;
  selectedTaskGraphReferences: TaskGraphReference[];
  selectedTaskId: string;
  taskConfigPanel: TaskConfigPanel;
  taskDetailPanelItems: Array<LayerNavItem<TaskConfigPanel>>;
  taskDraft: SpecificTaskRecord;
  taskFlowDefinitions: TaskSystemOverview["task_management"]["task_flow_definitions"];
  taskPolicyError: string;
  taskPolicyText: string;
  tasks: SpecificTaskRecord[];
  workflowOptions: string[];
}) {
  return (
    <TaskDefinitionPage>
      <aside className="task-management-directory">
        <div className="task-management-directory__head">
          <span>{selectedDomain?.title || "未选择任务域"}</span>
          <strong>具体任务</strong>
          <ToolbarButton disabled={saving === "task-create" || !selectedDomain} onClick={onCreateTask}>
            <Plus size={15} />新任务
          </ToolbarButton>
        </div>
        <div className="boundary-list">
          {tasks.map((task) => (
            <button
              className={task.task_id === selectedTaskId ? "boundary-list-row boundary-list-row--active task-domain-task-row" : "boundary-list-row task-domain-task-row"}
              key={task.task_id}
              onClick={() => onSelectTask(task.task_id)}
              type="button"
            >
              <strong>{task.task_title}</strong>
              <span>{task.enabled ? "启用" : "停用"}</span>
            </button>
          ))}
          {!tasks.length ? <div className="boundary-empty">当前任务域暂无任务。</div> : null}
        </div>
      </aside>

      <main className="task-management-workbench">
        <header className="task-management-titlebar">
          <div>
            <span>任务定义库</span>
            <h3>{selectedTask ? (taskDraft.task_title || selectedTask.task_title) : "未选择任务"}</h3>
            <p>这里只定义可复用的具体任务。任务图是同一任务域下的独立编排对象，图模块可以引用这里的任务定义。</p>
          </div>
          <div className="boundary-actions">
            <ToolbarButton disabled={saving === "task-order-create" || !selectedTask} onClick={() => void onSendTaskToChat()}>
              {saving === "task-order-create" ? "创建订单中" : "带入主会话"}
            </ToolbarButton>
            <ToolbarButton disabled={saving === "task-stack" || !selectedTask} onClick={onSaveTask} variant="primary">
              <Save size={15} />保存任务
            </ToolbarButton>
          </div>
        </header>

        {selectedTask ? (
          <section className="boundary-layer-stack">
            <LayerNav
              ariaLabel="任务详情页面"
              items={taskDetailPanelItems}
              onChange={onSetTaskConfigPanel}
              value={taskConfigPanel}
              variant="secondary"
            />
            <section className="boundary-card">
              <header>
                <strong>{taskDraft.task_title || "特定任务定义"}</strong>
                <ToolbarButton disabled={saving === "task-delete"} onClick={onDeleteTask}>
                  <Trash2 size={15} />删除任务
                </ToolbarButton>
              </header>
              <div className="boundary-form task-definition-form">
                <Field label="任务标题">
                  <input
                    onChange={(event) => onSetTaskDraft((value) => ({ ...value, task_title: event.target.value }))}
                    value={taskDraft.task_title}
                  />
                </Field>
                <Field label="所属任务域">
                  <input readOnly value={selectedDomain?.title || taskDraft.domain_id || "未选择任务域"} />
                </Field>
                <Field label="验收档案">
                  <input
                    onChange={(event) => onSetTaskDraft((value) => ({ ...value, acceptance_profile_id: event.target.value }))}
                    value={taskDraft.acceptance_profile_id}
                  />
                </Field>
                <Field label="任务描述" wide>
                  <textarea
                    onChange={(event) => onSetTaskDraft((value) => ({ ...value, description: event.target.value }))}
                    value={taskDraft.description}
                  />
                </Field>
                <label className="boundary-check">
                  <input
                    checked={taskDraft.enabled}
                    onChange={(event) => onSetTaskDraft((value) => ({ ...value, enabled: event.target.checked }))}
                    type="checkbox"
                  />
                  启用任务
                </label>
                <section className="contract-editor-section task-artifact-policy-editor">
                  <header><strong>产物规则</strong><span>任务级默认产物策略；正式产物记录在运行管理中查看</span></header>
                  <div className="boundary-form">
                    <Field label="产物根目录">
                      <input
                        onChange={(event) => onSetArtifactPolicyDraft((value) => ({ ...value, artifact_root: event.target.value }))}
                        placeholder="output/novels/honghuang-shidai"
                        value={artifactPolicyDraft.artifact_root}
                      />
                    </Field>
                    <Field label="任务子目录">
                      <input
                        onChange={(event) => onSetArtifactPolicyDraft((value) => ({ ...value, subdir_template: event.target.value }))}
                        placeholder="{task_slug}/{run_slug}"
                        value={artifactPolicyDraft.subdir_template}
                      />
                    </Field>
                    <Field label="生成器">
                      <input
                        onChange={(event) => onSetArtifactPolicyDraft((value) => ({ ...value, materializer: event.target.value }))}
                        value={artifactPolicyDraft.materializer}
                      />
                    </Field>
                    <label className="boundary-check">
                      <input
                        checked={artifactPolicyDraft.enabled}
                        onChange={(event) => onSetArtifactPolicyDraft((value) => ({ ...value, enabled: event.target.checked }))}
                        type="checkbox"
                      />
                      启用产物落盘
                    </label>
                    <Field label="必需产物" wide>
                      <textarea
                        onChange={(event) => onSetArtifactPolicyDraft((value) => ({ ...value, required_files_text: event.target.value }))}
                        placeholder={"01_project_bible.md\n02_world_bible.md"}
                        value={artifactPolicyDraft.required_files_text}
                      />
                    </Field>
                    <Field label="可选产物" wide>
                      <textarea
                        onChange={(event) => onSetArtifactPolicyDraft((value) => ({ ...value, optional_files_text: event.target.value }))}
                        placeholder="chapters/chapter_001_draft.md"
                        value={artifactPolicyDraft.optional_files_text}
                      />
                    </Field>
                  </div>
                </section>
                <SystemFields>
                  <Field label="任务 ID">
                    <input
                      onChange={(event) => onSetTaskDraft((value) => ({ ...value, task_id: event.target.value }))}
                      value={taskDraft.task_id}
                    />
                  </Field>
                  <ContractSelectField
                    contracts={domainContractSpecs}
                    label="输入契约"
                    legacyContracts={contractCatalog}
                    onChange={(value) => onSetTaskDraft((current) => ({ ...current, input_contract_id: value }))}
                    options={commonContractOptions}
                    value={taskDraft.input_contract_id}
                  />
                  <ContractSelectField
                    contracts={domainContractSpecs}
                    label="输出契约"
                    legacyContracts={contractCatalog}
                    onChange={(value) => onSetTaskDraft((current) => ({ ...current, output_contract_id: value }))}
                    options={commonContractOptions}
                    value={taskDraft.output_contract_id}
                  />
                  <SelectField
                    label="默认执行流程"
                    onChange={(value) => onSetTaskDraft((current) => ({ ...current, default_workflow_id: value }))}
                    options={workflowOptions}
                    value={taskDraft.default_workflow_id}
                  />
                  <FlowContractSelect
                    flows={taskFlowDefinitions}
                    label="默认流程契约"
                    onChange={(value) => onSetTaskDraft((current) => ({ ...current, default_flow_contract_id: value }))}
                    value={taskDraft.default_flow_contract_id}
                  />
                  <SelectField
                    label="投影策略"
                    onChange={(value) => onSetTaskDraft((current) => ({ ...current, default_projection_policy: value }))}
                    options={["workflow_compatible_or_task_default", "task_default"]}
                    value={taskDraft.default_projection_policy}
                  />
                  <Field label="任务策略" wide>
                    <>
                      <textarea value={taskPolicyText} onChange={(event) => onSetTaskPolicyText(event.target.value)} />
                      <small className={taskPolicyError ? "boundary-json-state boundary-json-state--error" : "boundary-json-state"}>{taskPolicyError || "JSON 可解析"}</small>
                    </>
                  </Field>
                </SystemFields>
              </div>
            </section>

            <section className="boundary-card">
              <header><strong>承接要求</strong></header>
              <div className="boundary-kv task-eligibility-grid">
                {eligibilityRows.map((row) => <p key={row.label}><span>{row.label}</span><strong>{row.value}</strong></p>)}
              </div>
            </section>

            <section className="boundary-card">
              <header><strong>被任务图模块引用</strong><span>{selectedTaskGraphReferences.length} 张图</span></header>
              <div className="boundary-list boundary-list--scroll">
                {selectedTaskGraphReferences.map(({ graph, nodeRefs }) => (
                  <article className="boundary-list-row boundary-list-row--stacked" key={graph.graph_id}>
                    <div>
                      <strong>{graph.title || graph.graph_id}</strong>
                      <span>{graph.publish_state || "draft"} / {nodeRefs.length} 个节点引用</span>
                    </div>
                    <span>{nodeRefs.map((item) => `${item.title} · ${item.nodeId}`).join(" / ")}</span>
                    <div className="boundary-actions">
                      <ToolbarButton onClick={() => onOpenTaskGraph(graph.graph_id)}>打开这张图</ToolbarButton>
                    </div>
                  </article>
                ))}
                {!selectedTaskGraphReferences.length ? (
                  <div className="boundary-empty">当前具体任务还没有被任何任务图模块引用。</div>
                ) : null}
              </div>
            </section>
          </section>
        ) : <div className="boundary-empty">先在左侧选择或创建一个具体任务。</div>}
      </main>
    </TaskDefinitionPage>
  );
}
