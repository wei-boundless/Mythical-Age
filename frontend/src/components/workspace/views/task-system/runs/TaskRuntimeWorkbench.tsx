"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Send, SquareTerminal } from "lucide-react";

import {
  getTaskWorkEnvironmentDetail,
  listTaskWorkEnvironments,
  submitTaskWorkEnvironmentCommand,
  type TaskCommandRecord,
  type TaskDispatchRecord,
  type TaskWorkEnvironmentDetailResponse,
  type TaskWorkEnvironmentListItem,
} from "@/lib/api";

const DEFAULT_COMMAND_KIND = "dispatch_ready_graph_nodes";
const COMMAND_KIND_OPTIONS = [
  "prepare_episode",
  "run_episode",
  "request_pause",
  "request_resume",
  "request_stop",
  "recover_stale_lease",
  "resume_graph_run",
  "requeue_graph_node",
  "dispatch_ready_graph_nodes",
  "run_graph_node_work_order",
  "materialize_project_network_generation",
  "publish_project_network_generation",
  "repair_project_network_refs",
];

export function TaskRuntimeWorkbench() {
  const [items, setItems] = useState<TaskWorkEnvironmentListItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<TaskWorkEnvironmentDetailResponse | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [commandKind, setCommandKind] = useState(DEFAULT_COMMAND_KIND);
  const [commandPayload, setCommandPayload] = useState("{}");
  const [dispatchNow, setDispatchNow] = useState(true);

  const selectedItem = useMemo(
    () => items.find((item) => environmentIdOf(item) === selectedId) ?? null,
    [items, selectedId],
  );

  const loadList = useCallback(async () => {
    setLoadingList(true);
    setError("");
    try {
      const payload = await listTaskWorkEnvironments({ limit: 120 });
      const nextItems = payload.task_environments ?? [];
      setItems(nextItems);
      setSelectedId((current) => {
        if (current && nextItems.some((item) => environmentIdOf(item) === current)) return current;
        return environmentIdOf(nextItems[0]) || "";
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "任务环境列表加载失败");
    } finally {
      setLoadingList(false);
    }
  }, []);

  const loadDetail = useCallback(async (environmentId: string) => {
    if (!environmentId) {
      setDetail(null);
      return;
    }
    setLoadingDetail(true);
    setError("");
    try {
      const payload = await getTaskWorkEnvironmentDetail(environmentId, {
        contextPackageLimit: 6,
        episodeLimit: 24,
        eventLimit: 50,
        workProductLimit: 32,
      });
      setDetail(payload);
    } catch (exc) {
      setDetail(null);
      setError(exc instanceof Error ? exc.message : "任务环境详情加载失败");
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    void loadDetail(selectedId);
  }, [loadDetail, selectedId]);

  async function submitCommand() {
    if (!selectedId) return;
    let payload: Record<string, unknown>;
    try {
      const parsed = JSON.parse(commandPayload || "{}");
      if (!isPlainObject(parsed)) {
        setError("命令载荷必须是 JSON 对象。");
        return;
      }
      payload = parsed;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "命令载荷不是有效 JSON。");
      return;
    }
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const result = await submitTaskWorkEnvironmentCommand(selectedId, {
        command_kind: commandKind.trim() || DEFAULT_COMMAND_KIND,
        requested_by: "task-system-workbench",
        payload,
        dispatch_now: dispatchNow,
      });
      const submissionCommand = isPlainObject(result.submission?.command) ? result.submission.command : {};
      const commandId = String(result.submission?.command_id || submissionCommand.command_id || "");
      setNotice(commandId ? `命令已提交：${commandId}` : "命令已提交。");
      await loadDetail(selectedId);
      await loadList();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "命令提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="task-runtime-workbench">
      <header className="task-runtime-head">
        <div>
          <strong>任务事实</strong>
          <span>TaskEnvironment、TaskCommand、dispatch 和运行产物</span>
        </div>
        <button disabled={loadingList || loadingDetail} onClick={() => void loadList()} type="button">
          <RefreshCw size={15} />刷新
        </button>
      </header>

      {error ? <p className="task-runtime-message task-runtime-message--error">{error}</p> : null}
      {notice ? <p className="task-runtime-message">{notice}</p> : null}

      <div className="task-runtime-layout">
        <TaskEnvironmentRail
          items={items}
          loading={loadingList}
          onSelect={setSelectedId}
          selectedId={selectedId}
        />

        <main className="task-runtime-main">
          <TaskEnvironmentOverview detail={detail} item={selectedItem} loading={loadingDetail} />
          <TaskCommandComposer
            commandKind={commandKind}
            commandPayload={commandPayload}
            dispatchNow={dispatchNow}
            disabled={!selectedId || submitting}
            onCommandKindChange={setCommandKind}
            onCommandPayloadChange={setCommandPayload}
            onDispatchNowChange={setDispatchNow}
            onSubmit={() => void submitCommand()}
            submitting={submitting}
          />
          <TaskFactSections detail={detail} />
        </main>
      </div>
    </section>
  );
}

function TaskEnvironmentRail({
  items,
  loading,
  onSelect,
  selectedId,
}: {
  items: TaskWorkEnvironmentListItem[];
  loading: boolean;
  onSelect: (environmentId: string) => void;
  selectedId: string;
}) {
  if (!items.length) {
    return (
      <aside className="task-runtime-rail">
        <p className="task-runtime-empty">{loading ? "正在加载任务环境..." : "暂无任务运行事实。"}</p>
      </aside>
    );
  }
  return (
    <aside className="task-runtime-rail" aria-label="任务环境列表">
      {items.map((item) => {
        const environmentId = environmentIdOf(item);
        const active = environmentId === selectedId;
        return (
          <button
            aria-current={active ? "true" : undefined}
            className={active ? "task-runtime-env-row task-runtime-env-row--active" : "task-runtime-env-row"}
            key={environmentId}
            onClick={() => onSelect(environmentId)}
            type="button"
          >
            <strong>{taskTitleOf(item)}</strong>
            <span>{environmentId}</span>
            <small>{statusLabel(statusOf(item))}</small>
          </button>
        );
      })}
    </aside>
  );
}

function TaskEnvironmentOverview({
  detail,
  item,
  loading,
}: {
  detail: TaskWorkEnvironmentDetailResponse | null;
  item: TaskWorkEnvironmentListItem | null;
  loading: boolean;
}) {
  const environment = detail?.task_environment ?? item?.task_environment ?? {};
  const instance = detail?.task_instance ?? item?.task_instance ?? {};
  const binding = detail?.graph_node_binding ?? item?.graph_node_binding ?? {};
  const summary = detail?.summary ?? {};
  const activity = detail?.activity_state ?? item?.activity_state ?? {};
  const title = firstText(instance, ["title", "task_title", "name"]) || firstText(environment, ["title", "label"]) || "任务环境";
  const environmentId = firstText(environment, ["task_environment_id"]) || (item ? environmentIdOf(item) : "");
  return (
    <section className="task-runtime-panel task-runtime-panel--overview">
      <header>
        <div>
          <strong>{loading ? "正在同步任务事实..." : title}</strong>
          <span>{environmentId || "未选择任务环境"}</span>
        </div>
        <small>{statusLabel(firstText(activity, ["activity_state", "status"]) || firstText(environment, ["status"]))}</small>
      </header>
      <div className="task-runtime-metrics">
        <Metric label="命令" value={summaryNumber(summary, "task_command_count")} />
        <Metric label="派发" value={summaryNumber(summary, "task_dispatch_record_count")} />
        <Metric label="Episode" value={summaryNumber(summary, "episode_count")} />
        <Metric label="产物" value={summaryNumber(summary, "work_product_count")} />
        <Metric label="Checkpoint" value={summaryNumber(summary, "checkpoint_count")} />
        <Metric label="事件" value={summaryNumber(summary, "event_count")} />
      </div>
      <div className="task-runtime-kv">
        <p><span>任务类型</span><strong>{firstText(instance, ["task_kind", "kind"]) || "未记录"}</strong></p>
        <p><span>项目</span><strong>{firstText(instance, ["project_id"]) || firstText(environment, ["project_id"]) || "未绑定"}</strong></p>
        <p><span>图运行</span><strong>{firstText(binding, ["graph_run_id"]) || "未绑定"}</strong></p>
        <p><span>WorkOrder</span><strong>{firstText(binding, ["work_order_id"]) || "未绑定"}</strong></p>
      </div>
    </section>
  );
}

function TaskCommandComposer({
  commandKind,
  commandPayload,
  dispatchNow,
  disabled,
  onCommandKindChange,
  onCommandPayloadChange,
  onDispatchNowChange,
  onSubmit,
  submitting,
}: {
  commandKind: string;
  commandPayload: string;
  dispatchNow: boolean;
  disabled: boolean;
  onCommandKindChange: (value: string) => void;
  onCommandPayloadChange: (value: string) => void;
  onDispatchNowChange: (value: boolean) => void;
  onSubmit: () => void;
  submitting: boolean;
}) {
  return (
    <section className="task-runtime-panel task-runtime-command">
      <header>
        <div>
          <strong>提交命令</strong>
          <span>所有推进动作进入 TaskCommand，再由 scheduler 执行</span>
        </div>
        <button disabled={disabled} onClick={onSubmit} type="button">
          {submitting ? <SquareTerminal size={15} /> : <Send size={15} />}
          {submitting ? "提交中" : "提交"}
        </button>
      </header>
      <div className="task-runtime-command__grid">
        <label>
          <span>命令类型</span>
          <select value={commandKind} onChange={(event) => onCommandKindChange(event.target.value)}>
            {COMMAND_KIND_OPTIONS.map((item) => (
              <option key={item} value={item}>{commandKindLabel(item)}</option>
            ))}
          </select>
        </label>
        <label className="task-runtime-command__switch">
          <input checked={dispatchNow} onChange={(event) => onDispatchNowChange(event.target.checked)} type="checkbox" />
          <span>立即派发</span>
        </label>
        <label className="task-runtime-command__payload">
          <span>载荷 JSON</span>
          <textarea value={commandPayload} onChange={(event) => onCommandPayloadChange(event.target.value)} />
        </label>
      </div>
    </section>
  );
}

function TaskFactSections({ detail }: { detail: TaskWorkEnvironmentDetailResponse | null }) {
  if (!detail) {
    return <p className="task-runtime-empty">选择任务环境后显示任务事实。</p>;
  }
  return (
    <div className="task-runtime-fact-grid">
      <TaskCommandTable commands={detail.task_commands ?? []} dispatchRecords={detail.task_dispatch_records ?? []} />
      <RecordList
        emptyText="暂无 work product。"
        items={detail.work_products ?? []}
        title="运行产物"
        renderItem={(item) => (
          <>
            <strong>{firstText(item, ["product_kind", "product_domain"]) || "work product"}</strong>
            <span>{firstText(item, ["status"]) || "candidate"} · {firstText(item, ["confidence"]) || "confidence 未记录"}</span>
            <small>{firstText(item, ["stable_ref", "payload_ref", "work_product_id"])}</small>
          </>
        )}
      />
      <RecordList
        emptyText="暂无 checkpoint。"
        items={detail.checkpoints ?? []}
        title="检查点"
        renderItem={(item) => (
          <>
            <strong>{firstText(item, ["checkpoint_kind", "kind"]) || "checkpoint"}</strong>
            <span>{firstText(item, ["status"]) || formatTime(item.updated_at ?? item.created_at)}</span>
            <small>{firstText(item, ["checkpoint_id", "source_episode_id"])}</small>
          </>
        )}
      />
      <RecordList
        emptyText="暂无计划或待办。"
        items={[...(detail.task_plans ?? []), ...(detail.todo_items ?? [])].slice(0, 12)}
        title="计划与待办"
        renderItem={(item) => (
          <>
            <strong>{firstText(item, ["title", "plan_title", "goal"]) || firstText(item, ["plan_id", "todo_id"]) || "任务事实"}</strong>
            <span>{statusLabel(firstText(item, ["status"]))}</span>
            <small>{firstText(item, ["blocker", "summary", "plan_id", "todo_id"])}</small>
          </>
        )}
      />
      <RecordList
        emptyText="暂无事件。"
        items={detail.events ?? []}
        title="事件流"
        renderItem={(item) => (
          <>
            <strong>{firstText(item, ["event_type", "kind"]) || "event"}</strong>
            <span>{formatTime(item.created_at ?? item.updated_at)}</span>
            <small>{firstText(item, ["summary", "event_id", "source_id"])}</small>
          </>
        )}
      />
    </div>
  );
}

function TaskCommandTable({
  commands,
  dispatchRecords,
}: {
  commands: TaskCommandRecord[];
  dispatchRecords: TaskDispatchRecord[];
}) {
  const dispatchByCommand = new Map(dispatchRecords.map((record) => [record.command_id, record]));
  return (
    <section className="task-runtime-panel task-runtime-panel--wide">
      <header>
        <div>
          <strong>命令账本</strong>
          <span>{commands.length} commands · {dispatchRecords.length} dispatch records</span>
        </div>
      </header>
      {commands.length ? (
        <div className="task-runtime-table">
          <div className="task-runtime-table__head" aria-hidden="true">
            <span>命令</span>
            <span>状态</span>
            <span>派发</span>
            <span>时间</span>
          </div>
          {commands.map((command) => {
            const dispatch = dispatchByCommand.get(command.command_id);
            return (
              <div className="task-runtime-table__row" key={command.command_id}>
                <p>
                  <strong>{commandKindLabel(command.command_kind)}</strong>
                  <span>{command.command_id}</span>
                </p>
                <p><strong>{statusLabel(command.status)}</strong><span>{command.attempt_count ?? 0} attempts</span></p>
                <p><strong>{statusLabel(dispatch?.status)}</strong><span>{dispatch?.dispatch_id || "未派发"}</span></p>
                <p><strong>{formatTime(command.updated_at || command.created_at)}</strong><span>{command.requested_by || "unknown"}</span></p>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="task-runtime-empty">暂无命令记录。</p>
      )}
    </section>
  );
}

function RecordList({
  emptyText,
  items,
  renderItem,
  title,
}: {
  emptyText: string;
  items: Array<Record<string, unknown>>;
  renderItem: (item: Record<string, unknown>) => JSX.Element;
  title: string;
}) {
  return (
    <section className="task-runtime-panel">
      <header>
        <div>
          <strong>{title}</strong>
          <span>{items.length} records</span>
        </div>
      </header>
      {items.length ? (
        <div className="task-runtime-list">
          {items.map((item, index) => (
            <article key={firstText(item, ["work_product_id", "checkpoint_id", "todo_id", "plan_id", "event_id"]) || `${title}-${index}`}>
              {renderItem(item)}
            </article>
          ))}
        </div>
      ) : (
        <p className="task-runtime-empty">{emptyText}</p>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <p>
      <span>{label}</span>
      <strong>{String(value)}</strong>
    </p>
  );
}

function environmentIdOf(item: TaskWorkEnvironmentListItem | undefined | null) {
  return firstText(item?.task_environment, ["task_environment_id"]) || "";
}

function taskTitleOf(item: TaskWorkEnvironmentListItem) {
  return firstText(item.task_instance, ["title", "task_title", "name"])
    || firstText(item.task_environment, ["title", "label"])
    || environmentIdOf(item)
    || "任务环境";
}

function statusOf(item: TaskWorkEnvironmentListItem) {
  return firstText(item.activity_state, ["activity_state", "status"])
    || firstText(item.task_environment, ["status"])
    || firstText(item.task_instance, ["status"]);
}

function firstText(payload: unknown, keys: string[]) {
  if (!isPlainObject(payload)) return "";
  for (const key of keys) {
    const value = payload[key];
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

function summaryNumber(summary: Record<string, unknown>, key: string) {
  const value = Number(summary[key] ?? 0);
  return Number.isFinite(value) ? value : 0;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function statusLabel(status: unknown) {
  const value = String(status ?? "").trim();
  const labels: Record<string, string> = {
    active: "运行中",
    blocked: "阻塞",
    canceled: "已取消",
    candidate: "候选",
    completed: "已完成",
    dead_letter: "死信",
    failed: "失败",
    idle: "空闲",
    pending: "等待",
    queued: "排队",
    recorded: "已记录",
    running: "运行中",
    stopped: "已停止",
    succeeded: "成功",
    waiting: "等待",
  };
  return labels[value] || value || "未记录";
}

function commandKindLabel(kind: string) {
  const labels: Record<string, string> = {
    dispatch_ready_graph_nodes: "派发就绪图节点",
    materialize_project_network_generation: "生成项目网络候选",
    prepare_episode: "准备 Episode",
    publish_project_network_generation: "发布项目网络 generation",
    recover_stale_lease: "恢复过期租约",
    repair_project_network_refs: "修复项目网络引用",
    request_pause: "请求暂停",
    request_resume: "请求恢复",
    request_stop: "请求停止",
    resume_graph_run: "恢复图运行",
    requeue_graph_node: "重排图节点",
    run_episode: "运行 Episode",
    run_graph_node_work_order: "运行图节点 WorkOrder",
  };
  return labels[kind] ? `${labels[kind]} · ${kind}` : kind;
}

function formatTime(value: unknown) {
  const timestamp = Number(value || 0);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "未记录";
  const millis = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
  return new Date(millis).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
