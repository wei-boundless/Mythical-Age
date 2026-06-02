"use client";

import { useEffect, useMemo, useState } from "react";
import { BrainCircuit, CheckCircle2, FileArchive, GitBranch, Plus, ShieldCheck, UserRoundCheck } from "lucide-react";

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

function actionIcon(action: TaskGraphEditorAction) {
  if (action.relationId?.startsWith("memory.")) return <BrainCircuit aria-hidden="true" size={15} />;
  if (action.relationId) return <GitBranch aria-hidden="true" size={15} />;
  if (action.nodeKind === "reviewer") return <UserRoundCheck aria-hidden="true" size={15} />;
  if (action.nodeKind === "memory_repository") return <BrainCircuit aria-hidden="true" size={15} />;
  if (action.nodeKind === "artifact_repository") return <FileArchive aria-hidden="true" size={15} />;
  if (action.nodeKind === "human_gate") return <ShieldCheck aria-hidden="true" size={15} />;
  return <Plus aria-hidden="true" size={15} />;
}

function shortActionTitle(action: TaskGraphEditorAction) {
  if (action.nodeKind === "writer") return "写作";
  if (action.nodeKind === "reviewer") return "审核";
  if (action.nodeKind === "repairer") return "返修";
  if (action.nodeKind === "memory_repository") return "记忆";
  if (action.nodeKind === "artifact_repository") return "产物";
  if (action.nodeKind === "human_gate") return "人工";
  return action.title;
}

export function TaskGraphActionRail({
  canCreateRelation,
  disabled,
  linkingFromNodeId,
  onAddNode,
  onAddTaskNode,
  onApplyRelation,
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
  const relationPresets = useMemo(
    () => (semanticRelationPresets.length ? semanticRelationPresets : FALLBACK_TASK_GRAPH_SEMANTIC_RELATIONS),
    [semanticRelationPresets],
  );
  const relationActions = useMemo<TaskGraphEditorAction[]>(() => relationPresets.map((preset) => ({
    id: `edge.${preset.relation_id}`,
    title: preset.title_zh || taskGraphSemanticRelationLabel(preset.relation_id, relationPresets),
    description: preset.description || preset.payload_contract_id || preset.relation_id,
    kind: "edge",
    relationId: preset.relation_id,
  })), [relationPresets]);
  const nodeActions = useMemo(
    () => TASK_GRAPH_EDITOR_ACTION_GROUPS.flatMap((group) => group.actions).filter((action) => action.kind === "node" && action.nodeKind),
    [],
  );
  const [selectedRelationId, setSelectedRelationId] = useState<TaskGraphSemanticRelationId>(relationActions[0]?.relationId || "writing.draft_to_review");
  const [selectedTaskId, setSelectedTaskId] = useState(selectedDomainTasks[0]?.task_id || "");
  const selectedTask = selectedDomainTasks.find((task) => task.task_id === selectedTaskId) || selectedDomainTasks[0];

  useEffect(() => {
    if (!relationActions.some((action) => action.relationId === selectedRelationId)) {
      const nextRelationId = relationActions[0]?.relationId;
      if (nextRelationId) setSelectedRelationId(nextRelationId);
    }
  }, [relationActions, selectedRelationId]);

  useEffect(() => {
    if (!selectedDomainTasks.some((task) => task.task_id === selectedTaskId)) {
      setSelectedTaskId(selectedDomainTasks[0]?.task_id || "");
    }
  }, [selectedDomainTasks, selectedTaskId]);

  return (
    <aside className="task-graph-action-rail" aria-label="任务图语义动作">
      <section className="task-graph-action-rail__status">
        <span>意图</span>
        <strong>{relationHint}</strong>
      </section>

      <section className="task-graph-action-group">
        <header>
          <strong>添加节点</strong>
        </header>
        <div className="task-graph-action-grid">
          {nodeActions.map((action) => (
            <button
              disabled={disabled}
              key={action.id}
              onClick={() => action.nodeKind && onAddNode(action.nodeKind)}
              title={action.description}
              type="button"
            >
              {actionIcon(action)}
              <span>{shortActionTitle(action)}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="task-graph-action-group">
        <header>
          <strong>关系</strong>
          <span>{canCreateRelation ? "选中边可改类型，选中节点可创建连线。" : "先选择边或节点。"}</span>
        </header>
        <div className="task-graph-select-command">
          <select
            aria-label="选择语义关系"
            disabled={disabled || !canCreateRelation}
            onChange={(event) => setSelectedRelationId(event.target.value as TaskGraphSemanticRelationId)}
            value={selectedRelationId}
          >
            {relationActions.map((action) => action.relationId ? (
              <option key={action.id} value={action.relationId}>{action.title}</option>
            ) : null)}
          </select>
          <button
            disabled={disabled || !canCreateRelation || !selectedRelationId}
            onClick={() => onApplyRelation(selectedRelationId)}
            title={relationActions.find((action) => action.relationId === selectedRelationId)?.description || "应用关系"}
            type="button"
          >
            <GitBranch aria-hidden="true" size={14} />
            <span>应用</span>
          </button>
        </div>
      </section>

      <section className="task-graph-action-group">
        <header>
          <strong>具体任务</strong>
        </header>
        {selectedDomainTasks.length ? (
          <div className="task-graph-select-command">
            <select
              aria-label="选择具体任务"
              disabled={disabled}
              onChange={(event) => setSelectedTaskId(event.target.value)}
              value={selectedTask?.task_id || ""}
            >
              {selectedDomainTasks.map((task) => (
                <option key={task.task_id} value={task.task_id}>{task.task_title || task.task_id}</option>
              ))}
            </select>
            <button disabled={disabled || !selectedTask} onClick={() => selectedTask && onAddTaskNode(selectedTask)} type="button">
              <CheckCircle2 aria-hidden="true" size={14} />
              <span>挂载</span>
            </button>
          </div>
        ) : (
          <p className="task-graph-action-empty">当前环境没有可挂载任务。</p>
        )}
      </section>
    </aside>
  );
}
