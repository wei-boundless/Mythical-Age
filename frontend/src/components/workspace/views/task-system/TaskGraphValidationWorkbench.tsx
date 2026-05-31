"use client";

import { AlertTriangle, CheckCircle2, FileCheck2, GitBranch, RefreshCw, Wrench } from "lucide-react";

import type { TaskGraphStandardView } from "@/lib/api";

import { buildTaskGraphMemoryModel } from "./taskGraphMemoryMatrix";
import type { TaskGraphPreflightIssue, TaskGraphPreflightReport } from "./taskGraphPreflight";

function severityLabel(severity: TaskGraphPreflightIssue["severity"]) {
  if (severity === "error") return "阻塞";
  if (severity === "warning") return "需处理";
  return "建议";
}

function issueGroup(issue: TaskGraphPreflightIssue) {
  if (issue.source.includes("prompt") || issue.source.includes("cognition")) return "节点职责与输入包";
  if (issue.source.includes("memory") || issue.source.includes("artifact")) return "资源与产物";
  if (issue.source.includes("timeline") || issue.source.includes("revision")) return "生命周期与返修";
  if (issue.source.includes("human_gate") || issue.source.includes("manual")) return "人工门控";
  if (issue.source.includes("contract") || issue.source.includes("review_gate")) return "契约与质量门";
  if (issue.source.includes("runtime") || issue.source.includes("scheduler")) return "运行装配";
  return "图结构";
}

function repairActionLabel(issue: TaskGraphPreflightIssue) {
  if (issue.source === "frontend.preflight.prompt_semantics") return "打开 Prompt";
  if (issue.source === "frontend.preflight.cognition_packet") return "补输入说明";
  if (issue.source === "frontend.preflight.contract" && issue.scope === "edge") return "补载荷契约";
  if (issue.source === "frontend.preflight.memory_handoff") return "补摘要交接";
  if (issue.source === "frontend.preflight.memory_selector") return "补 Selector";
  if (issue.source === "frontend.preflight.memory_commit_path") return "补提交路径";
  if (issue.source === "frontend.preflight.revision_packet") return "补返修包";
  if (issue.source === "frontend.preflight.artifact") return "配置产物";
  if (issue.source === "frontend.preflight.human_gate") return "配置门控";
  if (issue.source === "frontend.preflight.timeline" && issue.scope === "phase") return "补阶段";
  return "";
}

export function TaskGraphValidationWorkbench({
  activeGraphEdges,
  activeGraphNodes,
  onFocusIssue,
  onRefreshStandardView,
  onRepairIssue,
  preflightReport,
  standardView,
  standardViewError,
  standardViewLoading,
  standardViewStale,
}: {
  activeGraphEdges: Array<Record<string, unknown>>;
  activeGraphNodes: Array<Record<string, unknown>>;
  onFocusIssue: (issue: TaskGraphPreflightIssue) => void;
  onRefreshStandardView: () => void;
  onRepairIssue: (issue: TaskGraphPreflightIssue) => void;
  preflightReport: TaskGraphPreflightReport;
  standardView: TaskGraphStandardView | null;
  standardViewError: string;
  standardViewLoading: boolean;
  standardViewStale: boolean;
}) {
  const memoryModel = buildTaskGraphMemoryModel({ nodes: activeGraphNodes, edges: activeGraphEdges });
  const groupedIssues = Array.from(
    preflightReport.issues.reduce((groups, issue) => {
      const group = issueGroup(issue);
      groups.set(group, [...(groups.get(group) ?? []), issue]);
      return groups;
    }, new Map<string, TaskGraphPreflightIssue[]>()),
  );

  return (
    <section className="task-graph-validation-workbench" aria-label="任务图检查与修复">
      <header className="task-graph-validation-head">
        <div>
          <span>检查修复</span>
          <strong>{preflightReport.valid ? "当前没有发布阻塞" : "当前任务图需要处理阻塞项"}</strong>
          <small>这里按问题定位对象，能自动补齐的直接修复，不能自动补齐的回到画布 Inspector。</small>
        </div>
        <button disabled={standardViewLoading} onClick={onRefreshStandardView} type="button">
          <RefreshCw aria-hidden="true" size={15} />
          刷新标准视图
        </button>
      </header>

      <section className="task-graph-validation-metrics" aria-label="检查指标">
        <article>
          <span>阻塞</span>
          <strong>{preflightReport.error_count}</strong>
        </article>
        <article>
          <span>警告</span>
          <strong>{preflightReport.warning_count}</strong>
        </article>
        <article>
          <span>建议</span>
          <strong>{preflightReport.info_count}</strong>
        </article>
        <article>
          <span>记忆资源</span>
          <strong>{memoryModel.repositories.length} / {memoryModel.memoryEdges.length}</strong>
        </article>
        <article>
          <span>标准对象</span>
          <strong>{standardView ? `${standardView.nodes.length} 节点` : "未载入"}</strong>
        </article>
      </section>

      <section className="task-graph-validation-grid">
        <article className="boundary-card task-graph-validation-standard">
          <header>
            <FileCheck2 aria-hidden="true" size={16} />
            <strong>标准对象视图</strong>
            <span>{standardViewStale ? "已过期" : standardView ? "已对齐" : "未载入"}</span>
          </header>
          {standardViewError ? (
            <div className="task-graph-validation-error">
              <AlertTriangle aria-hidden="true" size={15} />
              <span>{standardViewError}</span>
            </div>
          ) : null}
          <div className="task-graph-mini-kv">
            <p><span>节点</span><strong>{standardView?.nodes.length ?? activeGraphNodes.length}</strong></p>
            <p><span>边</span><strong>{standardView?.edges.length ?? activeGraphEdges.length}</strong></p>
            <p><span>资源</span><strong>{standardView?.resources.length ?? memoryModel.repositories.length}</strong></p>
            <p><span>接口</span><strong>{standardView?.interfaces?.length ?? 0}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>用途</strong>
            <span>标准对象用于解释、预检和发布依据；编辑仍回到画布节点、边和资源意图。</span>
          </div>
        </article>

        <article className="boundary-card task-graph-validation-standard">
          <header>
            <GitBranch aria-hidden="true" size={16} />
            <strong>图语义覆盖</strong>
            <span>结构健康</span>
          </header>
          <div className="task-graph-mini-kv">
            <p><span>执行节点</span><strong>{activeGraphNodes.filter((node) => String(node.role ?? node.work_posture) !== "resource").length}</strong></p>
            <p><span>资源节点</span><strong>{activeGraphNodes.filter((node) => String(node.role ?? node.work_posture) === "resource").length}</strong></p>
            <p><span>记忆读写</span><strong>{memoryModel.memoryEdges.length}</strong></p>
            <p><span>可见问题</span><strong>{preflightReport.issue_count}</strong></p>
          </div>
          <div className="task-graph-note">
            <strong>优化判断</strong>
            <span>常见修复应在问题列表完成；复杂语义配置回到选中对象 Inspector，而不是跳进底层页面。</span>
          </div>
        </article>
      </section>

      <section className="task-graph-validation-issues">
        <header>
          <strong>问题队列</strong>
          <span>{preflightReport.issue_count ? `${preflightReport.issue_count} 项` : "没有问题"}</span>
        </header>
        {!groupedIssues.length ? (
          <div className="task-graph-validation-empty">
            <CheckCircle2 aria-hidden="true" size={18} />
            <strong>检查通过</strong>
            <span>可以进入发布运行页继续编译和启动。</span>
          </div>
        ) : null}
        {groupedIssues.map(([group, issues]) => (
          <article className="task-graph-validation-group" key={group}>
            <header>
              <strong>{group}</strong>
              <span>{issues.length} 项</span>
            </header>
            <div className="task-graph-validation-issue-list">
              {issues.map((issue) => {
                const repairLabel = repairActionLabel(issue);
                return (
                  <section className={`task-graph-validation-issue task-graph-validation-issue--${issue.severity}`} key={issue.issue_id}>
                    <div>
                      <span>{severityLabel(issue.severity)} · {issue.scope}{issue.target_id ? ` · ${issue.target_id}` : ""}</span>
                      <strong>{issue.title}</strong>
                      <small>{issue.detail}</small>
                    </div>
                    <div className="task-graph-validation-issue__actions">
                      <button onClick={() => onFocusIssue(issue)} type="button">
                        <GitBranch aria-hidden="true" size={14} />
                        定位
                      </button>
                      {repairLabel ? (
                        <button onClick={() => onRepairIssue(issue)} type="button">
                          <Wrench aria-hidden="true" size={14} />
                          {repairLabel}
                        </button>
                      ) : null}
                    </div>
                  </section>
                );
              })}
            </div>
          </article>
        ))}
      </section>
    </section>
  );
}
