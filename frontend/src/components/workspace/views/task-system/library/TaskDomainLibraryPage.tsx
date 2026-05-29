"use client";

import { Loader2, Pencil, Save, Trash2 } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import type { ConversationEntryPolicy, TaskDomainRecord } from "@/lib/api";

import { TaskDomainManagementPage } from "../TaskSystemPages";
import {
  TaskSystemField as Field,
  TaskSystemSelectField as SelectField,
  TaskSystemToolbarButton as ToolbarButton,
} from "../TaskSystemWorkbenchUi";

type TaskDomainLibraryDomain = {
  domain_id: string;
  title: string;
  tasks: unknown[];
};

function SystemFields({ children }: { children: ReactNode }) {
  return (
    <details className="boundary-system-fields">
      <summary>系统字段</summary>
      <div className="boundary-form">{children}</div>
    </details>
  );
}

function ReadinessCard({ label, ready, value }: { label: string; ready: boolean; value: string }) {
  return (
    <article className={ready ? "boundary-readiness boundary-readiness--ready" : "boundary-readiness"}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{ready ? "已配置" : "待配置"}</small>
    </article>
  );
}

export function TaskDomainLibraryPage({
  contractCount,
  domainDraft,
  editingDomainName,
  entryDraft,
  graphCount,
  loading,
  onDeleteDomain,
  onSaveDomain,
  onSaveEntry,
  onSelectLayer,
  onSetDomainDraft,
  onSetEditingDomainName,
  onSetEntryDraft,
  saving,
  selectedDomain,
  workflowOptions,
}: {
  contractCount: number;
  domainDraft: TaskDomainRecord;
  editingDomainName: boolean;
  entryDraft: ConversationEntryPolicy;
  graphCount: number;
  loading: boolean;
  onDeleteDomain: () => void;
  onSaveDomain: () => void;
  onSaveEntry: () => void;
  onSelectLayer: (layer: "tasks" | "graphs" | "contracts") => void;
  onSetDomainDraft: Dispatch<SetStateAction<TaskDomainRecord>>;
  onSetEditingDomainName: (editing: boolean) => void;
  onSetEntryDraft: Dispatch<SetStateAction<ConversationEntryPolicy>>;
  saving: string;
  selectedDomain: TaskDomainLibraryDomain | null;
  workflowOptions: string[];
}) {
  return (
    <TaskDomainManagementPage>
      <main className="task-management-workbench task-management-workbench--full">
        <header className="task-management-titlebar">
          <div>
            <span>任务域库</span>
            {editingDomainName ? (
              <input
                autoFocus
                className="boundary-title-input"
                onChange={(event) => onSetDomainDraft((value) => ({ ...value, title: event.target.value }))}
                onKeyDown={(event) => {
                  if (event.key === "Enter") onSaveDomain();
                  if (event.key === "Escape") onSetEditingDomainName(false);
                }}
                value={domainDraft.title}
              />
            ) : (
              <h3>{selectedDomain?.title || "任务域"}</h3>
            )}
            <p>任务域只负责分类、入口策略和域级边界，不编辑图模块和运行产物。</p>
          </div>
          <div className="boundary-actions">
            <ToolbarButton onClick={() => onSetEditingDomainName(true)}>
              <Pencil size={15} />改名
            </ToolbarButton>
            <ToolbarButton disabled={saving === "domain-delete" || !selectedDomain} onClick={onDeleteDomain}>
              <Trash2 size={15} />删除域
            </ToolbarButton>
            <ToolbarButton disabled={saving === "domain"} onClick={onSaveDomain} variant="primary">
              <Save size={15} />保存域
            </ToolbarButton>
          </div>
        </header>

        <section className="boundary-card">
          <header>
            <strong>任务域设置</strong>
            <span>{selectedDomain?.domain_id || domainDraft.domain_id}</span>
          </header>
          <div className="boundary-form">
            <label className="boundary-check">
              <input
                checked={domainDraft.enabled}
                onChange={(event) => onSetDomainDraft((value) => ({ ...value, enabled: event.target.checked }))}
                type="checkbox"
              />
              启用任务域
            </label>
            <Field label="任务域描述" wide>
              <textarea
                onChange={(event) => onSetDomainDraft((value) => ({ ...value, description: event.target.value }))}
                value={domainDraft.description}
              />
            </Field>
            <SystemFields>
              <Field label="任务域 ID">
                <input
                  onChange={(event) => onSetDomainDraft((value) => ({ ...value, domain_id: event.target.value }))}
                  value={domainDraft.domain_id}
                />
              </Field>
              <Field label="入口策略 ID">
                <input
                  onChange={(event) => onSetEntryDraft((value) => ({ ...value, profile_id: event.target.value }))}
                  value={entryDraft.profile_id}
                />
              </Field>
              <SelectField
                label="默认 Workflow"
                onChange={(value) => onSetEntryDraft((current) => ({ ...current, default_workflow_id: value }))}
                options={workflowOptions}
                value={entryDraft.default_workflow_id}
              />
            </SystemFields>
          </div>
          <div className="boundary-actions">
            <ToolbarButton disabled={saving === "entry"} onClick={onSaveEntry}>
              <Save size={15} />保存入口策略
            </ToolbarButton>
            <div className="task-domain-quick-jumps">
              <ToolbarButton onClick={() => onSelectLayer("tasks")}>任务定义库</ToolbarButton>
              <ToolbarButton onClick={() => onSelectLayer("graphs")}>任务图库</ToolbarButton>
              <ToolbarButton onClick={() => onSelectLayer("contracts")}>契约库</ToolbarButton>
            </div>
          </div>
        </section>

        {loading ? <div className="boundary-empty"><Loader2 className="spin" size={16} />加载中</div> : null}
        <div className="task-management-status-row">
          <ReadinessCard label="域内任务" ready={Boolean(selectedDomain?.tasks.length)} value={`${selectedDomain?.tasks.length ?? 0}`} />
          <ReadinessCard label="任务图" ready={Boolean(graphCount)} value={`${graphCount}`} />
          <ReadinessCard label="契约" ready={Boolean(contractCount)} value={`${contractCount}`} />
        </div>
      </main>
    </TaskDomainManagementPage>
  );
}
