"use client";

import {
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  FileText,
  ListChecks,
  PencilLine,
  PlayCircle,
  Send,
  Square,
  Target,
  TriangleAlert,
} from "lucide-react";
import React, { useMemo, useState } from "react";

import type { HarnessTaskRunLiveMonitor, PublicTodoItem } from "@/lib/api";
import type { ProjectionRenderBlock, TodoPlanProjectionBlock } from "@/lib/projection/chronological";
import type { Message } from "@/lib/store/types";

type TaskModeKind = "goal" | "plan" | "todo";
type TodoStatusTone = "active" | "blocked" | "done" | "pending";

type TaskModePanelProps = {
  active?: boolean;
  messages: Message[];
  monitor?: HarnessTaskRunLiveMonitor | null;
  onCancelTask: () => Promise<void> | void;
  onContinueTask: () => Promise<void> | void;
  onSubmitRevision: (message: string) => Promise<void> | void;
};

type PlanStep = {
  title: string;
  detail: string;
  status: string;
};

type TaskModeContext = {
  activeMode: TaskModeKind;
  contract: Record<string, unknown>;
  goal: Record<string, unknown>;
  plan: Record<string, unknown>;
  todo: Record<string, unknown>;
  tabs: TaskModeKind[];
  taskRunId: string;
  title: string;
  status: string;
  waitReason: string;
};

type TodoPanelSnapshot = {
  activeItem: PublicTodoItem | null;
  block: TodoPlanProjectionBlock | null;
  completed: number;
  items: PublicTodoItem[];
  percent: number;
  tone: TodoStatusTone;
  total: number;
};

const TAB_LABELS: Record<TaskModeKind, string> = {
  goal: "Goal",
  plan: "Plan",
  todo: "Todo",
};

export function SessionTaskModePanel({
  active = false,
  messages,
  monitor,
  onCancelTask,
  onContinueTask,
  onSubmitRevision,
}: TaskModePanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [selectedTab, setSelectedTab] = useState<TaskModeKind>("goal");
  const [revisionDraft, setRevisionDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const context = useMemo(() => taskModeContextFromMonitor(monitor), [monitor]);
  const latestTodo = useMemo(() => latestTodoSnapshotFromMessages(messages), [messages]);
  const todoSnapshot = useMemo(
    () => latestTodo.total ? latestTodo : todoSnapshotFromContract(context?.todo ?? {}),
    [context?.todo, latestTodo],
  );

  if (!active || !context || !context.tabs.length) {
    return null;
  }

  const activeTab = context.tabs.includes(selectedTab) ? selectedTab : context.activeMode;
  const progressText = todoSnapshot.total ? `${todoSnapshot.completed}/${todoSnapshot.total}` : "";
  const headline = taskModeHeadline(context, activeTab, todoSnapshot);
  const canContinue = ["waiting_approval", "waiting_executor", "blocked"].includes(context.status);

  async function submitRevision() {
    const draft = revisionDraft.trim();
    if (!draft || submitting) {
      return;
    }
    setSubmitting(true);
    try {
      await onSubmitRevision(revisionInstruction(activeTab, draft));
      setRevisionDraft("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <aside className="task-mode-tail-shell" aria-label="任务模式动态尾">
      <section className={`task-mode-tail task-mode-tail--${activeTab}${collapsed ? " task-mode-tail--collapsed" : ""}`}>
        <header className="task-mode-tail__header">
          <button
            aria-expanded={!collapsed}
            className="task-mode-tail__collapse"
            onClick={() => setCollapsed((value) => !value)}
            title={collapsed ? "展开任务模式尾" : "收起任务模式尾"}
            type="button"
          >
            <span className="task-mode-tail__mark" aria-hidden="true">{tabIcon(activeTab)}</span>
            <span className="task-mode-tail__title">
              <strong>{TAB_LABELS[activeTab]} Mode</strong>
              <span>{headline}</span>
            </span>
            {progressText ? <span className="task-mode-tail__progress-text">{progressText}</span> : null}
            <ChevronDown className="task-mode-tail__chevron" size={16} aria-hidden="true" />
          </button>

          <div className="task-mode-tail__tabs" aria-label="任务模式上下文">
            {context.tabs.map((tab) => (
              <button
                aria-current={activeTab === tab ? "page" : undefined}
                className={activeTab === tab ? "task-mode-tail__tab task-mode-tail__tab--active" : "task-mode-tail__tab"}
                key={tab}
                onClick={() => setSelectedTab(tab)}
                type="button"
              >
                {tabIcon(tab)}
                <span>{TAB_LABELS[tab]}</span>
              </button>
            ))}
          </div>

          <div className="task-mode-tail__actions">
            {canContinue ? (
              <button onClick={() => void onContinueTask()} type="button">
                <PlayCircle size={14} />
                <span>继续</span>
              </button>
            ) : null}
            <button className="task-mode-tail__actions-danger" onClick={() => void onCancelTask()} type="button">
              <Square size={13} />
              <span>取消</span>
            </button>
          </div>
        </header>

        {todoSnapshot.total ? (
          <div className="task-mode-tail__progress" aria-hidden="true">
            <span style={{ width: `${todoSnapshot.percent}%` }} />
          </div>
        ) : null}

        {!collapsed ? (
          <div className="task-mode-tail__body">
            {activeTab === "goal" ? <GoalContractView context={context} /> : null}
            {activeTab === "plan" ? <PlanContractView context={context} /> : null}
            {activeTab === "todo" ? <TodoTableView snapshot={todoSnapshot} /> : null}

            <div className="task-mode-tail__revision" aria-label={`${TAB_LABELS[activeTab]} 修改指令`}>
              <label>
                <PencilLine size={14} />
                <span>{revisionLabel(activeTab)}</span>
              </label>
              <div>
                <input
                  aria-label={`${TAB_LABELS[activeTab]} 修改说明`}
                  disabled={submitting}
                  onChange={(event) => setRevisionDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void submitRevision();
                    }
                  }}
                  placeholder={revisionPlaceholder(activeTab)}
                  value={revisionDraft}
                />
                <button disabled={!revisionDraft.trim() || submitting} onClick={() => void submitRevision()} type="button">
                  <Send size={13} />
                  <span>提交</span>
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </aside>
  );
}

function GoalContractView({ context }: { context: TaskModeContext }) {
  const goal = context.goal;
  const rows = [
    ["目标", text(goal.user_visible_goal) || text(goal.task_run_goal) || context.title],
    ["成功定义", text(goal.success_definition)],
    ["证据要求", evidenceLabel(recordValue(goal.evidence_contract))],
    ["运行状态", statusLabel(context.status, context.waitReason)],
  ].filter((row) => row[1]);

  return (
    <div className="task-mode-goal-contract">
      {rows.map(([label, value]) => (
        <div className="task-mode-goal-contract__row" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function PlanContractView({ context }: { context: TaskModeContext }) {
  const steps = planStepsFromContract(context.plan);
  const strategy = text(context.plan.strategy_summary) || text(context.plan.summary) || context.title;
  return (
    <div className="task-mode-plan-page">
      <div className="task-mode-plan-page__summary">
        <span>策略</span>
        <strong>{strategy || "等待 agent 建立计划"}</strong>
      </div>
      <ol className="task-mode-plan-page__steps">
        {steps.length ? steps.map((step, index) => (
          <li key={`${step.title}:${index}`}>
            <span>{index + 1}</span>
            <div>
              <strong>{step.title}</strong>
              {step.detail ? <small>{step.detail}</small> : null}
            </div>
            <em>{planStepStatusLabel(step.status)}</em>
          </li>
        )) : (
          <li className="task-mode-plan-page__empty">
            <span>1</span>
            <div><strong>计划等待生成</strong><small>agent 继续执行后会把策略拆成可追踪步骤。</small></div>
            <em>待定</em>
          </li>
        )}
      </ol>
    </div>
  );
}

function TodoTableView({ snapshot }: { snapshot: TodoPanelSnapshot }) {
  if (!snapshot.total) {
    return (
      <div className="task-mode-tail__empty">
        <ListChecks size={16} />
        <span>Todo 表格等待 agent 写入。</span>
      </div>
    );
  }
  return (
    <div className="task-mode-todo-table-wrap">
      <table className="task-mode-todo-table">
        <thead>
          <tr>
            <th>序号</th>
            <th>事项</th>
            <th>状态</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          {snapshot.items.map((item, index) => {
            const status = normalizedTodoStatus(item);
            const active = text(item.todo_id) === text(snapshot.block?.activeItemId) || status === "in_progress";
            const tone = todoStatusTone(status, active);
            return (
              <tr className={`task-mode-todo-table__row task-mode-todo-table__row--${tone}`} key={text(item.todo_id) || `${index}:${text(item.content)}`}>
                <td>{index + 1}</td>
                <td>
                  <span>{active ? text(item.active_form || item.content) : text(item.content)}</span>
                </td>
                <td><span>{todoStatusIcon(tone)}{todoStatusLabel(status, active)}</span></td>
                <td>{text(item.notes) || "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function taskModeContextFromMonitor(monitor: HarnessTaskRunLiveMonitor | null | undefined): TaskModeContext | null {
  const monitorRecord = recordValue(monitor);
  if (!Object.keys(monitorRecord).length) {
    return null;
  }
  const taskRun = recordValue(monitorRecord.task_run);
  const diagnostics = recordValue(taskRun.diagnostics);
  const contract = firstRecord(diagnostics.contract, diagnostics.task_run_contract, monitorRecord.contract);
  const workModes = arrayRecords(contract.work_modes);
  const primaryRef = text(contract.primary_work_mode_instance_id) || text(recordValue(contract.container_contract).primary_work_mode_ref);
  const primaryModeRecord = workModes.find((item) => text(item.mode_instance_id) === primaryRef) ?? workModes[0] ?? {};
  const activeMode = normalizeModeKind(text(primaryModeRecord.mode_kind)) ?? "goal";
  const goal = firstRecord(contract.goal_contract, modeContract(workModes, "goal"));
  const plan = firstRecord(contract.plan_contract, modeContract(workModes, "plan"));
  const todo = firstRecord(modeContract(workModes, "todo"), contract.todo_contract);
  const tabs = uniqueModes([
    goalHasContent(goal) ? "goal" : null,
    planHasContent(plan) ? "plan" : null,
    todoHasContent(todo) ? "todo" : null,
    activeMode,
  ]);
  const taskRunId = text(taskRun.task_run_id) || text(monitorRecord.task_run_id);
  const title = text(goal.user_visible_goal)
    || text(goal.task_run_goal)
    || text(contract.user_visible_goal)
    || text(contract.task_run_goal)
    || text(monitorRecord.title)
    || "当前任务";
  return {
    activeMode: tabs.includes(activeMode) ? activeMode : tabs[0] ?? "goal",
    contract,
    goal,
    plan,
    todo,
    tabs,
    taskRunId,
    title,
    status: text(monitorRecord.status) || text(taskRun.status),
    waitReason: text(monitorRecord.wait_reason) || text(diagnostics.wait_reason),
  };
}

function latestTodoSnapshotFromMessages(messages: Message[]): TodoPanelSnapshot {
  const block = latestTodoPlanFromMessages(messages);
  return todoSnapshotFromItems(block?.items ?? [], block);
}

function todoSnapshotFromContract(contract: Record<string, unknown>): TodoPanelSnapshot {
  const items = arrayRecords(contract.items).map((item): PublicTodoItem => ({
    todo_id: text(item.todo_id) || text(item.item_id),
    content: text(item.content) || text(item.title),
    active_form: text(item.active_form),
    status: text(item.status) || "pending",
    notes: text(item.notes) || text(item.detail),
  })).filter((item) => text(item.content));
  const block = items.length ? {
    kind: "todo_plan" as const,
    id: text(contract.todo_list_id) || "contract-todo",
    title: "Todo",
    detail: "",
    state: "waiting",
    statusKind: "todo_plan",
    planId: text(contract.todo_list_id) || "contract-todo",
    activeItemId: text(contract.active_item_id),
    items,
    offset: 0,
  } : null;
  return todoSnapshotFromItems(items, block);
}

function todoSnapshotFromItems(itemsInput: PublicTodoItem[], block: TodoPlanProjectionBlock | null): TodoPanelSnapshot {
  const items = itemsInput.filter((item) => text(item.content));
  const completed = items.filter((item) => normalizedTodoStatus(item) === "completed").length;
  const activeItem = block
    ? items.find((item) => text(item.todo_id) === text(block.activeItemId)) ?? items.find((item) => normalizedTodoStatus(item) === "in_progress") ?? null
    : null;
  const blocked = items.some((item) => normalizedTodoStatus(item) === "blocked");
  const total = items.length;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  return {
    activeItem,
    block,
    completed,
    items,
    percent,
    tone: blocked ? "blocked" : activeItem ? "active" : total && completed === total ? "done" : "pending",
    total,
  };
}

function latestTodoPlanFromMessages(messages: Message[]): TodoPlanProjectionBlock | null {
  let latestBlock: TodoPlanProjectionBlock | null = null;
  let latestMessageIndex = -1;
  messages.forEach((message, messageIndex) => {
    const blocks = todoPlanBlocks(message.projectionView?.blocks ?? []);
    for (const block of blocks) {
      if (!block.items?.some((item) => text(item.content))) {
        continue;
      }
      if (!latestBlock || messageIndex > latestMessageIndex || (messageIndex === latestMessageIndex && block.offset >= latestBlock.offset)) {
        latestBlock = block;
        latestMessageIndex = messageIndex;
      }
    }
  });
  return latestBlock;
}

function todoPlanBlocks(blocks: ProjectionRenderBlock[]): TodoPlanProjectionBlock[] {
  const result: TodoPlanProjectionBlock[] = [];
  for (const block of blocks) {
    if (block.kind === "todo_plan") {
      result.push(block);
      continue;
    }
    if (block.kind === "activity_archive") {
      result.push(...todoPlanBlocks(block.blocks));
    }
  }
  return result;
}

function planStepsFromContract(plan: Record<string, unknown>): PlanStep[] {
  const rawSteps = arrayUnknown(plan.major_steps).length ? arrayUnknown(plan.major_steps) : arrayUnknown(plan.steps);
  return rawSteps.map((item): PlanStep => {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      const record = item as Record<string, unknown>;
      return {
        title: text(record.title) || text(record.name) || text(record.step) || "未命名步骤",
        detail: text(record.detail) || text(record.description),
        status: text(record.status) || "pending",
      };
    }
    return { title: text(item), detail: "", status: "pending" };
  }).filter((item) => item.title);
}

function modeContract(workModes: Record<string, unknown>[], modeKind: TaskModeKind) {
  const mode = workModes.find((item) => text(item.mode_kind) === modeKind);
  return recordValue(mode?.contract);
}

function uniqueModes(items: Array<TaskModeKind | null>): TaskModeKind[] {
  const result: TaskModeKind[] = [];
  for (const item of items) {
    if (!item || result.includes(item)) {
      continue;
    }
    result.push(item);
  }
  return result;
}

function normalizeModeKind(value: string): TaskModeKind | null {
  if (value === "goal" || value === "plan" || value === "todo") {
    return value;
  }
  return null;
}

function firstRecord(...values: unknown[]) {
  for (const value of values) {
    const record = recordValue(value);
    if (Object.keys(record).length) {
      return record;
    }
  }
  return {};
}

function goalHasContent(goal: Record<string, unknown>) {
  return Boolean(text(goal.user_visible_goal) || text(goal.task_run_goal) || text(goal.success_definition));
}

function planHasContent(plan: Record<string, unknown>) {
  return Boolean(text(plan.strategy_summary) || arrayUnknown(plan.major_steps).length || arrayUnknown(plan.steps).length);
}

function todoHasContent(todo: Record<string, unknown>) {
  return arrayRecords(todo.items).length > 0;
}

function taskModeHeadline(context: TaskModeContext, activeTab: TaskModeKind, todo: TodoPanelSnapshot) {
  if (activeTab === "goal") {
    return context.title;
  }
  if (activeTab === "plan") {
    return text(context.plan.strategy_summary) || "计划页面已绑定";
  }
  const activeText = text(todo.activeItem?.active_form || todo.activeItem?.content);
  if (activeText) {
    return activeText;
  }
  return todo.total ? "Todo 表格已同步" : "等待 Todo 表格";
}

function revisionInstruction(tab: TaskModeKind, draft: string) {
  if (tab === "goal") {
    return `修改当前 Goal 契约：${draft}`;
  }
  if (tab === "plan") {
    return `调整当前 Plan：${draft}`;
  }
  return `更新当前 Todo 列表：${draft}`;
}

function revisionLabel(tab: TaskModeKind) {
  if (tab === "goal") return "修改 Goal 契约";
  if (tab === "plan") return "调整 Plan";
  return "更新 Todo";
}

function revisionPlaceholder(tab: TaskModeKind) {
  if (tab === "goal") return "写下新的目标边界、成功定义或取消原因";
  if (tab === "plan") return "写下要插入、删除或重排的计划步骤";
  return "写下要新增、完成、阻塞或修改的 Todo";
}

function evidenceLabel(evidence: Record<string, unknown>) {
  if (!Object.keys(evidence).length) return "";
  if (evidence.evidence_required === true) return "需要证据";
  if (evidence.evidence_required === false) return "不强制";
  return text(evidence.source);
}

function statusLabel(status: string, waitReason: string) {
  if (status === "waiting_approval" && waitReason === "task_launch_supervision") return "等待启动确认";
  if (status === "waiting_executor") return "等待继续";
  if (status === "running") return "运行中";
  if (status === "completed") return "已完成";
  return status || "同步中";
}

function planStepStatusLabel(status: string) {
  if (status === "completed") return "完成";
  if (status === "in_progress" || status === "running") return "进行中";
  if (status === "blocked") return "阻塞";
  return "待处理";
}

function normalizedTodoStatus(item: PublicTodoItem) {
  return text(item.status).toLowerCase();
}

function todoStatusTone(status: string, active: boolean): TodoStatusTone {
  if (status === "completed") return "done";
  if (status === "blocked") return "blocked";
  if (active || status === "in_progress") return "active";
  return "pending";
}

function todoStatusIcon(tone: TodoStatusTone) {
  if (tone === "done") return <CheckCircle2 size={13} />;
  if (tone === "active") return <PlayCircle size={13} />;
  if (tone === "blocked") return <TriangleAlert size={13} />;
  return <CircleDashed size={13} />;
}

function todoStatusLabel(status: string, active: boolean) {
  if (status === "completed") return "完成";
  if (status === "blocked") return "阻塞";
  if (active || status === "in_progress") return "进行中";
  return "待处理";
}

function tabIcon(tab: TaskModeKind) {
  if (tab === "goal") return <Target size={14} />;
  if (tab === "plan") return <FileText size={14} />;
  return <ListChecks size={14} />;
}

function arrayRecords(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function arrayUnknown(value: unknown) {
  return Array.isArray(value) ? value : [];
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown) {
  return String(value ?? "").trim();
}
