"use client";

import type { ReactNode } from "react";
import { Archive, BadgeCheck, Bot, Database, FileOutput, FolderTree, GitBranch, Plus, ShieldCheck, Wrench } from "lucide-react";
import type { AgentSystemAgentRuntimeCatalog } from "@/lib/api";

import { taskGraphNodeRegistrations, type TaskGraphNodeRegistration } from "../registry/taskGraphNodeRegistry";
import {
  agentWorldRegistrationsFromCatalog,
  defaultResourceWorldRegistrations,
  type AgentWorldRegistration,
  type ResourceWorldRegistration,
} from "../registry/taskGraphWorldRegistries";

export function GraphTaskToolPanel({
  agentCatalog,
  onAddAgent,
  onAddNode,
  onAddResource,
}: {
  agentCatalog: AgentSystemAgentRuntimeCatalog | null;
  onAddAgent: (agent: AgentWorldRegistration) => void;
  onAddNode: (registration: TaskGraphNodeRegistration) => void;
  onAddResource: (resource: ResourceWorldRegistration) => void;
}) {
  const agentWorld = agentWorldRegistrationsFromCatalog(agentCatalog);
  return (
    <aside className="graph-repository-tool-panel" aria-label="图世界对象面板">
      <PanelGroup title="节点类型" detail="添加普通图节点">
        <div className="graph-repository-tool-list">
          {taskGraphNodeRegistrations.map((item) => (
            <ToolButton
              detail={item.category}
              icon={item.visual.icon}
              key={item.kind}
              label={item.displayName}
              onClick={() => onAddNode(item)}
              tone={item.visual.tone}
            />
          ))}
        </div>
      </PanelGroup>
      <PanelGroup title="Agent 库" detail="拖入后成为 agent 节点">
        <div className="graph-repository-tool-list">
          {agentWorld.map((item) => (
            <ToolButton
              detail={item.agent_id}
              icon={item.visual.icon}
              key={item.agent_id}
              label={item.displayName}
              onClick={() => onAddAgent(item)}
              tone={item.visual.tone}
            />
          ))}
        </div>
      </PanelGroup>
      <PanelGroup title="资源库" detail="显式连接后才参与运行">
        <div className="graph-repository-tool-list">
          {defaultResourceWorldRegistrations.map((item) => (
            <ToolButton
              detail={item.kind}
              icon={item.visual.icon}
              key={item.resource_id}
              label={item.displayName}
              onClick={() => onAddResource(item)}
              tone={item.visual.tone}
            />
          ))}
        </div>
      </PanelGroup>
    </aside>
  );
}

function PanelGroup({ children, detail, title }: { children: ReactNode; detail: string; title: string }) {
  return (
    <section className="graph-repository-panel-group">
      <header>
        <strong>{title}</strong>
        <span>{detail}</span>
      </header>
      {children}
    </section>
  );
}

function ToolButton({
  detail,
  icon,
  label,
  onClick,
  tone,
}: {
  detail: string;
  icon: string;
  label: string;
  onClick: () => void;
  tone: string;
}) {
  const Icon = iconForName(icon);
  return (
    <button className={`graph-repository-tool-button graph-repository-tone--${tone}`} onClick={onClick} type="button">
      <span className="graph-repository-tool-button__icon"><Icon size={15} /></span>
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <Plus size={14} />
    </button>
  );
}

function iconForName(name: string) {
  if (name === "badge-check") return BadgeCheck;
  if (name === "list-tree") return GitBranch;
  if (name === "shield-check") return ShieldCheck;
  if (name === "file-output") return FileOutput;
  if (name === "database") return Database;
  if (name === "folder-tree") return FolderTree;
  if (name === "archive") return Archive;
  if (name === "wrench") return Wrench;
  return Bot;
}

