"use client";

import { AlertTriangle, Bug, CheckCircle2, Clock3, Play, Search } from "lucide-react";

import type { HealthAgentRun, HealthIssue, HealthProblemNode } from "@/lib/api";

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(" / ") : fallback;
  }
  return String(value);
}

function severityTone(severity: string) {
  const value = severity.toLowerCase();
  if (value.includes("high") || value.includes("critical")) {
    return "health-pill--danger";
  }
  if (value.includes("low")) {
    return "health-pill--success";
  }
  return "health-pill--warning";
}

function statusIcon(status: string) {
  const value = status.toLowerCase();
  if (value.includes("resolved") || value.includes("closed")) {
    return CheckCircle2;
  }
  if (value.includes("blocked") || value.includes("failed")) {
    return AlertTriangle;
  }
  return Clock3;
}

function statusLabel(status: string) {
  if (status === "triage_ready") return "待分析";
  if (status === "running") return "分析中";
  if (status === "completed") return "已完成";
  if (status === "resolved" || status === "closed") return "已关闭";
  if (status === "blocked" || status === "failed") return "阻断";
  return status || "未知";
}

function severityLabel(severity: string) {
  const value = severity.toLowerCase();
  if (value.includes("critical")) return "严重";
  if (value.includes("high")) return "高";
  if (value.includes("medium")) return "中";
  if (value.includes("low")) return "低";
  return severity || "未定级";
}

function systemLabel(system: string) {
  const labels: Record<string, string> = {
    query_runtime: "入口适配",
    task_system: "任务系统",
    capability_system: "能力系统",
    memory_system: "记忆系统",
    skill_system: "技能系统",
    model_system: "模型运行",
    orchestration_system: "编排系统",
    runtime_loop: "运行链路",
    runtime: "运行时"
  };
  return labels[system] || system || "未归属";
}

function sourceLabel(source: string) {
  const labels: Record<string, string> = {
    manual: "手动记录",
    agent: "子 Agent 提交",
    runtime: "运行时记录",
    sample: "样例数据"
  };
  return labels[source] || source || "未知来源";
}

function issueLayerLabel(issue: HealthIssue) {
  if (["runtime_loop", "runtime", "orchestration_system", "task_system"].includes(issue.owner_system)) return "系统问题";
  return "用户/体验问题";
}

function laneLabel(lane: string) {
  if (lane === "health_issue_read") return "健康问题只读";
  return lane ? "健康分析链路" : "未绑定";
}

function terminalLabel(reason: string) {
  if (!reason) return "等待结果";
  if (reason === "completed") return "已完成";
  if (reason === "running") return "运行中";
  if (reason === "not_executed_sample") return "样例记录";
  return reason;
}

export function HealthIssuePanel({
  issues,
  problemNodes,
  runs,
  selectedIssueId,
  runningIssueId,
  onSelectIssue,
  onRunIssue
}: {
  issues: HealthIssue[];
  problemNodes: HealthProblemNode[];
  runs: HealthAgentRun[];
  selectedIssueId: string;
  runningIssueId: string;
  onSelectIssue: (issue: HealthIssue) => void;
  onRunIssue: (issue: HealthIssue) => void;
}) {
  const selectedIssue = issues.find((issue) => issue.issue_id === selectedIssueId) ?? issues[0] ?? null;
  const selectedNodes = selectedIssue ? problemNodes.filter((node) => node.issue_id === selectedIssue.issue_id) : [];
  const selectedRuns = selectedIssue ? runs.filter((run) => run.issue_id === selectedIssue.issue_id) : [];

  return (
    <div className="health-issue-layout">
      <section className="health-list-panel">
        <div className="health-panel-head">
          <div>
            <span>问题处理</span>
            <h3>问题中心</h3>
          </div>
          <Search size={16} />
        </div>
        <div className="health-issue-list">
          {issues.map((issue) => {
            const Icon = statusIcon(issue.status);
            const active = issue.issue_id === selectedIssue?.issue_id;
            return (
              <button
                className={`health-issue-row ${active ? "health-issue-row--active" : ""}`}
                key={issue.issue_id}
                onClick={() => onSelectIssue(issue)}
                type="button"
              >
                <Icon size={16} />
                <div>
                  <strong>{issue.title}</strong>
                  <span>{issueLayerLabel(issue)} · {systemLabel(issue.owner_system)} · {sourceLabel(issue.source)}</span>
                </div>
                <em className={`health-pill ${severityTone(issue.severity)}`}>{severityLabel(issue.severity)}</em>
              </button>
            );
          })}
        </div>
      </section>

      <section className="health-detail-panel">
        {selectedIssue ? (
          <>
            <div className="health-detail-panel__title">
              <div>
                <span>当前问题</span>
                <h3>{selectedIssue.title}</h3>
              </div>
              <button
                className="action-button action-button--primary"
                disabled={runningIssueId === selectedIssue.issue_id}
                onClick={() => onRunIssue(selectedIssue)}
                type="button"
              >
                <Play size={15} />
                {runningIssueId === selectedIssue.issue_id ? "分析中" : "分析当前问题"}
              </button>
            </div>
            <div className="health-evidence-grid">
              <EvidenceCell label="问题分层" value={issueLayerLabel(selectedIssue)} />
              <EvidenceCell label="归属系统" value={systemLabel(selectedIssue.owner_system)} />
              <EvidenceCell label="处理状态" value={statusLabel(selectedIssue.status)} />
              <EvidenceCell label="证据引用" value={selectedIssue.conversation_ref ? 1 : 0} />
              <EvidenceCell label="运行痕迹" value={selectedIssue.runtime_trace_refs?.length ?? 0} />
              <EvidenceCell label="提示证据" value={selectedIssue.prompt_manifest_refs?.length ?? 0} />
              <EvidenceCell label="记忆证据" value={selectedIssue.memory_refs?.length ?? 0} />
            </div>
            <div className="health-subsection">
              <div className="health-panel-head">
                <div>
                  <span>问题节点</span>
                  <h3>问题节点</h3>
                </div>
                <Bug size={16} />
              </div>
              {selectedNodes.length ? (
                <div className="health-node-list">
                  {selectedNodes.map((node) => (
                    <article className="health-node-row" key={node.node_id}>
                      <strong>{systemLabel(node.system)} / {text(node.stage, "待定位")}</strong>
                      <p>{node.diagnosis || "暂无诊断。"}</p>
                      <div className="health-ref-row">
                        <em>置信度 {Math.round((node.confidence || 0) * 100)}%</em>
                        <em>证据 {node.evidence_refs.length}</em>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="health-empty-state">暂无问题节点候选。</div>
              )}
            </div>
            <div className="health-subsection">
              <div className="health-panel-head">
                <div>
                  <span>关联运行</span>
                  <h3>关联运行</h3>
                </div>
                <Clock3 size={16} />
              </div>
              {selectedRuns.length ? (
                <div className="health-run-mini-list">
                  {selectedRuns.map((run) => (
                    <article key={run.run_id}>
                      <strong>{statusLabel(run.status)}</strong>
                      <span>{laneLabel(run.runtime_lane)} · {terminalLabel(run.terminal_reason)}</span>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="health-empty-state">还没有关联运行。</div>
              )}
            </div>
          </>
        ) : (
          <div className="health-empty-state">暂无健康问题。</div>
        )}
      </section>
    </div>
  );
}

function EvidenceCell({ label, value }: { label: string; value: unknown }) {
  return (
    <article>
      <span>{label}</span>
      <strong>{text(value, "0")}</strong>
    </article>
  );
}
