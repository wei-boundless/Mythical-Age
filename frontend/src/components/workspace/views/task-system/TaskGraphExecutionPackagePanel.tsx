"use client";

import type {
  ContractManifest,
  TaskGraphExecutionPackage,
  TaskGraphRuntimeSpec,
} from "@/lib/api";

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join(" / ") : "";
}

function runtimeIssueTitle(issue: Record<string, unknown>, index: number) {
  return String(issue.code ?? issue.message ?? `issue_${index + 1}`);
}

function recordValue(record: Record<string, unknown> | null | undefined, key: string) {
  return record && typeof record === "object" ? record[key] : undefined;
}

function recordArrayValue(record: Record<string, unknown> | null | undefined, key: string) {
  const value = recordValue(record, key);
  return Array.isArray(value) ? value : [];
}

function recordNumberValue(record: Record<string, unknown> | null | undefined, key: string) {
  const value = recordValue(record, key);
  return typeof value === "number" ? value : Number(value || 0);
}

function RawDiagnosticsDetails({
  children,
  title,
}: {
  children: string;
  title: string;
}) {
  return (
    <details className="task-graph-runtime-spec-details">
      <summary>{title}</summary>
      <pre>{children}</pre>
    </details>
  );
}

export function TaskGraphExecutionPackagePanel({
  contractManifest,
  executionPackage,
  runtimeSpec,
  runtimeSpecError,
}: {
  contractManifest: ContractManifest | null;
  executionPackage: TaskGraphExecutionPackage | null;
  runtimeSpec: TaskGraphRuntimeSpec | null;
  runtimeSpecError?: string;
}) {
  const graphModuleExecutionPlans = executionPackage?.graph_module_execution_plans ?? [];
  const splitPlans = executionPackage?.split_plans ?? [];
  const splitMergeIssues = executionPackage?.split_merge_issues ?? [];
  const objectTraceIndex = executionPackage?.object_trace_index ?? [];
  const runtimeDiagnostics = runtimeSpec?.diagnostics ?? {};
  const lengthBudget = recordValue(runtimeDiagnostics, "length_budget") as Record<string, unknown> | null | undefined;
  const lengthBudgetPreview = recordValue(runtimeDiagnostics, "length_budget_preview") as Record<string, unknown> | null | undefined;
  const runtimeSemantics = recordValue(runtimeDiagnostics, "runtime_semantics") as Record<string, unknown> | null | undefined;
  const runtimeSemanticsSummary = recordValue(runtimeSemantics, "summary") as Record<string, unknown> | null | undefined;
  const runtimeStepPolicy = recordValue(runtimeSemantics, "step_policy") as Record<string, unknown> | null | undefined;
  const runtimeSemanticDiagnostics = recordArrayValue(runtimeSemantics, "diagnostics");
  const splitLifecycleCount = Number(executionPackage?.summary.split_batch_lifecycle_plan_count ?? 0);
  const splitLifecycleStepCount = Number(executionPackage?.summary.split_batch_lifecycle_step_count ?? 0);

  return (
    <section className="boundary-card">
      <header><strong>发布执行包</strong><span>执行包是发布前真实运行事实源</span></header>
      {executionPackage ? (
        <div className="task-graph-runtime-spec-panel">
          <div className="task-graph-mini-kv">
            <p><span>执行包</span><strong>{executionPackage.valid ? "通过" : "待修复"}</strong></p>
            <p><span>Assembly</span><strong>{executionPackage.node_runtime_assemblies.length}</strong></p>
            <p><span>图模块</span><strong>{executionPackage.graph_modules.length}</strong></p>
            <p><span>图模块契约</span><strong>{String(executionPackage.summary.graph_module_handoff_contract_count ?? 0)}</strong></p>
            <p><span>模块计划</span><strong>{graphModuleExecutionPlans.length}</strong></p>
            <p><span>批次计划</span><strong>{String(executionPackage.summary.split_plan_count ?? splitPlans.length)}</strong></p>
            <p><span>批次数</span><strong>{String(executionPackage.summary.split_batch_count ?? 0)}</strong></p>
            <p><span>批次生命周期</span><strong>{String(splitLifecycleCount)}</strong></p>
            <p><span>生命周期步骤</span><strong>{String(splitLifecycleStepCount)}</strong></p>
            <p><span>对象追溯</span><strong>{String(executionPackage.summary.object_trace_count ?? objectTraceIndex.length)}</strong></p>
            <p><span>Scheduler Ready</span><strong>{String(executionPackage.summary.scheduler_ready_count ?? 0)}</strong></p>
            <p><span>Scheduler Blocked</span><strong>{String(executionPackage.summary.scheduler_blocked_count ?? 0)}</strong></p>
            <p><span>总问题</span><strong>{executionPackage.issues.length}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>{executionPackage.package_id}</strong>
            <span>这是一份发布前真实执行包：标准对象视图、契约清单、运行规格、调度影子态与节点装配来自同一份后端编译结果。</span>
          </div>
          {runtimeSemantics ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>通用运行语义</strong><span>{String(recordValue(runtimeSemantics, "authority") ?? "runtime_semantics")}</span></header>
              <div className="task-graph-mini-kv">
                <p><span>节点语义</span><strong>{String(recordValue(runtimeSemanticsSummary, "node_count") ?? 0)}</strong></p>
                <p><span>边语义</span><strong>{String(recordValue(runtimeSemanticsSummary, "edge_count") ?? 0)}</strong></p>
                <p><span>旧字段</span><strong>{String(recordValue(runtimeSemanticsSummary, "legacy_field_count") ?? 0)}</strong></p>
                <p><span>诊断</span><strong>{String(recordValue(runtimeSemanticsSummary, "diagnostic_count") ?? runtimeSemanticDiagnostics.length)}</strong></p>
                <p><span>Dispatch 边界</span><strong>{recordValue(runtimeStepPolicy, "editor_visible") ? "可见" : "运行时"}</strong></p>
                <p><span>运行角色</span><strong>{String(recordValue(runtimeStepPolicy, "runtime_role") ?? "-")}</strong></p>
              </div>
              {runtimeSemanticDiagnostics.length ? (
                <div className="task-graph-preflight-list">
                  {runtimeSemanticDiagnostics.slice(0, 5).map((item, index) => {
                    const issue = item as Record<string, unknown>;
                    return (
                      <article className="task-graph-preflight-row" key={`${String(recordValue(issue, "code") ?? "runtime_semantics")}_${index}`}>
                        <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(recordValue(issue, "severity") ?? "warning")}`}>
                          {String(recordValue(issue, "severity") ?? "warning")}
                        </span>
                        <div>
                          <strong>{String(recordValue(issue, "code") ?? "runtime_semantics")}</strong>
                          <span>{String(recordValue(issue, "message") ?? "")}</span>
                          <small>{String(recordValue(issue, "scope") ?? "graph")} / {String(recordValue(issue, "ref_id") ?? "-")} / {String(recordValue(issue, "field") ?? "-")}</small>
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : null}
            </section>
          ) : null}
          {lengthBudget && recordValue(lengthBudget, "configured") ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>长度预算契约</strong><span>业务验收范围</span></header>
              <div className="task-graph-mini-kv">
                <p><span>范围</span><strong>{String(recordValue(lengthBudgetPreview, "budget_scope") ?? recordValue(lengthBudget, "budget_scope") ?? "-")}</strong></p>
                <p><span>计量</span><strong>{String(recordValue(lengthBudgetPreview, "measurement_mode") ?? recordValue(lengthBudget, "measurement_mode") ?? "-")}</strong></p>
                <p><span>单元</span><strong>{String(recordValue(lengthBudgetPreview, "unit_label_zh") ?? recordValue(lengthBudget, "unit_label_zh") ?? "-")}</strong></p>
                <p><span>目标</span><strong>{String(recordNumberValue(lengthBudget, "target_units"))}</strong></p>
                <p><span>最小</span><strong>{String(recordNumberValue(lengthBudget, "min_units"))}</strong></p>
                <p><span>最大</span><strong>{String(recordNumberValue(lengthBudget, "max_units"))}</strong></p>
                <p><span>单元数</span><strong>{String(recordNumberValue(lengthBudget, "batch_unit_count"))}</strong></p>
              </div>
            </section>
          ) : null}
          {splitPlans.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>批次拆分计划</strong><span>contract_bindings.unit_batch / runtime.split_policy</span></header>
              <div className="task-graph-preflight-list">
                {splitPlans.map((plan, index) => {
                  const batches = recordArrayValue(plan, "batches");
                  const lifecyclePlans = recordArrayValue(plan, "batch_lifecycle_plans");
                  const mergeReadinessPlan = recordValue(plan, "merge_readiness_plan") as Record<string, unknown> | null | undefined;
                  const acceptance = recordValue(plan, "acceptance_policy") as Record<string, unknown> | null | undefined;
                  const merge = recordValue(plan, "merge_policy") as Record<string, unknown> | null | undefined;
                  const issues = recordArrayValue(plan, "issues");
                  const valid = recordValue(plan, "valid") !== false && !issues.some((issue) => String((issue as Record<string, unknown>).severity ?? "error") === "error");
                  const firstBatch = batches[0] as Record<string, unknown> | undefined;
                  const lastBatch = batches[batches.length - 1] as Record<string, unknown> | undefined;
                  const firstRange = recordValue(firstBatch, "range") as Record<string, unknown> | null | undefined;
                  const lastRange = recordValue(lastBatch, "range") as Record<string, unknown> | null | undefined;
                  return (
                    <article className="task-graph-preflight-row task-graph-preflight-row--stacked" key={`${String(recordValue(plan, "plan_id") ?? index)}_split_plan`}>
                      <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${valid ? "info" : "error"}`}>
                        {valid ? "split_plan" : "blocked"}
                      </span>
                      <div>
                        <strong>{String(recordValue(plan, "unit_kind") ?? "unit")} · {batches.length} 批</strong>
                        <span>
                          节点 {String(recordValue(plan, "node_id") ?? "-")} / 总量 {String(recordValue(plan, "requested_count") ?? 0)} / 每批 {String(recordValue(plan, "batch_size") ?? 0)}
                        </span>
                        <small>
                          范围 {String(recordValue(firstRange, "label") ?? "-")} 至 {String(recordValue(lastRange, "label") ?? "-")}；
                          验收 {String(recordValue(acceptance, "mode") ?? "-")} / 合并 {String(recordValue(merge, "mode") ?? "-")}
                        </small>
                        {lifecyclePlans.length ? (
                          <div className="task-graph-batch-lifecycle-preview">
                            {lifecyclePlans.slice(0, 4).map((lifecyclePlan, lifecycleIndex) => {
                              const lifecycleRecord = lifecyclePlan as Record<string, unknown>;
                              const steps = recordArrayValue(lifecycleRecord, "steps");
                              return (
                                <p key={`${String(recordValue(lifecycleRecord, "plan_id") ?? lifecycleIndex)}_lifecycle`}>
                                  <span>{String(recordValue(lifecycleRecord, "batch_id") ?? `batch_${lifecycleIndex + 1}`)}</span>
                                  <strong>
                                    {steps.map((step) => String(recordValue(step as Record<string, unknown>, "step_type") ?? "step")).join(" -> ")}
                                  </strong>
                                </p>
                              );
                            })}
                            {lifecyclePlans.length > 4 ? <em>另有 {lifecyclePlans.length - 4} 个批次生命周期</em> : null}
                          </div>
                        ) : null}
                        {mergeReadinessPlan ? (
                          <small>
                            Merge {String(recordValue(mergeReadinessPlan, "ready_condition") ?? "-")}；
                            只消费 {String(recordValue(recordValue(mergeReadinessPlan, "metadata") as Record<string, unknown> | null | undefined, "merge_consumes") ?? "committed packet")}
                          </small>
                        ) : null}
                        {issues.length ? (
                          <small>{issues.map((issue) => String((issue as Record<string, unknown>).code ?? "split_issue")).join(" / ")}</small>
                        ) : null}
                      </div>
                      <em>{String(recordValue(plan, "plan_id") ?? "")}</em>
                      <small>{String(recordValue(recordValue(plan, "metadata") as Record<string, unknown> | null | undefined, "source_path") ?? "contract_bindings")}</small>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}
          {splitMergeIssues.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>批次契约问题</strong><span>Split / Review / Merge diagnostics</span></header>
              <div className="task-graph-preflight-list">
                {splitMergeIssues.slice(0, 8).map((issue, index) => (
                  <article className="task-graph-preflight-row" key={`${String(recordValue(issue, "code") ?? "split_issue")}_${index}`}>
                    <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(recordValue(issue, "severity") ?? "error")}`}>
                      {String(recordValue(issue, "severity") ?? "error")}
                    </span>
                    <div>
                      <strong>{String(recordValue(issue, "code") ?? "split_issue")}</strong>
                      <span>{String(recordValue(issue, "message") ?? "批次契约问题")}</span>
                    </div>
                    <em>{String(recordValue(issue, "node_id") ?? "")}</em>
                    <small>{String(recordValue(issue, "plan_id") ?? "")}</small>
                  </article>
                ))}
              </div>
            </section>
          ) : null}
          {executionPackage.node_runtime_assemblies.length ? (
            <div className="task-graph-preflight-list">
              {executionPackage.node_runtime_assemblies.slice(0, 6).map((assembly) => (
                <article className="task-graph-preflight-row" key={String(assembly.assembly_id)}>
                  <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">assembly</span>
                  <div>
                    <strong>{assembly.node_id || assembly.task_ref || assembly.assembly_id}</strong>
                    <span>context {assembly.context_sections.length} / output {assembly.output_contracts.length} / handoff {(assembly.handoff_packets ?? []).length}</span>
                  </div>
                  <em>{assembly.agent_id || "-"}</em>
                  <small>{assembly.projection_id || assembly.runtime_lane || "runtime_assembly"}</small>
                </article>
              ))}
            </div>
          ) : null}
          {objectTraceIndex.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>对象追溯索引</strong><span>Graph object {"->"} runtime facts</span></header>
              <div className="task-graph-preflight-list">
                {objectTraceIndex.slice(0, 8).map((item, index) => {
                  const runtimeRef = recordValue(item, "runtime_ref") as Record<string, unknown> | null | undefined;
                  const manifestRef = recordValue(item, "manifest_ref") as Record<string, unknown> | null | undefined;
                  const schedulerRef = recordValue(item, "scheduler_ref") as Record<string, unknown> | null | undefined;
                  return (
                    <article className="task-graph-preflight-row" key={`${String(recordValue(item, "object_type") ?? "object")}_${String(recordValue(item, "object_id") ?? index)}`}>
                      <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">
                        {String(recordValue(item, "object_type") ?? "object")}
                      </span>
                      <div>
                        <strong>{String(recordValue(item, "title") ?? recordValue(item, "object_id") ?? "未命名对象")}</strong>
                        <span>
                          runtime {String(recordValue(runtimeRef, "node_id") ?? recordValue(runtimeRef, "edge_id") ?? recordValue(runtimeRef, "runtime_node_id") ?? recordValue(runtimeRef, "runtime_spec_graph_id") ?? "-")} /
                          manifest {String(recordValue(manifestRef, "node_contract_id") ?? recordValue(manifestRef, "edge_contract_id") ?? recordValue(manifestRef, "handoff_contract_id") ?? recordValue(manifestRef, "manifest_id") ?? "-")}
                        </span>
                      </div>
                      <em>{String(recordValue(schedulerRef, "status") ?? recordValue(item, "status") ?? "-")}</em>
                      <small>{String(recordValue(item, "source_path") ?? "")}</small>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}
          {graphModuleExecutionPlans.length ? (
            <section className="task-graph-runtime-spec-panel">
              <header><strong>导入图模块执行计划</strong><span>Module node / Imported package preview</span></header>
              <div className="task-graph-preflight-list">
                {graphModuleExecutionPlans.map((plan, index) => {
                  const importedGraph = recordValue(plan, "imported_graph") as Record<string, unknown> | null | undefined;
                  const runtimeSummary = recordValue(plan, "imported_runtime_spec_summary") as Record<string, unknown> | null | undefined;
                  const manifestSummary = recordValue(plan, "imported_contract_manifest_summary") as Record<string, unknown> | null | undefined;
                  const schedulerSummary = recordValue(plan, "imported_scheduler_summary") as Record<string, unknown> | null | undefined;
                  const assemblySummary = recordValue(plan, "imported_node_runtime_assembly_summary") as Record<string, unknown> | null | undefined;
                  const planIssues = recordArrayValue(plan, "issues");
                  const valid = recordValue(plan, "valid") !== false && !planIssues.some((issue) => String((issue as Record<string, unknown>).severity ?? "error") === "error");
                  return (
                    <article className="task-graph-preflight-row task-graph-preflight-row--stacked" key={`${String(recordValue(plan, "plan_id") ?? index)}`}>
                      <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${valid ? "info" : "error"}`}>
                        {valid ? "ready" : "blocked"}
                      </span>
                      <div>
                        <strong>{String(recordValue(importedGraph, "title") ?? recordValue(plan, "linked_graph_id") ?? "未绑定图模块")}</strong>
                        <span>
                          模块节点 {String(recordValue(plan, "runtime_node_id") ?? "-")} / 导入模块 {String(recordValue(plan, "linked_graph_id") ?? "-")} / 版本 {String(recordValue(plan, "version_ref") ?? "未锚定")}
                        </span>
                        <small>
                          Runtime {recordNumberValue(runtimeSummary, "node_count")} 节点 / {recordNumberValue(runtimeSummary, "edge_count")} 边；
                          Manifest {recordNumberValue(manifestSummary, "node_contract_count")} 节点契约 / {recordNumberValue(manifestSummary, "edge_handoff_contract_count")} 边契约；
                          Scheduler ready {recordArrayValue(schedulerSummary, "ready_node_ids").length} / blocked {recordArrayValue(schedulerSummary, "blocked_node_ids").length}；
                          Assembly {recordNumberValue(assemblySummary, "assembly_count")}
                        </small>
                        {planIssues.length ? (
                          <small>{planIssues.map((issue) => String((issue as Record<string, unknown>).code ?? "graph_module_issue")).join(" / ")}</small>
                        ) : null}
                      </div>
                      <em>{String(recordValue(plan, "handoff_contract_id") ?? "无交接契约")}</em>
                      <small>{String(recordValue(plan, "isolation_policy") ?? "isolated_per_graph_module_run")}</small>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
      {contractManifest ? (
        <div className="task-graph-runtime-spec-panel">
          <div className="task-graph-mini-kv">
            <p><span>Manifest</span><strong>{contractManifest.valid ? "通过" : "待修复"}</strong></p>
            <p><span>图契约</span><strong>{Object.keys(contractManifest.graph_contract_bindings ?? {}).length}</strong></p>
            <p><span>节点契约</span><strong>{contractManifest.node_contracts.length}</strong></p>
            <p><span>边契约</span><strong>{contractManifest.edge_handoff_contracts.length}</strong></p>
            <p><span>图模块契约</span><strong>{(contractManifest.graph_module_handoff_contracts ?? []).length}</strong></p>
            <p><span>问题</span><strong>{contractManifest.issues.length}</strong></p>
          </div>
          {(contractManifest.graph_module_handoff_contracts ?? []).length ? (
            <div className="task-graph-preflight-list">
              {(contractManifest.graph_module_handoff_contracts ?? []).slice(0, 6).map((item, index) => (
                <article className="task-graph-preflight-row" key={`${String(recordValue(item, "plan_id") ?? index)}_graph_module_handoff`}>
                  <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">graph_module</span>
                  <div>
                    <strong>{String(recordValue(item, "linked_graph_id") ?? "未绑定图模块")}</strong>
                    <span>
                      {String(recordValue(item, "runtime_node_id") ?? "-")} / {String(recordValue(item, "input_port_id") ?? "input.default")} {"->"} {String(recordValue(item, "output_port_id") ?? "output.default")}
                    </span>
                  </div>
                  <em>{String(recordValue(item, "handoff_contract_id") ?? "无交接契约")}</em>
                  <small>graph_module_handoff</small>
                </article>
              ))}
            </div>
          ) : null}
          {contractManifest.issues.length ? (
            <div className="task-graph-preflight-list">
              {contractManifest.issues.slice(0, 8).map((issue, index) => (
                <article className="task-graph-preflight-row" key={`${issue.code}_${index}`}>
                  <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(issue.severity ?? "error")}`}>
                    {String(issue.severity ?? "error")}
                  </span>
                  <div>
                    <strong>{issue.code}</strong>
                    <span>{issue.message}</span>
                  </div>
                  <em>{issue.node_id || issue.edge_id || issue.source_ref}</em>
                  <small>contract_manifest</small>
                </article>
              ))}
            </div>
          ) : (
            <div className="task-graph-note">
              <strong>契约清单没有阻塞问题</strong>
              <span>图、节点、边的 contract_bindings 已经进入发布前清单。</span>
            </div>
          )}
        </div>
      ) : null}
      {runtimeSpec ? (
        <div className="task-graph-runtime-spec-panel">
          <div className="task-graph-mini-kv">
            <p><span>来源</span><strong>{String(runtimeSpec.diagnostics?.source ?? "runtime_spec")}</strong></p>
            <p><span>节点</span><strong>{runtimeSpec.nodes.length}</strong></p>
            <p><span>有效</span><strong>{runtimeSpec.valid ? "通过" : "待修复"}</strong></p>
            <p><span>起点</span><strong>{listText(runtimeSpec.start_node_ids) || "-"}</strong></p>
            <p><span>终点</span><strong>{listText(runtimeSpec.terminal_node_ids) || "-"}</strong></p>
            <p><span>通信</span><strong>{listText(runtimeSpec.communication_modes) || "-"}</strong></p>
            <p><span>图模块</span><strong>{(runtimeSpec.graph_module_runtime_plans ?? runtimeSpec.graph_modules ?? []).length}</strong></p>
          </div>
          {(runtimeSpec.graph_module_runtime_plans ?? runtimeSpec.graph_modules ?? []).length ? (
            <div className="task-graph-preflight-list">
              {(runtimeSpec.graph_module_runtime_plans ?? runtimeSpec.graph_modules ?? []).map((plan, index) => (
                <article className="task-graph-preflight-row" key={`${String(plan.plan_id ?? plan.runtime_node_id ?? index)}`}>
                  <span className="task-graph-preflight-row__severity task-graph-preflight-row__severity--info">graph_module</span>
                  <div>
                    <strong>{String(plan.linked_graph_id ?? "未绑定图模块")}</strong>
                    <span>{String(plan.plan_id ?? "")} / {String(plan.version_ref ?? "未锚定版本")}</span>
                  </div>
                  <em>{String(plan.runtime_node_id ?? plan.unit_id ?? "")}</em>
                  <small>{String(plan.handoff_contract_id ?? "无交接契约")}</small>
                </article>
              ))}
            </div>
          ) : null}
          {runtimeSpec.issues.length ? (
            <div className="task-graph-preflight-list">
              {runtimeSpec.issues.map((issue, index) => (
                <article className="task-graph-preflight-row" key={`${runtimeIssueTitle(issue, index)}_${index}`}>
                  <span className={`task-graph-preflight-row__severity task-graph-preflight-row__severity--${String(issue.severity ?? "error")}`}>
                    {String(issue.severity ?? "error")}
                  </span>
                  <div>
                    <strong>{runtimeIssueTitle(issue, index)}</strong>
                    <span>{String(issue.message ?? "运行规范问题")}</span>
                  </div>
                  <em>{String(issue.node_id ?? issue.edge_id ?? "runtime")}</em>
                  <small>backend.runtime_spec</small>
                </article>
              ))}
            </div>
          ) : (
            <div className="task-graph-note">
              <strong>运行规范没有阻塞问题</strong>
              <span>后端 direct compiler 已经返回可运行的 runtime spec。</span>
            </div>
          )}
          <details className="task-graph-runtime-spec-details">
            <summary>诊断抽屉</summary>
            <RawDiagnosticsDetails title="RuntimeSpec 原始诊断">
              {JSON.stringify(runtimeSpec.diagnostics ?? {}, null, 2)}
            </RawDiagnosticsDetails>
            {contractManifest ? (
              <RawDiagnosticsDetails title="ContractManifest 原始清单">
                {JSON.stringify(contractManifest, null, 2)}
              </RawDiagnosticsDetails>
            ) : null}
          </details>
        </div>
      ) : (
        <div className={runtimeSpecError ? "task-graph-note task-graph-note--danger" : "task-graph-note"}>
          <strong>{runtimeSpecError ? "执行包不可用" : "尚未编译执行包"}</strong>
          <span>{runtimeSpecError || "点击“编译执行包”后，平台会从 TaskGraphDefinition 生成契约清单、运行规格和调度影子态。"}</span>
        </div>
      )}
    </section>
  );
}
