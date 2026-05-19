"use client";

import { AlertTriangle, CheckCircle2, FileWarning, Info } from "lucide-react";

import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";
import type { TaskGraphPreflightIssue, TaskGraphPreflightReport } from "./taskGraphPreflight";

function severityIcon(severity: TaskGraphPreflightIssue["severity"]) {
  if (severity === "error") return AlertTriangle;
  if (severity === "warning") return FileWarning;
  return Info;
}

function subjectForIssue(issue: TaskGraphPreflightIssue): TaskGraphComposableSubject {
  if (issue.scope === "port_edge" && issue.target_id) return { kind: "port_edge", edge_id: issue.target_id };
  if (issue.scope === "unit" && issue.target_id) return { kind: "unit", unit_id: issue.target_id };
  return { kind: "issue", issue };
}

export function TaskGraphDiagnosticsDock({
  onSelectSubject,
  report,
  standardViewIssueCount,
}: {
  onSelectSubject: (subject: TaskGraphComposableSubject) => void;
  report: TaskGraphPreflightReport;
  standardViewIssueCount: number;
}) {
  const visibleIssues = report.issues.slice(0, 8);
  return (
    <section className="task-graph-composer-dock" aria-label="诊断与预检">
      <header className="task-graph-composer-dock__head">
        <div>
          {report.valid ? <CheckCircle2 aria-hidden="true" size={16} /> : <AlertTriangle aria-hidden="true" size={16} />}
          <strong>{report.valid ? "预检可通过" : "预检存在阻塞"}</strong>
          <span>{report.error_count} 阻塞 / {report.warning_count} 警告 / {report.info_count} 提示 / 标准视图 {standardViewIssueCount}</span>
        </div>
      </header>
      {visibleIssues.length ? (
        <div className="task-graph-composer-dock__list">
          {visibleIssues.map((issue) => {
            const Icon = severityIcon(issue.severity);
            return (
              <button className={`task-graph-composer-diagnostic task-graph-composer-diagnostic--${issue.severity}`} key={issue.issue_id} onClick={() => onSelectSubject(subjectForIssue(issue))} type="button">
                <Icon aria-hidden="true" size={14} />
                <span>
                  <strong>{issue.title}</strong>
                  <small>{issue.scope}{issue.target_id ? `:${issue.target_id}` : ""} / {issue.source}</small>
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="task-graph-composer-dock__empty">当前没有预检问题，仍可刷新标准视图确认后端合并结果。</div>
      )}
    </section>
  );
}

