"use client";

import { Activity, Bot, GitBranch, ListChecks, Network, ShieldCheck, Sparkles, Workflow } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import {
  getHealthSystemOverview,
  getOperationAgents,
  getProjectionTemplates,
  getSkillWorkflows,
  getTaskSystemOverview,
  previewHealthAgentRun,
  type HealthAgentRunPreview,
  type HealthSystemOverview,
  type OperationAgentCatalog,
  type ProjectionTemplateCatalog,
  type SkillWorkflowCatalog,
  type TaskSystemOverview
} from "@/lib/api";

type PanelKey =
  | "overview"
  | "main-agent"
  | "sub-agents"
  | "flows"
  | "coordination"
  | "matrix"
  | "workflows"
  | "projections"
  | "runs";

const panels: Array<{ key: PanelKey; label: string; icon: typeof Activity }> = [
  { key: "overview", label: "总览", icon: Activity },
  { key: "main-agent", label: "主 Agent", icon: Bot },
  { key: "sub-agents", label: "子 Agent", icon: Network },
  { key: "flows", label: "任务流", icon: Workflow },
  { key: "coordination", label: "协调任务", icon: GitBranch },
  { key: "matrix", label: "链路权限", icon: ShieldCheck },
  { key: "workflows", label: "Skills 工作流", icon: ListChecks },
  { key: "projections", label: "投影分配", icon: Sparkles },
  { key: "runs", label: "运行记录", icon: Activity }
];

function text(value: unknown, fallback = "-") {
  if (Array.isArray(value)) {
    return value.length ? value.join(" / ") : fallback;
  }
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function badgeTone(value: unknown) {
  const normalized = String(value || "").toLowerCase();
  if (["valid", "enabled", "system_builtin", "sample"].includes(normalized)) {
    return "border-emerald-300 bg-emerald-50 text-emerald-800";
  }
  if (["invalid", "disabled", "blocked", "failed"].includes(normalized)) {
    return "border-rose-300 bg-rose-50 text-rose-800";
  }
  return "border-slate-300 bg-slate-50 text-slate-700";
}

function StatusBadge({ value }: { value: unknown }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${badgeTone(value)}`}>
      {text(value)}
    </span>
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div>
        <h3 className="text-base font-semibold text-slate-950">{title}</h3>
        {subtitle ? <p className="mt-1 text-xs text-slate-500">{subtitle}</p> : null}
      </div>
    </div>
  );
}

function DataTable({
  rows,
  columns,
  emptyText = "暂无数据",
  onRowSelect
}: {
  rows: Array<Record<string, unknown>>;
  columns: Array<{ key: string; label: string; render?: (row: Record<string, unknown>) => ReactNode }>;
  emptyText?: string;
  onRowSelect?: (row: Record<string, unknown>) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="max-h-[520px] overflow-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
            <tr>
              {columns.map((column) => (
                <th className="border-b border-slate-200 px-3 py-2 font-semibold" key={column.key}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length ? (
              rows.map((row, index) => (
                <tr
                  className={`border-b border-slate-100 last:border-0 ${onRowSelect ? "cursor-pointer hover:bg-slate-50" : ""}`}
                  key={`${columns[0]?.key || "row"}-${index}`}
                  onClick={() => onRowSelect?.(row)}
                >
                  {columns.map((column) => (
                    <td className="max-w-[260px] px-3 py-2 align-top text-slate-700" key={column.key}>
                      {column.render ? column.render(row) : text(row[column.key])}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-3 py-8 text-center text-slate-500" colSpan={columns.length}>
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function TaskSystemView() {
  const [activePanel, setActivePanel] = useState<PanelKey>("overview");
  const [taskOverview, setTaskOverview] = useState<TaskSystemOverview | null>(null);
  const [operationAgents, setOperationAgents] = useState<OperationAgentCatalog | null>(null);
  const [workflows, setWorkflows] = useState<SkillWorkflowCatalog | null>(null);
  const [projections, setProjections] = useState<ProjectionTemplateCatalog | null>(null);
  const [health, setHealth] = useState<HealthSystemOverview | null>(null);
  const [detail, setDetail] = useState<{ title: string; payload: Record<string, unknown> } | null>(null);
  const [preview, setPreview] = useState<HealthAgentRunPreview | null>(null);
  const [previewingIssueId, setPreviewingIssueId] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [taskPayload, agentPayload, workflowPayload, projectionPayload, healthPayload] = await Promise.all([
          getTaskSystemOverview(),
          getOperationAgents(),
          getSkillWorkflows(),
          getProjectionTemplates(),
          getHealthSystemOverview()
        ]);
        if (cancelled) {
          return;
        }
        setTaskOverview(taskPayload);
        setOperationAgents(agentPayload);
        setWorkflows(workflowPayload);
        setProjections(projectionPayload);
        setHealth(healthPayload);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "任务系统数据加载失败");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const agents = useMemo(() => taskOverview?.agents ?? operationAgents?.agents ?? [], [operationAgents, taskOverview]);
  const mainAgents = useMemo(() => agents.filter((item) => item.profile_type === "primary"), [agents]);
  const subAgents = useMemo(() => agents.filter((item) => item.profile_type === "sub_agent"), [agents]);
  const flows = taskOverview?.flows ?? [];
  const bindings = taskOverview?.bindings ?? [];
  const matrixRows = taskOverview?.link_permission_matrix?.rows ?? [];
  const coordinationTasks = taskOverview?.coordination_tasks ?? [];
  const topologyTemplates = taskOverview?.topology_templates ?? [];
  const workflowRows = workflows?.workflows ?? [];
  const projectionRows = projections?.templates ?? [];
  const runRows = health?.agent_runs ?? [];

  async function handlePreviewIssue(issueId: string) {
    setPreviewingIssueId(issueId);
    setError("");
    try {
      const payload = await previewHealthAgentRun(issueId);
      setPreview(payload);
      setDetail({ title: "健康子 Agent 实例化预览", payload: payload as unknown as Record<string, unknown> });
      setActivePanel("runs");
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "健康子 Agent 实例化预览失败");
    } finally {
      setPreviewingIssueId("");
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden task-system-view">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Task System</p>
          <h2 className="mt-1 text-2xl font-semibold text-slate-950">任务系统工作台</h2>
        </div>
        <div className="grid grid-cols-4 gap-2 text-xs">
          <Metric label="Agent" value={taskOverview?.summary?.agent_count} />
          <Metric label="任务流" value={taskOverview?.summary?.task_flow_count} />
          <Metric label="协调任务" value={taskOverview?.summary?.coordination_task_count} />
          <Metric label="断链" value={taskOverview?.summary?.invalid_binding_count} />
        </div>
      </header>

      {error ? <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}

      <div className="grid min-h-0 flex-1 grid-cols-[190px_minmax(0,1fr)] gap-4 overflow-hidden">
        <nav className="min-h-0 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
          {panels.map((panel) => {
            const Icon = panel.icon;
            return (
              <button
                className={`mb-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm ${
                  activePanel === panel.key ? "bg-slate-950 text-white" : "text-slate-700 hover:bg-white"
                }`}
                key={panel.key}
                onClick={() => setActivePanel(panel.key)}
                type="button"
              >
                <Icon size={15} />
                {panel.label}
              </button>
            );
          })}
        </nav>

        <main className="min-h-0 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-4">
          {activePanel === "overview" ? (
            <div className="grid gap-4">
              <SectionTitle title="完整装配链" subtitle="Task -> Agent -> Workflow -> Projection -> Lane -> Policy -> RuntimeLoop -> HealthTrace" />
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-4">
                <ChainNode title="操作系统" body="AgentRegistry / AgentCapabilityProfile" />
                <ChainNode title="任务系统" body="TaskFlow / TaskAgentBinding / Matrix" />
                <ChainNode title="执行循环" body="RuntimeDirectiveLane / TaskRunLoop" />
                <ChainNode title="健康系统" body="HealthIssue / HealthAgentRun / ProblemNode" />
              </div>
              <SectionTitle title="最近健康问题" />
              <DataTable
                rows={health?.issues ?? []}
                onRowSelect={(row) => setDetail({ title: "健康问题", payload: row })}
                columns={[
                  { key: "issue_id", label: "Issue" },
                  { key: "title", label: "标题" },
                  { key: "owner_system", label: "归属" },
                  { key: "severity", label: "级别" },
                  { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
                  {
                    key: "action",
                    label: "实例化",
                    render: (row) => {
                      const issueId = text(row.issue_id, "");
                      return (
                        <button
                          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-100"
                          disabled={!issueId || previewingIssueId === issueId}
                          onClick={(event) => {
                            event.stopPropagation();
                            void handlePreviewIssue(issueId);
                          }}
                          type="button"
                        >
                          {previewingIssueId === issueId ? "装配中" : "预览"}
                        </button>
                      );
                    }
                  }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "main-agent" ? (
            <div className="grid gap-4">
              <SectionTitle title="主 Agent 调度中心" subtitle="主 Agent 负责任务识别、委派和最终整合，不与子 Agent 混在同一管理列表。" />
              <DataTable
                rows={mainAgents}
                onRowSelect={(row) => setDetail({ title: "主 Agent", payload: row })}
                columns={[
                  { key: "agent_id", label: "Agent" },
                  { key: "display_name", label: "名称" },
                  { key: "lifecycle_state", label: "生命周期", render: (row) => <StatusBadge value={row.lifecycle_state} /> },
                  { key: "default_projection_template_id", label: "默认投影" },
                  { key: "governance_status", label: "治理" }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "sub-agents" ? (
            <div className="grid gap-4">
              <SectionTitle title="子 Agent 实例" subtitle="子 Agent 是受限执行单元，按任务族、链路权限、workflow 和投影模板装配。" />
              <DataTable
                rows={subAgents}
                onRowSelect={(row) => setDetail({ title: "子 Agent", payload: row })}
                columns={[
                  { key: "agent_id", label: "Agent" },
                  { key: "display_name", label: "名称" },
                  { key: "owner_system", label: "Owner" },
                  { key: "lifecycle_state", label: "状态", render: (row) => <StatusBadge value={row.lifecycle_state} /> },
                  { key: "default_projection_template_id", label: "投影" },
                  { key: "deletable", label: "删除策略" }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "flows" ? (
            <div className="grid gap-4">
              <SectionTitle title="单 Agent 任务流" />
              <DataTable
                rows={flows}
                onRowSelect={(row) => setDetail({ title: "任务流", payload: row })}
                columns={[
                  { key: "flow_id", label: "Flow" },
                  { key: "task_mode", label: "TaskMode" },
                  { key: "default_agent_id", label: "Agent" },
                  { key: "default_workflow_id", label: "Workflow" },
                  { key: "default_runtime_lane", label: "Lane" },
                  { key: "default_memory_scope", label: "Memory" },
                  { key: "output_contract_id", label: "Output" }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "coordination" ? (
            <div className="grid gap-4">
              <SectionTitle title="协调任务" subtitle="本轮仅占位和只读展示，为未来多 Agent 拓扑准备。" />
              <DataTable
                rows={coordinationTasks}
                onRowSelect={(row) => setDetail({ title: "协调任务", payload: row })}
                columns={[
                  { key: "coordination_task_id", label: "Coordination" },
                  { key: "title", label: "标题" },
                  { key: "coordination_mode", label: "模式" },
                  { key: "coordinator_agent_id", label: "协调者" },
                  { key: "participant_agent_ids", label: "参与者" },
                  { key: "enabled", label: "启用", render: (row) => <StatusBadge value={row.enabled ? "enabled" : "draft"} /> }
                ]}
              />
              <SectionTitle title="拓扑模板" />
              <DataTable
                rows={topologyTemplates}
                onRowSelect={(row) => setDetail({ title: "拓扑模板", payload: row })}
                columns={[
                  { key: "template_id", label: "Template" },
                  { key: "title", label: "标题" },
                  { key: "join_policy", label: "Join" },
                  { key: "failure_policy", label: "Failure" },
                  { key: "terminal_policy", label: "Terminal" }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "matrix" ? (
            <div className="grid gap-4">
              <SectionTitle title="链路权限矩阵" subtitle="回答每个 agent 在每个 task mode 下能走哪条链。" />
              <DataTable
                rows={matrixRows}
                onRowSelect={(row) => setDetail({ title: "链路权限", payload: row })}
                columns={[
                  { key: "agent_id", label: "Agent" },
                  { key: "task_mode", label: "Task" },
                  { key: "runtime_lane", label: "Lane" },
                  { key: "skill_workflow", label: "Workflow" },
                  { key: "projection_template", label: "Projection" },
                  { key: "memory_scope", label: "Memory" },
                  { key: "output_contract", label: "Output" },
                  { key: "validation_state", label: "状态", render: (row) => <StatusBadge value={row.validation_state} /> }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "workflows" ? (
            <div className="grid gap-4">
              <SectionTitle title="Skills 工作流" />
              <DataTable
                rows={workflowRows}
                onRowSelect={(row) => setDetail({ title: "Skills 工作流", payload: row })}
                columns={[
                  { key: "workflow_id", label: "Workflow" },
                  { key: "title", label: "标题" },
                  { key: "task_mode", label: "TaskMode" },
                  { key: "visible_skill_ids", label: "Skills" },
                  { key: "output_contract_id", label: "Output" }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "projections" ? (
            <div className="grid gap-4">
              <SectionTitle title="投影分配" />
              <DataTable
                rows={projectionRows}
                onRowSelect={(row) => setDetail({ title: "投影模板", payload: row })}
                columns={[
                  { key: "template_id", label: "Template" },
                  { key: "title", label: "标题" },
                  { key: "soul_id", label: "Soul" },
                  { key: "agent_profile_id", label: "Profile" },
                  { key: "projection_resolution_policy", label: "切换策略" },
                  { key: "default_skill_workflow_id", label: "Workflow" },
                  { key: "default_output_contract", label: "Output" }
                ]}
              />
            </div>
          ) : null}

          {activePanel === "runs" ? (
            <div className="grid gap-4">
              <SectionTitle title="运行记录" subtitle="当前展示健康子 Agent 的样例运行索引，后续接 RuntimeLoop trace reader。" />
              <DataTable
                rows={runRows}
                onRowSelect={(row) => setDetail({ title: "健康 Agent Run", payload: row })}
                columns={[
                  { key: "run_id", label: "Run" },
                  { key: "issue_id", label: "Issue" },
                  { key: "agent_id", label: "Agent" },
                  { key: "runtime_lane", label: "Lane" },
                  { key: "workflow_id", label: "Workflow" },
                  { key: "status", label: "状态", render: (row) => <StatusBadge value={row.status} /> },
                  { key: "terminal_reason", label: "结束原因" }
                ]}
              />
            </div>
          ) : null}
          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <SectionTitle title="当前装配状态" subtitle="这里显示任务系统是否已经把 Agent、任务流、workflow、投影和 lane 串起来。" />
              <div className="mt-4 grid grid-cols-2 gap-3 text-xs xl:grid-cols-4">
                <StateChip label="绑定" value={bindings.length ? "ready" : "missing"} />
                <StateChip label="权限矩阵" value={matrixRows.length ? "ready" : "missing"} />
                <StateChip label="投影模板" value={projectionRows.length ? "ready" : "missing"} />
                <StateChip label="健康实例化" value={preview?.status ?? "waiting"} />
              </div>
            </div>
            <DetailPanel detail={detail} preview={preview} />
          </div>
        </main>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-right">
      <div className="text-[11px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-slate-950">{text(value, "0")}</div>
    </div>
  );
}

function ChainNode({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <div className="mt-2 text-xs leading-5 text-slate-500">{body}</div>
    </div>
  );
}

function StateChip({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1">
        <StatusBadge value={value} />
      </div>
    </div>
  );
}

function DetailPanel({
  detail,
  preview
}: {
  detail: { title: string; payload: Record<string, unknown> } | null;
  preview: HealthAgentRunPreview | null;
}) {
  const payload = detail?.payload;
  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4">
      <SectionTitle title={detail?.title ?? "详情"} subtitle={detail ? "点击表格行可切换详情。" : "请选择一条任务系统对象。"} />
      {preview ? (
        <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">
          <div className="font-semibold">最近实例化预览：{preview.status}</div>
          <div className="mt-2 grid gap-1">
            <span>Agent: {text(preview.binding?.agent_id)}</span>
            <span>Lane: {text(preview.runtime_directive_lane?.lane_type)}</span>
            <span>Projection: {text(preview.projection_instance?.template_id)}</span>
            <span>PromptManifest: {text(preview.projection_instance?.prompt_manifest_id)}</span>
          </div>
        </div>
      ) : null}
      {payload ? (
        <pre className="mt-4 max-h-[420px] overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
          {JSON.stringify(payload, null, 2)}
        </pre>
      ) : (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300 p-6 text-center text-xs text-slate-500">
          任务系统对象的合同、权限和运行引用会显示在这里。
        </div>
      )}
    </aside>
  );
}
