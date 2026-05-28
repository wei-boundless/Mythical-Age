"use client";

import { Play, Save, Trash2 } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import type { EngagementEventRecord, EngagementRunRecord, RegisteredEngagementPlan, TaskGraphRecord } from "@/lib/api";

import { TaskDefinitionPage } from "../TaskSystemPages";
import {
  TaskSystemField as Field,
  TaskSystemSelectField as SelectField,
  TaskSystemToolbarButton as ToolbarButton,
} from "../TaskSystemWorkbenchUi";

type LayerNavItem<T extends string> = {
  detail: string;
  label: string;
  meta: string;
  value: T;
};

type EngagementPlanPanel = "contract";

function JsonField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  return (
    <Field label={label} wide>
      <textarea rows={8} value={value} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

function planSubtitle(plan: RegisteredEngagementPlan) {
  return `${plan.task_environment_id || "未绑定环境"} / ${plan.execution_strategy?.kind || "未配置策略"} / ${plan.runtime_profile?.runtime_mode || "未配置模式"}`;
}

export function EngagementPlanLibraryPage({
  engagementPlanDraft,
  engagementPlanJsonText,
  engagementPlanJsonError,
  engagementPlans,
  environmentOptions,
  taskGraphs,
  onCreatePlan,
  onDeletePlan,
  onSavePlan,
  onSelectPlan,
  onSetEngagementPlanDraft,
  onSetEngagementPlanJsonText,
  onStartPlan,
  onSyncRunCloseout,
  planRuns,
  runEvents,
  saving,
  selectedEngagementPlan,
  selectedEngagementPlanId,
  taskDetailPanelItems,
}: {
  engagementPlanDraft: RegisteredEngagementPlan;
  engagementPlanJsonText: string;
  engagementPlanJsonError: string;
  engagementPlans: RegisteredEngagementPlan[];
  environmentOptions: Array<{ label: string; value: string }>;
  taskGraphs: TaskGraphRecord[];
  onCreatePlan: () => void;
  onDeletePlan: () => void;
  onSavePlan: () => void;
  onSelectPlan: (planId: string) => void;
  onSetEngagementPlanDraft: Dispatch<SetStateAction<RegisteredEngagementPlan>>;
  onSetEngagementPlanJsonText: (value: string) => void;
  onStartPlan: () => void | Promise<void>;
  onSyncRunCloseout: (engagementRunId: string) => void | Promise<void>;
  planRuns: EngagementRunRecord[];
  runEvents: EngagementEventRecord[];
  saving: string;
  selectedEngagementPlan: RegisteredEngagementPlan | null;
  selectedEngagementPlanId: string;
  taskDetailPanelItems: Array<LayerNavItem<EngagementPlanPanel>>;
}) {
  const environmentIds = environmentOptions.map((item) => item.value);
  const environmentLabel = (value: string) => environmentOptions.find((item) => item.value === value)?.label || value;
  const runtimeMode = String(engagementPlanDraft.runtime_profile?.runtime_mode || "professional");
  const startupPolicy = engagementPlanDraft.execution_strategy?.startup_policy ?? {};
  const selectedGraphId = String(startupPolicy.graph_id ?? startupPolicy.task_graph_id ?? "");
  const graphOptions = taskGraphs.map((item) => item.graph_id);
  const graphLabel = (value: string) => {
    const graph = taskGraphs.find((item) => item.graph_id === value);
    if (!graph) return value || "未绑定任务图";
    return `${graph.title || graph.graph_id} · ${graph.graph_kind} · ${graph.graph_id}`;
  };

  return (
    <TaskDefinitionPage>
      <aside className="task-management-directory">
        <div className="task-management-directory__head">
          <span>承接计划</span>
          <strong>任务启动契约</strong>
          <ToolbarButton disabled={saving === "engagement-plan-create"} onClick={onCreatePlan}>
            新计划
          </ToolbarButton>
        </div>
        <div className="boundary-list">
          {engagementPlans.map((plan) => (
            <button
              className={plan.plan_id === selectedEngagementPlanId ? "boundary-list-row boundary-list-row--active task-domain-task-row" : "boundary-list-row task-domain-task-row"}
              key={plan.plan_id}
              onClick={() => onSelectPlan(plan.plan_id)}
              type="button"
            >
              <strong>{plan.title}</strong>
              <span>{plan.status}</span>
              <small>{planSubtitle(plan)}</small>
            </button>
          ))}
          {!engagementPlans.length ? <div className="boundary-empty">当前没有承接计划。</div> : null}
        </div>
      </aside>

      <main className="task-management-workbench">
        <header className="task-management-titlebar">
          <div>
            <span>任务承接计划</span>
            <h3>{selectedEngagementPlan ? engagementPlanDraft.title || selectedEngagementPlan.title : "未选择计划"}</h3>
            <p>承接计划定义系统可启动的成型任务契约。环境、执行策略和运行模式由计划绑定，启动请求不能覆盖。</p>
          </div>
          <div className="boundary-actions">
            <ToolbarButton disabled={saving === "engagement-plan-start" || !selectedEngagementPlan} onClick={() => void onStartPlan()}>
              <Play size={15} />启动
            </ToolbarButton>
            <ToolbarButton disabled={saving === "engagement-plan-delete" || !selectedEngagementPlan} onClick={onDeletePlan}>
              <Trash2 size={15} />删除
            </ToolbarButton>
            <ToolbarButton disabled={saving === "engagement-plan-save"} onClick={onSavePlan} variant="primary">
              <Save size={15} />保存计划
            </ToolbarButton>
          </div>
        </header>

        <section className="boundary-layer-stack">
          <nav className="task-system-layer-nav task-system-layer-nav--secondary" aria-label="承接计划配置">
            {taskDetailPanelItems.map((item) => (
              <button className="task-system-layer-nav__item task-system-layer-nav__item--active" key={item.value} type="button">
                <span>{item.label}</span>
                <strong>{item.meta}</strong>
                <small>{item.detail}</small>
              </button>
            ))}
          </nav>

          <div className="boundary-form">
            <Field label="计划 ID">
              <input value={engagementPlanDraft.plan_id} onChange={(event) => onSetEngagementPlanDraft((draft) => ({ ...draft, plan_id: event.target.value }))} />
            </Field>
            <Field label="标题">
              <input value={engagementPlanDraft.title} onChange={(event) => onSetEngagementPlanDraft((draft) => ({ ...draft, title: event.target.value }))} />
            </Field>
            <SelectField
              label="任务环境"
              value={engagementPlanDraft.task_environment_id}
              options={environmentIds}
              formatOption={environmentLabel}
              onChange={(value) => onSetEngagementPlanDraft((draft) => ({ ...draft, task_environment_id: value }))}
            />
            <SelectField
              label="运行模式"
              value={runtimeMode}
              options={["role", "standard", "professional", "custom"]}
              onChange={(value) => onSetEngagementPlanDraft((draft) => ({ ...draft, runtime_profile: { ...draft.runtime_profile, runtime_mode: value } }))}
            />
            <SelectField
              label="任务图"
              value={selectedGraphId}
              options={graphOptions}
              formatOption={graphLabel}
              onChange={(value) => onSetEngagementPlanDraft((draft) => ({
                ...draft,
                execution_strategy: {
                  kind: "graph_task_run",
                  startup_policy: {
                    ...(draft.execution_strategy?.startup_policy ?? {}),
                    graph_id: value,
                  },
                  lifecycle_policy: draft.execution_strategy?.lifecycle_policy ?? {},
                },
              }))}
            />
            <Field label="执行策略">
              <input readOnly value="graph_task_run" />
            </Field>
            <Field label="状态">
              <select value={engagementPlanDraft.status} onChange={(event) => onSetEngagementPlanDraft((draft) => ({ ...draft, status: event.target.value }))}>
                {["draft", "active", "deprecated", "disabled", "archived"].map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </Field>
            <Field label="说明" wide>
              <textarea rows={4} value={engagementPlanDraft.description} onChange={(event) => onSetEngagementPlanDraft((draft) => ({ ...draft, description: event.target.value }))} />
            </Field>
            <JsonField label="契约 JSON" value={engagementPlanJsonText} onChange={onSetEngagementPlanJsonText} />
            {engagementPlanJsonError ? <div className="boundary-notice boundary-notice--error">{engagementPlanJsonError}</div> : null}
          </div>

          <section className="boundary-panel">
            <header className="boundary-panel__head">
              <div>
                <span>运行结果</span>
                <strong>{planRuns.length ? `${planRuns.length} 次运行` : "暂无运行"}</strong>
              </div>
            </header>
            <div className="boundary-list">
              {planRuns.map((run) => {
                const artifacts = run.artifact_refs ?? [];
                const events = runEvents.filter((event) => event.engagement_run_id === run.engagement_run_id);
                return (
                  <article className="boundary-list-row boundary-list-row--stack" key={run.engagement_run_id}>
                    <div>
                      <strong>{run.status}</strong>
                      <span>{run.task_run_id || run.engagement_run_id}</span>
                    </div>
                    <small>{run.closeout?.task_run_terminal_reason ? String(run.closeout.task_run_terminal_reason) : run.strategy_kind}</small>
                    {artifacts.length ? (
                      <ul>
                        {artifacts.slice(0, 4).map((artifact, index) => (
                          <li key={`${run.engagement_run_id}:artifact:${index}`}>{String(artifact.path ?? artifact.absolute_path ?? artifact.ref ?? "")}</li>
                        ))}
                      </ul>
                    ) : <small>尚未绑定真实交付物。</small>}
                    {events.length ? <small>{events[events.length - 1]?.summary}</small> : null}
                    <div className="boundary-actions">
                      <ToolbarButton disabled={saving === `engagement-run-sync:${run.engagement_run_id}`} onClick={() => void onSyncRunCloseout(run.engagement_run_id)}>
                        同步验收
                      </ToolbarButton>
                    </div>
                  </article>
                );
              })}
              {!planRuns.length ? <div className="boundary-empty">启动承接计划后，这里会显示 TaskRun 收口结果和真实 artifact。</div> : null}
            </div>
          </section>
        </section>
      </main>
    </TaskDefinitionPage>
  );
}
