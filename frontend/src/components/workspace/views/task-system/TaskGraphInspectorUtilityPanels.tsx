import { Cable, FileWarning, GitBranch } from "lucide-react";

import type { ComposableUnitSpec } from "@/lib/api";

import {
  TaskGraphInspectorSection,
  TaskGraphInspectorSummary,
} from "./TaskGraphInspectorPrimitives";
import type { TaskGraphComposableGraphOverlay } from "./taskGraphModuleComposition";
import type { TaskGraphComposableSubject } from "./taskGraphComposableEditorTypes";

export function TaskGraphUnmappedUnitPanel({ selected }: { selected: ComposableUnitSpec }) {
  return (
    <TaskGraphInspectorSection icon={<GitBranch aria-hidden="true" size={15} />} title="Unit" aside={selected.source_kind || "standard view"}>
      <TaskGraphInspectorSummary
        caption={selected.unit_id}
        overline={selected.unit_type}
        title={selected.title || selected.unit_id}
      />
      <div className="task-graph-note">
        <strong>该 Unit 未映射到可编辑节点</strong>
        <span>资源、工具或覆盖层 Unit 的完整表单将在 Interface / Port 覆盖层阶段开放；当前先通过原始节点或图节点编辑入口配置。</span>
      </div>
    </TaskGraphInspectorSection>
  );
}

export function TaskGraphInterfacePlaceholderPanel({ selectedSubject }: { selectedSubject: TaskGraphComposableSubject }) {
  if (selectedSubject.kind !== "interface" && selectedSubject.kind !== "port") return null;
  return (
    <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="接口端口" aside="只读预览">
      <div className="task-graph-note">
        <strong>接口覆盖层将在下一阶段开放</strong>
        <span>当前先通过节点契约、图节点交接契约和显式端口边维护接口语义。</span>
      </div>
    </TaskGraphInspectorSection>
  );
}

export function TaskGraphIssueInspector({ selectedSubject }: { selectedSubject: TaskGraphComposableSubject }) {
  if (selectedSubject.kind !== "issue") return null;
  return (
    <TaskGraphInspectorSection icon={<FileWarning aria-hidden="true" size={15} />} title="诊断问题" aside={selectedSubject.issue.severity}>
      <TaskGraphInspectorSummary
        caption={selectedSubject.issue.source}
        overline={`${selectedSubject.issue.scope}${selectedSubject.issue.target_id ? `:${selectedSubject.issue.target_id}` : ""}`}
        title={selectedSubject.issue.title}
      />
      <div className="task-graph-note task-graph-note--danger">
        <strong>处理说明</strong>
        <span>{selectedSubject.issue.detail}</span>
      </div>
    </TaskGraphInspectorSection>
  );
}

export function TaskGraphOverlayStatusPanel({
  onNormalizeOverlay,
  overlay,
}: {
  onNormalizeOverlay: () => void;
  overlay: TaskGraphComposableGraphOverlay;
}) {
  return (
    <TaskGraphInspectorSection icon={<Cable aria-hidden="true" size={15} />} title="覆盖层状态" aside="metadata.composable_graph">
      <div className="task-graph-composer-kv">
        <p><span>Unit 覆盖</span><strong>{overlay.units.length}</strong></p>
        <p><span>Interface 覆盖</span><strong>{overlay.interfaces.length}</strong></p>
        <p><span>PortEdge 覆盖</span><strong>{overlay.port_edges.length}</strong></p>
        <p><span>Nested 覆盖</span><strong>{overlay.nested_runtime.length}</strong></p>
      </div>
      {overlay.units.length || overlay.interfaces.length || overlay.nested_runtime.length ? (
        <button className="task-graph-composer-subtle-action" onClick={onNormalizeOverlay} type="button">
          重新规范化覆盖层
        </button>
      ) : null}
    </TaskGraphInspectorSection>
  );
}
