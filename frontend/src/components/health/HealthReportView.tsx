"use client";

import { AlertTriangle, CheckCircle2, ClipboardList, GitBranch, ListChecks, ShieldAlert, Wrench } from "lucide-react";

import type { HealthAgentRun, HealthIssue, HealthProblemNode, HealthTraceReport } from "@/lib/api";

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(" / ") : fallback;
  }
  return String(value);
}

function resultContent(result: Record<string, unknown> | null) {
  if (!result) {
    return "";
  }
  return text(result.content || result.summary || result.result || "");
}

function statusLabel(status?: string) {
  if (!status) return "未生成";
  if (status === "running") return "运行中";
  if (status === "passed") return "通过";
  if (status === "failed") return "失败";
  if (status === "warning") return "警告";
  if (status === "completed") return "完成";
  if (status === "blocked") return "阻断";
  if (status === "triage_ready") return "待分析";
  return status;
}

function systemLabel(system?: string) {
  const labels: Record<string, string> = {
    task_system: "任务系统",
    capability_system: "能力系统",
    memory_system: "记忆系统",
    soul_system: "灵魂系统",
    skill_system: "技能系统",
    orchestration_system: "编排系统",
    runtime_loop: "运行链路",
    test_system: "测试系统"
  };
  return system ? labels[system] || system : "未归属";
}

function severityLabel(severity?: string) {
  if (!severity) return "未定级";
  const value = severity.toLowerCase();
  if (value.includes("critical")) return "严重";
  if (value.includes("high")) return "高";
  if (value.includes("medium")) return "中";
  if (value.includes("low")) return "低";
  return severity;
}

function laneLabel(lane?: string) {
  if (!lane) return "未绑定";
  if (lane === "health_issue_read") return "健康问题只读";
  if (lane === "codex_smoke_test") return "冒烟验证";
  return "健康分析链路";
}

function boundLabel(value?: string) {
  return value ? "已绑定" : "未绑定";
}

function terminalLabel(reason?: string) {
  if (!reason) return "等待结果";
  if (reason === "completed") return "已完成";
  if (reason === "not_executed_sample") return "样例记录";
  if (reason === "running") return "运行中";
  return reason;
}

function evidenceState(count: number) {
  if (count >= 4) return "证据较完整";
  if (count >= 2) return "证据可用";
  if (count >= 1) return "证据偏少";
  return "证据缺失";
}

export function HealthReportView({
  selectedIssue,
  selectedRun,
  problemNodes,
  traceReport
}: {
  selectedIssue: HealthIssue | null;
  selectedRun: HealthAgentRun | null;
  problemNodes: HealthProblemNode[];
  traceReport: HealthTraceReport | null;
}) {
  const content = resultContent(traceReport?.result ?? null);
  const relevantNodes = selectedIssue ? problemNodes.filter((node) => node.issue_id === selectedIssue.issue_id) : [];
  const primaryNode = relevantNodes[0] ?? null;
  const firstProblemEvent = traceReport?.problem_events?.[0] as Record<string, unknown> | undefined;
  const evidenceCount = [
    selectedIssue?.conversation_ref,
    ...(selectedIssue?.runtime_trace_refs ?? []),
    ...(selectedIssue?.prompt_manifest_refs ?? []),
    ...(selectedIssue?.memory_refs ?? []),
    ...(selectedIssue?.assertion_refs ?? [])
  ].filter(Boolean).length;
  const whereText = primaryNode
    ? `${systemLabel(primaryNode.system)} / ${primaryNode.stage}`
    : selectedIssue
      ? systemLabel(selectedIssue.owner_system)
      : "等待定位";
  const whyText = primaryNode?.diagnosis
    || text(firstProblemEvent?.summary, "")
    || content
    || "当前证据不足，还不能稳定解释问题原因。";
  const actionText = primaryNode?.suggested_action
    || (content ? "按候选结论复核证据，并把复现路径沉淀为用例。" : "先绑定运行证据或执行健康分析。");

  return (
    <div className="health-report-view">
      <section className="health-diagnosis-brief">
        <div className="health-diagnosis-brief__title">
          <span className={`health-pill ${selectedIssue ? "health-pill--warning" : ""}`}>
            {selectedIssue ? severityLabel(selectedIssue.severity) : "未选择"}
          </span>
          <div>
            <span>问题报告</span>
            <h3>{selectedIssue?.title || "等待选择一个健康问题"}</h3>
          </div>
        </div>
        <div className="health-diagnosis-grid">
          <article className="health-diagnosis-card health-diagnosis-card--where">
            <GitBranch size={18} />
            <span>哪里出了问题</span>
            <strong>{whereText}</strong>
            <p>{primaryNode ? `置信度 ${Math.round(primaryNode.confidence * 100)}%，已定位到问题节点。` : "还没有稳定的问题节点，需要在报告内补齐链路分析。"}</p>
          </article>
          <article className="health-diagnosis-card health-diagnosis-card--why">
            <AlertTriangle size={18} />
            <span>为什么出问题</span>
            <strong>{content ? "已有候选解释" : primaryNode ? "节点诊断可用" : "解释不足"}</strong>
            <p>{whyText}</p>
          </article>
          <article className="health-diagnosis-card health-diagnosis-card--action">
            <Wrench size={18} />
            <span>下一步怎么处理</span>
            <strong>{primaryNode?.suggested_action ? "按节点建议处理" : content ? "复核并沉淀用例" : "补齐证据"}</strong>
            <p>{actionText}</p>
          </article>
        </div>
      </section>

      <section className="health-report-columns health-report-columns--decision">
        <article className="health-report-decision-card">
          <div className="health-panel-head">
            <div>
              <span>结论依据</span>
              <h3>为什么可以这么判断</h3>
            </div>
            <ClipboardList size={16} />
          </div>
          <div className="health-report-answer">
            <strong>{content || primaryNode?.diagnosis || "暂无候选诊断"}</strong>
            <p>{selectedRun ? `健康分析状态：${statusLabel(selectedRun.status)} / ${terminalLabel(selectedRun.terminal_reason)}。` : "还没有健康分析运行，报告只能展示已知问题和证据缺口。"}</p>
          </div>
          <div className="health-report-proof-row">
            <span>{evidenceState(evidenceCount)}</span>
            <span>{traceReport?.event_count ?? 0} 个运行事件</span>
            <span>{relevantNodes.length} 个问题节点</span>
          </div>
        </article>

        <article className="health-report-decision-card">
          <div className="health-panel-head">
            <div>
              <span>复核清单</span>
              <h3>用户该先看什么</h3>
            </div>
            <ShieldAlert size={16} />
          </div>
          <div className="health-review-checks">
            <div>
              <CheckCircle2 size={15} />
              <span>问题节点是否指向真实故障位置</span>
            </div>
            <div>
              <CheckCircle2 size={15} />
              <span>解释是否能被运行事件或测试失败支撑</span>
            </div>
            <div>
              <CheckCircle2 size={15} />
              <span>修复动作是否能转成验证用例</span>
            </div>
          </div>
        </article>
      </section>

      <section className="health-report-summary health-report-summary--compact">
        <div className="health-panel-head">
          <div>
            <span>问题节点</span>
            <h3>定位路径</h3>
          </div>
          <ListChecks size={16} />
        </div>
        {relevantNodes.length ? (
          <div className="health-node-list">
            {relevantNodes.map((node) => (
              <article className="health-node-row" key={node.node_id}>
                <span>{systemLabel(node.system)}</span>
                <strong>{node.stage}</strong>
                <p>{node.diagnosis || node.suggested_action}</p>
                {node.suggested_action ? <em>{node.suggested_action}</em> : null}
              </article>
            ))}
          </div>
        ) : (
          <div className="health-empty-state">还没有定位到问题节点。请在当前问题报告内查看节点关系，并补齐证据。</div>
        )}
        <details className="health-report-technical-details">
          <summary>查看技术引用</summary>
          <dl className="health-report-dl">
            <div>
              <dt>运行通道</dt>
              <dd>{laneLabel(selectedRun?.runtime_lane)}</dd>
            </div>
            <div>
              <dt>工作流</dt>
              <dd>{boundLabel(selectedRun?.workflow_id)}</dd>
            </div>
            <div>
              <dt>投影</dt>
              <dd>{boundLabel(selectedRun?.projection_id)}</dd>
            </div>
            <div>
              <dt>提示清单</dt>
              <dd>{boundLabel(selectedRun?.prompt_manifest_id)}</dd>
            </div>
          </dl>
        </details>
      </section>
    </div>
  );
}
