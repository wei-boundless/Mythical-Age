"use client";

import { Copy, GitFork, PlayCircle, RotateCcw, Save, Sparkles } from "lucide-react";

export function GraphTaskEditorToolbar({
  graphTitle,
  saving,
  onAutoLayout,
  onCreateInstance,
  onDuplicate,
  onPublish,
  onSave,
  onSaveTemplate,
}: {
  graphTitle: string;
  saving: string;
  onAutoLayout: () => void;
  onCreateInstance: () => void;
  onDuplicate: () => void;
  onPublish: () => void;
  onSave: () => void;
  onSaveTemplate: () => void;
}) {
  return (
    <header className="graph-repository-editor-toolbar">
      <div>
        <span>任务图编辑器</span>
        <strong>{graphTitle || "未命名图草稿"}</strong>
      </div>
      <nav aria-label="图编辑器操作">
        <span className="graph-editor-action-group" aria-label="画布整理">
          <button disabled={Boolean(saving)} onClick={onAutoLayout} title="自动整理当前画布布局" type="button">
            <RotateCcw size={15} />
            <span>布局</span>
          </button>
          <button disabled={Boolean(saving)} onClick={onDuplicate} title="从当前图生产副本" type="button">
            <Copy size={15} />
            <span>副本</span>
          </button>
          <button disabled={Boolean(saving)} onClick={onSaveTemplate} title="把当前图另存为用户模板" type="button">
            <Sparkles size={15} />
            <span>模板</span>
          </button>
        </span>
        <span className="graph-editor-action-group graph-editor-action-group--commit" aria-label="保存发布">
          <button disabled={Boolean(saving)} onClick={onSave} title="保存图定义草稿" type="button">
            <Save size={15} />
            <span>{saving === "save" ? "保存中" : "保存"}</span>
          </button>
          <button className="graph-editor-action--primary" disabled={Boolean(saving)} onClick={onPublish} title="发布为可运行图" type="button">
            <GitFork size={15} />
            <span>{saving === "publish" ? "发布中" : "发布"}</span>
          </button>
        </span>
        <span className="graph-editor-action-group graph-editor-action-group--run" aria-label="封装运行">
          <button className="graph-editor-action--run" disabled={Boolean(saving)} onClick={onCreateInstance} title="封装为可运行项目" type="button">
            <PlayCircle size={15} />
            <span>封装</span>
          </button>
        </span>
      </nav>
    </header>
  );
}
