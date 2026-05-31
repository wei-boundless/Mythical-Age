"use client";

import { BrainCircuit, CheckCircle2, FileArchive, GitBranch, Plus, Route, ShieldCheck, UserRoundCheck } from "lucide-react";

import type { SpecificTaskRecord } from "@/lib/api";

import {
  TASK_GRAPH_EDITOR_ACTION_GROUPS,
  type TaskGraphEditorAction,
  type TaskGraphSemanticNodeKind,
} from "./TaskGraphEditorActions";
import {
  FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS,
  taskGraphSemanticRelationLabel,
  type TaskGraphSemanticRelationId,
  type TaskGraphSemanticRelationPreset,
} from "./taskGraphSemanticRelations";
import type { TaskGraphTemplateId } from "./taskGraphTemplates";

function actionIcon(action: TaskGraphEditorAction) {
  if (action.kind === "template") return <Route aria-hidden="true" size={15} />;
  if (action.relationId?.startsWith("memory.")) return <BrainCircuit aria-hidden="true" size={15} />;
  if (action.relationId) return <GitBranch aria-hidden="true" size={15} />;
  if (action.nodeKind === "reviewer") return <UserRoundCheck aria-hidden="true" size={15} />;
  if (action.nodeKind === "memory_repository") return <BrainCircuit aria-hidden="true" size={15} />;
  if (action.nodeKind === "artifact_repository") return <FileArchive aria-hidden="true" size={15} />;
  if (action.nodeKind === "human_gate") return <ShieldCheck aria-hidden="true" size={15} />;
  return <Plus aria-hidden="true" size={15} />;
}

export function TaskGraphActionRail({
  canCreateRelation,
  disabled,
  linkingFromNodeId,
  onAddNode,
  onAddTaskNode,
  onApplyRelation,
  onApplyTemplate,
  semanticRelationPresets,
  selectedDomainTasks,
  selectedNodeId,
}: {
  canCreateRelation: boolean;
  disabled: boolean;
  linkingFromNodeId: string;
  onAddNode: (kind: TaskGraphSemanticNodeKind) => void;
  onAddTaskNode: (task: SpecificTaskRecord) => void;
  onApplyRelation: (relationId: TaskGraphSemanticRelationId) => void;
  onApplyTemplate: (templateId: TaskGraphTemplateId) => void;
  semanticRelationPresets: TaskGraphSemanticRelationPreset[];
  selectedDomainTasks: SpecificTaskRecord[];
  selectedNodeId: string;
}) {
  const relationHint = linkingFromNodeId
    ? selectedNodeId && selectedNodeId !== linkingFromNodeId
      ? `${linkingFromNodeId} -> ${selectedNodeId}`
      : `起点 ${linkingFromNodeId}，再选择终点`
      : selectedNodeId
      ? `当前节点 ${selectedNodeId}`
      : "先选择节点或边";
  const relationPresets = semanticRelationPresets.length ? semanticRelationPresets : FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS;
  const relationActions: TaskGraphEditorAction[] = relationPresets.map((preset) => ({
    id: `edge.${preset.relation_id}`,
    title: preset.title_zh || taskGraphSemanticRelationLabel(preset.relation_id, relationPresets),
    description: preset.description || preset.payload_contract_id || preset.relation_id,
    kind: "edge",
    relationId: preset.relation_id,
  }));
  const actionGroups = TASK_GRAPH_EDITOR_ACTION_GROUPS
    .map((group) => {
      if (group.id === "relations") {
        return {
          ...group,
          description: "来自后端边协议目录，选择关系后由编译层解析契约。",
          actions: relationActions,
        };
      }
      if (group.id === "resources") {
        return {
          ...group,
          actions: group.actions.filter((action) => action.kind !== "edge"),
        };
      }
      return group;
    })
    .filter((group) => group.actions.length > 0);

  return (
    <aside className="task-graph-action-rail" aria-label="任务图语义动作">
      <section className="task-graph-action-rail__status">
        <span>当前意图</span>
        <strong>{relationHint}</strong>
      </section>

      {actionGroups.map((group) => (
        <section className="task-graph-action-group" key={group.id}>
          <header>
            <strong>{group.title}</strong>
            <span>{group.description}</span>
          </header>
          <div className="task-graph-action-list">
            {group.actions.map((action) => {
              const relationDisabled = action.kind === "edge" && !canCreateRelation;
              return (
                <button
                  disabled={disabled || relationDisabled}
                  key={action.id}
                  onClick={() => {
                    if (action.kind === "node" && action.nodeKind) onAddNode(action.nodeKind);
                    if (action.kind === "edge" && action.relationId) onApplyRelation(action.relationId);
                    if (action.kind === "template" && action.templateId) onApplyTemplate(action.templateId);
                  }}
                  title={action.description}
                  type="button"
                >
                  {actionIcon(action)}
                  <span>
                    <strong>{action.title}</strong>
                    <small>{action.description}</small>
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      ))}

      <section className="task-graph-action-group">
        <header>
          <strong>任务定义</strong>
          <span>把任务环境里的具体任务挂成节点。</span>
        </header>
        <div className="task-graph-domain-task-actions">
          {selectedDomainTasks.length ? selectedDomainTasks.map((task) => (
            <button disabled={disabled} key={task.task_id} onClick={() => onAddTaskNode(task)} type="button">
              <CheckCircle2 aria-hidden="true" size={14} />
              <span>
                <strong>{task.task_title || task.task_id}</strong>
                <small>{task.task_id}</small>
              </span>
            </button>
          )) : (
            <p>当前任务环境没有可挂载的具体任务。</p>
          )}
        </div>
      </section>
    </aside>
  );
}
