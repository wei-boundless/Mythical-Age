"use client";

import { Copy, FileText, Lock, Trash2 } from "lucide-react";

import type { GraphTemplateRecord } from "./templates/graphTemplateTypes";

export function TemplateGallery({
  onCreateDraft,
  onDeleteTemplate,
  onDuplicateTemplate,
  showHeader = true,
  templates,
}: {
  templates: GraphTemplateRecord[];
  showHeader?: boolean;
  onCreateDraft: (template: GraphTemplateRecord) => void;
  onDuplicateTemplate: (template: GraphTemplateRecord) => void;
  onDeleteTemplate: (template: GraphTemplateRecord) => void;
}) {
  const systemTemplates = templates.filter((template) => template.source === "builtin");
  const userTemplates = templates.filter((template) => template.source !== "builtin");
  return (
    <section className="graph-repository-section" aria-label="图模板库">
      {showHeader ? <SectionHead title="模板库" detail="模板是配置种子；创建后会生成可自由修改的图草稿。" /> : null}
      <div className="graph-repository-template-groups">
        <TemplateGroup
          empty="还没有系统模板。"
          onCreateDraft={onCreateDraft}
          onDeleteTemplate={onDeleteTemplate}
          onDuplicateTemplate={onDuplicateTemplate}
          templates={systemTemplates}
          title="系统内置模板"
        />
        <TemplateGroup
          empty="还没有用户模板。可以在编辑器里把当前图另存为模板。"
          onCreateDraft={onCreateDraft}
          onDeleteTemplate={onDeleteTemplate}
          onDuplicateTemplate={onDuplicateTemplate}
          templates={userTemplates}
          title="用户模板"
        />
      </div>
    </section>
  );
}

function TemplateGroup({
  empty,
  onCreateDraft,
  onDeleteTemplate,
  onDuplicateTemplate,
  templates,
  title,
}: {
  title: string;
  empty: string;
  templates: GraphTemplateRecord[];
  onCreateDraft: (template: GraphTemplateRecord) => void;
  onDuplicateTemplate: (template: GraphTemplateRecord) => void;
  onDeleteTemplate: (template: GraphTemplateRecord) => void;
}) {
  return (
    <section className="graph-repository-template-group">
      <header>
        <strong>{title}</strong>
        <span>{templates.length} 个模板</span>
      </header>
      {templates.length ? (
        <div className="graph-repository-template-grid">
          {templates.map((template) => (
            <article className="graph-repository-template-card" key={template.template_id}>
              <header>
                <FileText size={16} />
                <div>
                  <span>{template.category}</span>
                  <strong>{template.title}</strong>
                </div>
                {template.readonly ? <Lock size={14} /> : null}
              </header>
              <p>{template.description || "可复制到编辑器中自由修改。"}</p>
              <div className="graph-repository-template-card__facts">
                <span>{template.graph_seed.nodes.length} 节点</span>
                <span>{template.graph_seed.edges.length} 边</span>
                <span>{template.file_space_template?.file_roles.length ?? 0} 文件角色</span>
              </div>
              <footer>
                <button onClick={() => onCreateDraft(template)} type="button">创建图草稿</button>
                <button onClick={() => onDuplicateTemplate(template)} title="复制为用户模板" type="button">
                  <Copy size={14} />
                </button>
                {!template.readonly ? (
                  <button onClick={() => onDeleteTemplate(template)} title="删除用户模板" type="button">
                    <Trash2 size={14} />
                  </button>
                ) : null}
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <div className="graph-repository-empty">{empty}</div>
      )}
    </section>
  );
}

function SectionHead({ detail, title }: { detail: string; title: string }) {
  return (
    <header className="graph-repository-section-head">
      <div>
        <span>Task Graph System</span>
        <strong>{title}</strong>
      </div>
      <p>{detail}</p>
    </header>
  );
}
