"use client";

import { CheckCircle2, Sparkles } from "lucide-react";
import { useState } from "react";

import { TASK_GRAPH_TEMPLATE_CARDS, type TaskGraphTemplateBuildInput, type TaskGraphTemplateId } from "./taskGraphTemplates";

export type TaskGraphSetupWizardOptions = Pick<
  TaskGraphTemplateBuildInput,
  "task_intent" | "input_material_type" | "artifact_type" | "review_strength" | "loop_count" | "require_human_confirmation" | "agent_bindings"
>;

export function TaskGraphSetupWizard({
  domainTitle,
  taskCount,
  onApplyTemplate,
}: {
  domainTitle: string;
  taskCount: number;
  onApplyTemplate: (templateId: TaskGraphTemplateId, options: TaskGraphSetupWizardOptions) => void;
}) {
  const [taskIntent, setTaskIntent] = useState("");
  const [inputMaterialType, setInputMaterialType] = useState<TaskGraphSetupWizardOptions["input_material_type"]>("general");
  const [artifactType, setArtifactType] = useState<TaskGraphSetupWizardOptions["artifact_type"]>("markdown_report");
  const [reviewStrength, setReviewStrength] = useState<TaskGraphSetupWizardOptions["review_strength"]>("standard");
  const [loopCount, setLoopCount] = useState(3);
  const [requireHumanConfirmation, setRequireHumanConfirmation] = useState(false);
  const [pdfAgentId, setPdfAgentId] = useState("agent:pdf_reader");
  const [tableAgentId, setTableAgentId] = useState("agent:table_analyst");
  const [ragAgentId, setRagAgentId] = useState("agent:rag_analyst");

  const buildOptions = (): TaskGraphSetupWizardOptions => ({
    task_intent: taskIntent,
    input_material_type: inputMaterialType,
    artifact_type: artifactType,
    review_strength: reviewStrength,
    loop_count: loopCount,
    require_human_confirmation: requireHumanConfirmation,
    agent_bindings: {
      pdf_analyst: pdfAgentId,
      table_analyst: tableAgentId,
      rag: ragAgentId,
    },
  });

  return (
    <section className="task-graph-studio-page task-graph-setup-wizard">
      <header className="task-graph-studio-page__head">
        <span>TaskGraph Studio</span>
        <strong>从任务意图生成协同草稿</strong>
        <small>{domainTitle} · {taskCount} 个可绑定任务</small>
      </header>

      <section className="task-graph-setup-wizard__intro">
        <div>
          <Sparkles size={20} />
          <strong>选择一个持续任务模板</strong>
          <span>模板会生成真实节点、通信边、阶段、入口出口和职责 Prompt，不会用空节点绕过预检。</span>
        </div>
        <div>
          <CheckCircle2 size={20} />
          <strong>生成后进入拓扑编排</strong>
          <span>你仍然可以继续调整 Agent 编组、职责、时序、记忆、契约和发布状态。</span>
        </div>
      </section>

      <section className="boundary-card">
        <header><strong>模板参数</strong><span>会写入节点职责、阶段策略和 Agent 绑定来源</span></header>
        <div className="boundary-form">
          <label>
            <span>任务意图</span>
            <textarea value={taskIntent} onChange={(event) => setTaskIntent(event.target.value)} placeholder="例如：分析上传资料，产出可追溯的决策简报。" />
          </label>
          <label>
            <span>输入资料类型</span>
            <select value={inputMaterialType} onChange={(event) => setInputMaterialType(event.target.value as TaskGraphSetupWizardOptions["input_material_type"])}>
              <option value="general">通用资料</option>
              <option value="rag_corpus">RAG 知识库</option>
              <option value="pdf">PDF</option>
              <option value="table">表格</option>
              <option value="pdf_and_table">PDF + 表格</option>
            </select>
          </label>
          <label>
            <span>主要产物</span>
            <select value={artifactType} onChange={(event) => setArtifactType(event.target.value as TaskGraphSetupWizardOptions["artifact_type"])}>
              <option value="markdown_report">Markdown 报告</option>
              <option value="structured_json">结构化 JSON</option>
              <option value="table_dataset">表格数据集</option>
              <option value="decision_brief">决策简报</option>
            </select>
          </label>
          <label>
            <span>审核强度</span>
            <select value={reviewStrength} onChange={(event) => setReviewStrength(event.target.value as TaskGraphSetupWizardOptions["review_strength"])}>
              <option value="light">轻量</option>
              <option value="standard">标准</option>
              <option value="strict">严格</option>
            </select>
          </label>
          <label>
            <span>循环次数</span>
            <input min={0} type="number" value={loopCount} onChange={(event) => setLoopCount(Number(event.target.value || 0))} />
          </label>
          <label className="boundary-check">
            <input type="checkbox" checked={requireHumanConfirmation} onChange={(event) => setRequireHumanConfirmation(event.target.checked)} />
            关键阶段需要人工确认
          </label>
        </div>
        <div className="boundary-form">
          <label><span>PDF Agent</span><input value={pdfAgentId} onChange={(event) => setPdfAgentId(event.target.value)} /></label>
          <label><span>表格 Agent</span><input value={tableAgentId} onChange={(event) => setTableAgentId(event.target.value)} /></label>
          <label><span>RAG Agent</span><input value={ragAgentId} onChange={(event) => setRagAgentId(event.target.value)} /></label>
        </div>
      </section>

      <section className="task-graph-template-grid" aria-label="任务图模板">
        {TASK_GRAPH_TEMPLATE_CARDS.map((template) => (
          <button
            className="task-graph-template-card"
            key={template.template_id}
            onClick={() => onApplyTemplate(template.template_id, buildOptions())}
            type="button"
          >
            <strong>{template.title}</strong>
            <span>{template.intent}</span>
            <small>{template.best_for}</small>
            <div>
              {template.participant_roles.map((role) => <em key={role}>{role}</em>)}
            </div>
          </button>
        ))}
      </section>
    </section>
  );
}
