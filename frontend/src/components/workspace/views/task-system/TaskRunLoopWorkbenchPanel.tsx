"use client";

import { Save } from "lucide-react";

import {
  TaskSystemField,
  TaskSystemMultiSelectField,
  TaskSystemSelectField,
  TaskSystemToolbarButton,
  taskSystemDisplayLabel,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import type {
  RuntimeAssembly,
  SpecificTaskRecord,
  TaskExecutionPolicy,
  TaskGraphRecord,
  TaskMemoryRequestProfile,
} from "@/lib/api";

const EXECUTION_CHAIN_OPTIONS = ["single_agent_chain", "coordination_chain", "graph_run_loop"];
const RUNTIME_AGENT_SELECTION_OPTIONS = ["orchestration_default", "fixed_agent", "graph_node_binding"];
const TASK_LEVEL_OPTIONS = ["standard", "long_running", "critical"];
const TASK_PRIVILEGE_OPTIONS = ["bounded"];
const AGENT_CATEGORY_OPTIONS = ["main_agent", "system_management_agent", "worker_sub_agent"];
const DEFAULT_AGENT_OPTIONS = ["agent:0", "agent:3"];
const MEMORY_LAYER_OPTIONS = ["conversation", "state", "working", "long_term"];
const MEMORY_PRIORITY_OPTIONS = ["normal", "high"];
const MEMORY_WRITEBACK_OPTIONS = ["task_default", "task_summary_only", "session_and_durable"];
const SHARED_CONTEXT_POLICIES = ["explicit_refs_only", "shared_task_context"];
const MEMORY_SHARING_POLICIES = ["isolated_by_default", "shared_readonly"];
const WORKING_MEMORY_SCOPE_OPTIONS = ["node_scope", "graph_scope", "task_scope", "artifact_scope"];
const WORKING_MEMORY_VISIBILITY_OPTIONS = ["private_to_node", "shared_in_graph", "handoff_only", "coordinator_only", "human_review_only"];

function label(value: string) {
  const labels: Record<string, string> = {
    single_agent_chain: "单 Agent 循环",
    coordination_chain: "协调链",
    graph_run_loop: "图运行循环",
    orchestration_default: "按编排默认选择",
    fixed_agent: "固定 Agent",
    graph_node_binding: "按图节点绑定",
    standard: "标准任务",
    long_running: "长周期任务",
    critical: "关键任务",
    bounded: "受限权限",
    main_agent: "主 Agent",
    system_management_agent: "系统管理 Agent",
    worker_sub_agent: "工作子 Agent",
    "agent:0": "主 Agent",
    "agent:3": "健康管理 Agent",
    conversation: "会话记忆",
    state: "状态记忆",
    working: "工作记忆",
    long_term: "长期记忆",
    normal: "普通优先级",
    high: "高优先级",
    task_default: "任务默认写回",
    task_summary_only: "仅写回任务摘要",
    session_and_durable: "会话与长期写回",
    explicit_refs_only: "仅显式引用",
    shared_task_context: "共享任务上下文",
    isolated_by_default: "默认隔离",
    shared_readonly: "只读共享",
    node_scope: "节点范围",
    graph_scope: "图范围",
    task_scope: "任务范围",
    artifact_scope: "产物范围",
    private_to_node: "节点私有",
    shared_in_graph: "图内共享",
    handoff_only: "仅交接",
    coordinator_only: "仅协调者",
    human_review_only: "仅人工审查",
  };
  return labels[value] ?? value;
}

function includes(value: string[] | undefined, item: string) {
  return Boolean(value?.includes(item));
}

function readinessRows({
  selectedTask,
  selectedCoordination,
  executionDraft,
  memoryDraft,
  workflowAssembly,
  nodeAssembly,
}: {
  selectedTask: SpecificTaskRecord | null;
  selectedCoordination: TaskGraphRecord | null;
  executionDraft: TaskExecutionPolicy;
  memoryDraft: TaskMemoryRequestProfile;
  workflowAssembly: RuntimeAssembly | null;
  nodeAssembly: RuntimeAssembly | null;
}) {
  const hasTask = Boolean(selectedTask?.task_id);
  const hasGraphLoop = Boolean(selectedCoordination?.graph_id) || executionDraft.execution_chain_type === "graph_run_loop";
  const hasLongTermRead = includes(memoryDraft.requested_memory_layers, "long_term") && memoryDraft.allow_long_term_memory;
  const hasState = includes(memoryDraft.requested_memory_layers, "state");
  const hasWorking = includes(memoryDraft.requested_memory_layers, "working") && Boolean(memoryDraft.allow_working_memory);
  const hasWriteback = memoryDraft.writeback_policy !== "task_default" || memoryDraft.allow_long_term_memory;
  const hasAssembly = Boolean(workflowAssembly || nodeAssembly);
  return [
    { label: "任务入口", value: selectedTask?.task_title || selectedTask?.task_id || "未选择任务", ready: hasTask },
    { label: "图级循环", value: hasGraphLoop ? "已纳入任务图" : "单节点运行", ready: hasGraphLoop },
    { label: "状态记忆", value: hasState ? "已请求状态记忆" : "缺少状态记忆", ready: hasState },
    { label: "工作记忆", value: hasWorking ? "任务运行期生产状态已启用" : "未启用工作记忆", ready: hasWorking },
    { label: "长期记忆", value: hasLongTermRead ? "允许读取长期记忆" : "未启用长期连续性", ready: hasLongTermRead },
    { label: "记忆写回", value: hasWriteback ? label(memoryDraft.writeback_policy) : "任务默认", ready: hasWriteback },
    { label: "装配快照", value: hasAssembly ? "已有装配" : "请先预检装配", ready: hasAssembly },
  ];
}

export function TaskRunLoopWorkbenchPanel({
  selectedTask,
  selectedCoordination,
  executionDraft,
  setExecutionDraft,
  memoryDraft,
  setMemoryDraft,
  coordinationMemorySharingPolicy,
  setCoordinationMemorySharingPolicy,
  coordinationSharedContextPolicy,
  setCoordinationSharedContextPolicy,
  workflowAssembly,
  nodeAssembly,
  saveTaskStack,
  saveCoordinationStack,
  saving,
}: {
  selectedTask: SpecificTaskRecord | null;
  selectedCoordination: TaskGraphRecord | null;
  executionDraft: TaskExecutionPolicy;
  setExecutionDraft: (next: TaskExecutionPolicy) => void;
  memoryDraft: TaskMemoryRequestProfile;
  setMemoryDraft: (next: TaskMemoryRequestProfile) => void;
  coordinationMemorySharingPolicy: string;
  setCoordinationMemorySharingPolicy: (value: string) => void;
  coordinationSharedContextPolicy: string;
  setCoordinationSharedContextPolicy: (value: string) => void;
  workflowAssembly: RuntimeAssembly | null;
  nodeAssembly: RuntimeAssembly | null;
  saveTaskStack: () => Promise<void>;
  saveCoordinationStack: (published?: boolean) => Promise<void>;
  saving: string;
}) {
  const rows = readinessRows({
    selectedTask,
    selectedCoordination,
    executionDraft,
    memoryDraft,
    workflowAssembly,
    nodeAssembly,
  });
  const chapterContinuityReady = rows.filter((row) => row.ready).length;
  const workingPolicy: Record<string, unknown> = {
    ...(memoryDraft.working_memory_policy ?? {}),
    enabled: Boolean(memoryDraft.allow_working_memory),
    default_scope: memoryDraft.working_memory_default_scope || String(memoryDraft.working_memory_policy?.default_scope ?? "node_scope"),
    default_visibility: memoryDraft.working_memory_default_visibility || String(memoryDraft.working_memory_policy?.default_visibility ?? "private_to_node"),
    allow_dynamic_read: Boolean(memoryDraft.allow_dynamic_working_memory_read),
  };

  return (
    <section className="boundary-layer-stack task-runloop-workbench">
      <section className="boundary-card boundary-card--summary">
        <header>
          <div className="boundary-identity-stack">
            <span>运行循环 / 记忆支持</span>
            <strong>{selectedCoordination?.title || selectedTask?.task_title || "未选择任务"}</strong>
            <small>RunLoop 定义、记忆请求、上下文连续性与写回策略</small>
          </div>
          <div className="boundary-actions">
            <TaskSystemToolbarButton disabled={saving === "task-stack"} onClick={() => { void saveTaskStack(); }} variant="primary">
              <Save size={15} />保存任务运行配置
            </TaskSystemToolbarButton>
            <TaskSystemToolbarButton disabled={saving === "coordination" || !selectedCoordination} onClick={() => { void saveCoordinationStack(false); }}>
              <Save size={15} />保存图上下文策略
            </TaskSystemToolbarButton>
          </div>
        </header>
        <div className="boundary-metric-grid">
          <ReadinessTile label="连续运行就绪" value={`${chapterContinuityReady}/${rows.length}`} ready={chapterContinuityReady >= 6} />
          <ReadinessTile label="执行链" value={label(executionDraft.execution_chain_type)} ready={Boolean(executionDraft.execution_chain_type)} />
          <ReadinessTile label="记忆优先级" value={label(memoryDraft.memory_priority)} ready={Boolean(memoryDraft.memory_priority)} />
          <ReadinessTile label="工作记忆" value={memoryDraft.allow_working_memory ? label(String(workingPolicy.default_scope)) : "关闭"} ready={Boolean(memoryDraft.allow_working_memory)} />
        </div>
      </section>

      <section className="task-runloop-workbench__grid">
        <section className="boundary-card">
          <header><strong>执行循环定义</strong><span>Agent 循环 / 图运行循环</span></header>
          <div className="boundary-form">
            <TaskSystemSelectField
              label="执行链类型"
              value={executionDraft.execution_chain_type}
              options={EXECUTION_CHAIN_OPTIONS}
              onChange={(value) => setExecutionDraft({ ...executionDraft, execution_chain_type: value })}
              formatOption={label}
            />
            <TaskSystemSelectField
              label="Agent 选择"
              value={executionDraft.runtime_agent_selection_policy || "orchestration_default"}
              options={RUNTIME_AGENT_SELECTION_OPTIONS}
              onChange={(value) => setExecutionDraft({ ...executionDraft, runtime_agent_selection_policy: value })}
              formatOption={label}
            />
            <TaskSystemSelectField
              label="默认 Agent"
              value={executionDraft.default_agent_id || "agent:0"}
              options={DEFAULT_AGENT_OPTIONS}
              onChange={(value) => setExecutionDraft({ ...executionDraft, default_agent_id: value })}
              formatOption={label}
            />
            <TaskSystemSelectField
              label="任务等级"
              value={executionDraft.task_level || "standard"}
              options={TASK_LEVEL_OPTIONS}
              onChange={(value) => setExecutionDraft({ ...executionDraft, task_level: value })}
              formatOption={label}
            />
            <TaskSystemSelectField
              label="权限口径"
              value={executionDraft.task_privilege || "bounded"}
              options={TASK_PRIVILEGE_OPTIONS}
              onChange={(value) => setExecutionDraft({ ...executionDraft, task_privilege: value })}
              formatOption={label}
            />
            <TaskSystemMultiSelectField
              label="允许 Agent"
              value={executionDraft.allowed_agent_categories ?? []}
              options={AGENT_CATEGORY_OPTIONS}
              onChange={(value) => setExecutionDraft({ ...executionDraft, allowed_agent_categories: value })}
              formatOption={label}
              wide
            />
            <label className="boundary-check">
              <input
                checked={executionDraft.allow_worker_agent_spawn}
                onChange={(event) => setExecutionDraft({ ...executionDraft, allow_worker_agent_spawn: event.target.checked })}
                type="checkbox"
              />
              允许运行时生成工作子 Agent
            </label>
            <TaskSystemField label="运行备注" wide>
              <textarea value={executionDraft.notes} onChange={(event) => setExecutionDraft({ ...executionDraft, notes: event.target.value })} />
            </TaskSystemField>
          </div>
        </section>

        <section className="boundary-card">
          <header><strong>记忆与连续性</strong><span>记忆请求</span></header>
          <div className="boundary-form">
            <TaskSystemMultiSelectField
              label="请求记忆层"
              value={memoryDraft.requested_memory_layers ?? []}
              options={MEMORY_LAYER_OPTIONS}
              onChange={(value) => setMemoryDraft({ ...memoryDraft, requested_memory_layers: value })}
              formatOption={label}
              wide
            />
            <TaskSystemSelectField
              label="记忆优先级"
              value={memoryDraft.memory_priority}
              options={MEMORY_PRIORITY_OPTIONS}
              onChange={(value) => setMemoryDraft({ ...memoryDraft, memory_priority: value })}
              formatOption={label}
            />
            <TaskSystemSelectField
              label="写回策略"
              value={memoryDraft.writeback_policy}
              options={MEMORY_WRITEBACK_OPTIONS}
              onChange={(value) => setMemoryDraft({ ...memoryDraft, writeback_policy: value })}
              formatOption={label}
            />
            <label className="boundary-check">
              <input
                checked={memoryDraft.allow_long_term_memory}
                onChange={(event) => setMemoryDraft({ ...memoryDraft, allow_long_term_memory: event.target.checked })}
                type="checkbox"
              />
              允许长期记忆参与连续执行
            </label>
            <label className="boundary-check">
              <input
                checked={Boolean(memoryDraft.allow_working_memory)}
                onChange={(event) => {
                  const enabled = event.target.checked;
                  const layers = new Set(memoryDraft.requested_memory_layers ?? []);
                  if (enabled) {
                    layers.add("working");
                  } else {
                    layers.delete("working");
                  }
                  setMemoryDraft({
                    ...memoryDraft,
                    requested_memory_layers: Array.from(layers),
                    allow_working_memory: enabled,
                    working_memory_policy: {
                      ...workingPolicy,
                      enabled,
                    },
                  });
                }}
                type="checkbox"
              />
              启用任务工作记忆层
            </label>
            <label className="boundary-check">
              <input
                checked={Boolean(memoryDraft.allow_dynamic_working_memory_read)}
                disabled={!memoryDraft.allow_working_memory}
                onChange={(event) => setMemoryDraft({
                  ...memoryDraft,
                  allow_dynamic_working_memory_read: event.target.checked,
                  working_memory_policy: {
                    ...workingPolicy,
                    allow_dynamic_read: event.target.checked,
                  },
                })}
                type="checkbox"
              />
              允许子 Agent 申请动态读取
            </label>
            <TaskSystemField label="记忆主题" wide>
              <textarea
                value={(memoryDraft.requested_topics ?? []).join("\n")}
                onChange={(event) => setMemoryDraft({
                  ...memoryDraft,
                  requested_topics: event.target.value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean),
                })}
              />
            </TaskSystemField>
            <TaskSystemField label="记忆范围提示" wide>
              <input value={memoryDraft.memory_scope_hint} onChange={(event) => setMemoryDraft({ ...memoryDraft, memory_scope_hint: event.target.value })} />
            </TaskSystemField>
          </div>
        </section>
      </section>

      <section className="boundary-card">
        <header><strong>工作记忆策略</strong><span>工作记忆策略</span></header>
        <div className="boundary-form">
          <TaskSystemField label="策略画像 ID">
            <input
              value={memoryDraft.working_memory_policy_profile_id ?? ""}
              onChange={(event) => setMemoryDraft({
                ...memoryDraft,
                working_memory_policy_profile_id: event.target.value,
                working_memory_policy: {
                  ...workingPolicy,
                  profile_id: event.target.value,
                },
              })}
            />
          </TaskSystemField>
          <TaskSystemSelectField
            label="默认范围"
            value={String(workingPolicy.default_scope)}
            options={WORKING_MEMORY_SCOPE_OPTIONS}
            onChange={(value) => setMemoryDraft({
              ...memoryDraft,
              working_memory_default_scope: value,
              working_memory_policy: {
                ...workingPolicy,
                default_scope: value,
              },
            })}
            formatOption={label}
          />
          <TaskSystemSelectField
            label="默认可见性"
            value={String(workingPolicy.default_visibility)}
            options={WORKING_MEMORY_VISIBILITY_OPTIONS}
            onChange={(value) => setMemoryDraft({
              ...memoryDraft,
              working_memory_default_visibility: value,
              working_memory_policy: {
                ...workingPolicy,
                default_visibility: value,
              },
            })}
            formatOption={label}
          />
          <label className="boundary-check">
            <input
              checked={Boolean(workingPolicy.finalize_requires_human_review ?? true)}
              onChange={(event) => setMemoryDraft({
                ...memoryDraft,
                working_memory_policy: {
                  ...workingPolicy,
                  finalize_requires_human_review: event.target.checked,
                },
              })}
              type="checkbox"
            />
            任务收束需要人工复核
          </label>
          <label className="boundary-check">
            <input
              checked={Boolean(workingPolicy.promotion_requires_human_review ?? true)}
              onChange={(event) => setMemoryDraft({
                ...memoryDraft,
                working_memory_policy: {
                  ...workingPolicy,
                  promotion_requires_human_review: event.target.checked,
                },
              })}
              type="checkbox"
            />
            晋升任务长期记忆需要人工确认
          </label>
        </div>
        <div className="boundary-kv">
          <p><span>隔离原则</span><strong>任务工作记忆不自动写全局长期记忆</strong></p>
          <p><span>主归属</span><strong>任务图节点 owner_node_id</strong></p>
          <p><span>动态读取</span><strong>{memoryDraft.allow_dynamic_working_memory_read ? "RunLoop 审批" : "关闭"}</strong></p>
          <p><span>收束去向</span><strong>归档 / 晋升候选 / 废弃 / 冲突队列</strong></p>
        </div>
      </section>

      <section className="task-runloop-workbench__grid task-runloop-workbench__grid--wide">
        <section className="boundary-card">
          <header><strong>多 Agent 上下文策略</strong><span>{selectedCoordination?.graph_id || "未选择任务图"}</span></header>
          <div className="boundary-form">
            <TaskSystemSelectField
              label="共享上下文"
              value={coordinationSharedContextPolicy}
              options={SHARED_CONTEXT_POLICIES}
              onChange={setCoordinationSharedContextPolicy}
              formatOption={label}
            />
            <TaskSystemSelectField
              label="记忆共享"
              value={coordinationMemorySharingPolicy}
              options={MEMORY_SHARING_POLICIES}
              onChange={setCoordinationMemorySharingPolicy}
              formatOption={label}
            />
          </div>
          <div className="boundary-kv">
            <p><span>图运行模式</span><strong>{String(selectedCoordination?.runtime_policy?.coordination_mode ?? "") ? label(String(selectedCoordination?.runtime_policy?.coordination_mode ?? "")) : "未选择"}</strong></p>
            <p><span>节点数</span><strong>{selectedCoordination?.nodes?.length ?? 0}</strong></p>
            <p><span>共享上下文</span><strong>{String(selectedCoordination?.context_policy?.shared_context_policy ?? "") || "未配置"}</strong></p>
            <p><span>记忆共享</span><strong>{String(selectedCoordination?.context_policy?.memory_sharing_policy ?? "") || "未配置"}</strong></p>
          </div>
        </section>

        <section className="boundary-card">
          <header><strong>章节/长任务循环就绪度</strong><span>就绪度</span></header>
          <div className="boundary-task-table">
            {rows.map((row) => (
              <article className={row.ready ? "task-runloop-workbench__ready-row" : ""} key={row.label}>
                <strong>{row.label}</strong>
                <span>{row.ready ? "已就绪" : "待处理"}</span>
                <small>{row.value}</small>
              </article>
            ))}
          </div>
        </section>
      </section>

      <section className="boundary-card">
        <header><strong>当前装配对运行循环的可见输入</strong><span>上下文 / 循环策略</span></header>
        <div className="task-runloop-workbench__assembly">
          <RuntimeAssemblySummary title="单任务装配" assembly={workflowAssembly} />
          <RuntimeAssemblySummary title="节点装配" assembly={nodeAssembly} />
        </div>
      </section>
    </section>
  );
}

function RuntimeAssemblySummary({ title, assembly }: { title: string; assembly: RuntimeAssembly | null }) {
  return (
    <article>
      <header>
        <strong>{title}</strong>
        <span>{assembly?.assembly_id || "未生成"}</span>
      </header>
      <div className="boundary-kv">
        <p><span>Agent</span><strong>{assembly?.agent_id || "未装配"}</strong></p>
        <p><span>运行通道</span><strong>{taskSystemDisplayLabel(assembly?.runtime_lane, "未装配")}</strong></p>
        <p><span>上下文段</span><strong>{assembly?.context_sections?.length ?? 0}</strong></p>
        <p><span>输出契约</span><strong>{assembly?.output_contracts?.length ?? 0}</strong></p>
        <p><span>循环策略</span><strong>{Object.keys(assembly?.loop_policy ?? {}).length}</strong></p>
      </div>
    </article>
  );
}

function ReadinessTile({ label, value, ready }: { label: string; value: string; ready: boolean }) {
  return (
    <article className={ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{ready ? "已就绪" : "待处理"}</small>
    </article>
  );
}
