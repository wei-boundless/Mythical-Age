"use client";

import { FileText, Layers3, Lock, SplitSquareHorizontal } from "lucide-react";

import { TemplateGallery } from "../TemplateGallery";
import type { GraphTemplateRecord } from "../templates/graphTemplateTypes";

export function TemplateLibraryContext({
  onCreateDraft,
  onDeleteTemplate,
  onDuplicateTemplate,
  templates,
}: {
  templates: GraphTemplateRecord[];
  onCreateDraft: (template: GraphTemplateRecord) => void;
  onDuplicateTemplate: (template: GraphTemplateRecord) => void;
  onDeleteTemplate: (template: GraphTemplateRecord) => void;
}) {
  const featured = templates[0] ?? null;
  const builtinCount = templates.filter((template) => template.source === "builtin").length;
  const userCount = templates.length - builtinCount;
  return (
    <section className="graph-os-library-context" aria-label="模板库上下文">
      <aside className="graph-os-context-rail">
        <header>
          <span>Template Context</span>
          <strong>模板是配置种子</strong>
        </header>
        <div className="graph-os-fact-list">
          <p><FileText size={14} /><span>系统模板</span><strong>{builtinCount}</strong></p>
          <p><Layers3 size={14} /><span>用户模板</span><strong>{userCount}</strong></p>
          <p><SplitSquareHorizontal size={14} /><span>模板行为</span><strong>创建草稿</strong></p>
        </div>
        <p className="graph-os-context-note">模板不能直接运行。选择模板后会生成一份可编辑图草稿，再进入编辑器。</p>
      </aside>
      <div className="graph-os-context-main">
        <TemplateGallery
          onCreateDraft={onCreateDraft}
          onDeleteTemplate={onDeleteTemplate}
          onDuplicateTemplate={onDuplicateTemplate}
          templates={templates}
        />
      </div>
      <aside className="graph-os-context-inspector">
        <header>
          <span>Template Preview</span>
          <strong>{featured?.title || "暂无模板"}</strong>
        </header>
        {featured ? (
          <div className="graph-os-inspector-stack">
            <p><span>来源</span><strong>{featured.source}</strong></p>
            <p><span>类别</span><strong>{featured.category}</strong></p>
            <p><span>节点</span><strong>{featured.graph_seed.nodes.length}</strong></p>
            <p><span>边</span><strong>{featured.graph_seed.edges.length}</strong></p>
            <p><span>文件角色</span><strong>{featured.file_space_template?.file_roles.length ?? 0}</strong></p>
            <p><span>只读</span><strong>{featured.readonly ? "是" : "否"}</strong></p>
          </div>
        ) : (
          <div className="graph-repository-compact-empty">还没有可预览的模板。</div>
        )}
        <div className="graph-os-policy-card">
          <Lock size={15} />
          <span>模板层只提供结构种子，不拥有实例文件，也不直接启动运行。</span>
        </div>
      </aside>
    </section>
  );
}
