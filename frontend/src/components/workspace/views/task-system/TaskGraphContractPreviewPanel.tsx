"use client";

import type { TaskGraphContractPreview } from "@/lib/api";

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join(" / ") : "";
}

function recordValue(record: Record<string, unknown> | null | undefined, key: string) {
  return record && typeof record === "object" ? record[key] : undefined;
}

function recordArrayValue(record: Record<string, unknown> | null | undefined, key: string) {
  const value = recordValue(record, key);
  return Array.isArray(value) ? value : [];
}

function issueTitle(issue: Record<string, unknown>, index: number) {
  return String(issue.code ?? issue.message ?? `issue_${index + 1}`);
}

export function TaskGraphContractPreviewPanel({
  preview,
  previewError,
}: {
  preview: TaskGraphContractPreview | null;
  previewError?: string;
}) {
  const config = preview?.graph_config ?? null;
  const scheduler = preview?.scheduler_view ?? null;
  const compositionSources = preview?.composition_sources ?? [];
  const splitPlans = preview?.split_plans ?? [];
  const objectTraceIndex = preview?.object_trace_index ?? [];
  const issues = preview?.issues ?? [];
  const nodes = config?.nodes ?? [];
  const edges = config?.edges ?? [];
  const dependencyEdges = scheduler?.dependency_edges ?? [];

  return (
    <section className="boundary-card">
      <header><strong>图契约</strong><span>图任务运行前的唯一契约</span></header>
      {preview ? (
        <div className="task-graph-runtime-spec-panel">
          <div className="task-graph-mini-kv">
            <p><span>图契约</span><strong>{preview.valid ? "可发布" : "待修复"}</strong></p>
            <p><span>节点</span><strong>{String(preview.summary.node_count ?? nodes.length)}</strong></p>
            <p><span>边</span><strong>{String(preview.summary.edge_count ?? edges.length)}</strong></p>
            <p><span>可执行节点</span><strong>{String(preview.summary.executable_node_count ?? scheduler?.executable_node_ids.length ?? 0)}</strong></p>
            <p><span>依赖边</span><strong>{String(preview.summary.dependency_edge_count ?? dependencyEdges.length)}</strong></p>
            <p><span>组合来源</span><strong>{String(preview.summary.composition_source_count ?? compositionSources.length)}</strong></p>
            <p><span>批次计划</span><strong>{String(preview.summary.split_plan_count ?? splitPlans.length)}</strong></p>
            <p><span>追溯对象</span><strong>{String(preview.summary.object_trace_count ?? objectTraceIndex.length)}</strong></p>
            <p><span>问题</span><strong>{issues.length}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>{config?.config_id || preview.contract_id}</strong>
            <span>发布和启动运行只消费图契约；GraphRuntime 锁定契约，GraphLoop 只读取契约派生的调度视图。</span>
          </div>

          {scheduler ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>Loop 可识别调度视图</strong><span>{scheduler.authority}</span></header>
              <div className="task-graph-mini-kv">
                <p><span>起点</span><strong>{listText(scheduler.start_node_ids) || "-"}</strong></p>
                <p><span>终点</span><strong>{listText(scheduler.terminal_node_ids) || "-"}</strong></p>
                <p><span>可执行</span><strong>{listText(scheduler.executable_node_ids) || "-"}</strong></p>
              </div>
              {dependencyEdges.length ? (
                <div className="task-graph-preflight-list">
                  {dependencyEdges.slice(0, 8).map((edge, index) => (
                    <article className="task-graph-preflight-row" key={`${String(edge.edge_id ?? index)}_dependency`}>
                      <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">dependency</span>
                      <div>
                        <strong>{String(edge.edge_id ?? `edge_${index + 1}`)}</strong>
                        <span>{String(edge.source_node_id ?? "-")} {"->"} {String(edge.target_node_id ?? "-")}</span>
                      </div>
                      <em>{String(edge.edge_type ?? "")}</em>
                      <small>{String(edge.scheduler_role ?? "dependency")}</small>
                    </article>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}

          {compositionSources.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>图组合展开</strong><span>发布期展开为普通节点与边</span></header>
              <div className="task-graph-preflight-list">
                {compositionSources.map((source, index) => (
                  <article className="task-graph-preflight-row task-graph-preflight-row--stacked" key={`${String(source.composition_id ?? index)}_composition`}>
                    <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">expanded</span>
                    <div>
                      <strong>{String(source.linked_graph_id ?? "未绑定图")}</strong>
                      <span>组合节点 {String(source.composition_node_id ?? "-")} / scope {String(source.scope_prefix ?? "-")}</span>
                      <small>节点 {recordArrayValue(source, "expanded_node_ids").length} / 边 {recordArrayValue(source, "expanded_edge_ids").length}</small>
                    </div>
                    <em>{String(source.composition_id ?? "")}</em>
                    <small>ExecutableGraphConfig.composition_sources</small>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {splitPlans.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>批次计划</strong><span>配置内批处理策略</span></header>
              <div className="task-graph-preflight-list">
                {splitPlans.map((plan, index) => {
                  const batches = recordArrayValue(plan, "batches");
                  return (
                    <article className="task-graph-preflight-row task-graph-preflight-row--stacked" key={`${String(recordValue(plan, "plan_id") ?? index)}_split_plan`}>
                      <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">split</span>
                      <div>
                        <strong>{String(recordValue(plan, "unit_kind") ?? "unit")} · {batches.length} 批</strong>
                        <span>节点 {String(recordValue(plan, "node_id") ?? "-")} / 总量 {String(recordValue(plan, "requested_count") ?? 0)} / 每批 {String(recordValue(plan, "batch_size") ?? 0)}</span>
                      </div>
                      <em>{String(recordValue(plan, "plan_id") ?? "")}</em>
                      <small>ExecutableGraphConfig.control.batch_policy</small>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}

          {objectTraceIndex.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>对象追溯</strong><span>Graph object {"->"} harness config</span></header>
              <div className="task-graph-preflight-list">
                {objectTraceIndex.slice(0, 8).map((item, index) => {
                  const runtimeRef = recordValue(item, "runtime_ref") as Record<string, unknown> | null | undefined;
                  const schedulerRef = recordValue(item, "scheduler_ref") as Record<string, unknown> | null | undefined;
                  return (
                    <article className="task-graph-preflight-row" key={`${String(recordValue(item, "object_type") ?? "object")}_${String(recordValue(item, "object_id") ?? index)}`}>
                      <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">{String(recordValue(item, "object_type") ?? "object")}</span>
                      <div>
                        <strong>{String(recordValue(item, "title") ?? recordValue(item, "object_id") ?? "未命名对象")}</strong>
                        <span>runtime {String(recordValue(runtimeRef, "node_id") ?? recordValue(runtimeRef, "edge_id") ?? recordValue(runtimeRef, "graph_config_id") ?? "-")}</span>
                      </div>
                      <em>{String(recordValue(schedulerRef, "role") ?? recordValue(item, "status") ?? "-")}</em>
                      <small>{String(recordValue(item, "source_path") ?? "")}</small>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}

          {issues.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>图契约问题</strong><span>{issues.length} 项</span></header>
              <div className="task-graph-preflight-list">
                {issues.slice(0, 10).map((issue, index) => (
                  <article className="task-graph-preflight-row" key={`${issueTitle(issue, index)}_${index}`}>
                    <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(issue.severity ?? "error")}`}>
                      {String(issue.severity ?? "error")}
                    </span>
                    <div>
                      <strong>{issueTitle(issue, index)}</strong>
                      <span>{String(issue.message ?? "ExecutableGraphConfig 问题")}</span>
                    </div>
                    <em>{String(issue.node_id ?? issue.edge_id ?? issue.scope ?? "graph")}</em>
                    <small>backend.graph_config</small>
                  </article>
                ))}
              </div>
            </section>
          ) : (
            <div className="task-graph-note">
              <strong>图契约没有阻塞问题</strong>
              <span>当前图可以发布为图契约，并由 GraphRuntime 与 GraphLoop 启动。</span>
            </div>
          )}

          <details className="task-graph-runtime-spec-details">
            <summary>图契约 JSON</summary>
            <pre>{JSON.stringify(config, null, 2)}</pre>
          </details>
        </div>
      ) : (
        <div className={previewError ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
          <strong>{previewError ? "图契约不可用" : "尚未编译图契约"}</strong>
          <span>{previewError || "点击“编译图契约”后，图工作台会从 TaskGraphDefinition 编译出 ExecutableGraphConfig 和 loop 调度视图。"}</span>
        </div>
      )}
    </section>
  );
}

