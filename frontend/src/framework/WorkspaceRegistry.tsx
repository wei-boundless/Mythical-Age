"use client";

import { lazy, Suspense, type ReactNode } from "react";

import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import { CodeEnvironmentView } from "@/components/workspace/views/CodeEnvironmentView";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import type { WorkspaceView } from "@/lib/store/types";

import { SystemPageShell } from "./SystemPageShell";

const CapabilitySystemView = lazy(() => import("@/components/workspace/views/CapabilitySystemView").then((module) => ({ default: module.CapabilitySystemView })));
const GraphTaskSystemView = lazy(() => import("@/components/workspace/views/GraphTaskSystemView").then((module) => ({ default: module.GraphTaskSystemView })));
const HealthSystemView = lazy(() => import("@/components/workspace/views/HealthSystemView").then((module) => ({ default: module.HealthSystemView })));
const MemoryView = lazy(() => import("@/components/workspace/views/MemoryView").then((module) => ({ default: module.MemoryView })));
const OrchestrationView = lazy(() => import("@/components/workspace/views/OrchestrationView").then((module) => ({ default: module.OrchestrationView })));
const SystemConfigView = lazy(() => import("@/components/workspace/views/SystemConfigView").then((module) => ({ default: module.SystemConfigView })));
const TaskSystemView = lazy(() => import("@/components/workspace/views/TaskSystemView").then((module) => ({ default: module.TaskSystemView })));

type WorkspaceRegistryContext = {
  centerTaskEnvironmentId: string;
  view: WorkspaceView;
};

type WorkspaceViewDefinition = {
  label: string;
  render: (context: WorkspaceRegistryContext) => ReactNode;
  view: WorkspaceView;
};

function LazyView({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div className="boundary-empty boundary-empty--large">正在加载工作台...</div>}>
      {children}
    </Suspense>
  );
}

function renderCenterWorkspace({ centerTaskEnvironmentId, view }: WorkspaceRegistryContext) {
  return (
    <SystemPageShell label={view === "code-environment" ? "代码环境" : "主会话"} view={view}>
      <WorkbenchShell hideMainToolbar>
        <section className="workbench-view-host workbench-view-host--chat" aria-label="主会话">
          <CenterWorkspaceView taskEnvironmentId={centerTaskEnvironmentId} />
          {view === "code-environment" ? <CodeEnvironmentView /> : null}
        </section>
      </WorkbenchShell>
    </SystemPageShell>
  );
}

export const WORKSPACE_REGISTRY: Record<WorkspaceView, WorkspaceViewDefinition> = {
  chat: {
    label: "主会话",
    render: renderCenterWorkspace,
    view: "chat",
  },
  "code-environment": {
    label: "代码环境",
    render: renderCenterWorkspace,
    view: "code-environment",
  },
  creative: {
    label: "图任务",
    render: () => (
      <SystemPageShell label="图任务" view="creative">
        <LazyView><GraphTaskSystemView /></LazyView>
      </SystemPageShell>
    ),
    view: "creative",
  },
  "task-system": {
    label: "任务系统",
    render: () => (
      <SystemPageShell label="任务系统" view="task-system">
        <LazyView><TaskSystemView /></LazyView>
      </SystemPageShell>
    ),
    view: "task-system",
  },
  orchestration: {
    label: "Agent 管理系统",
    render: () => (
      <SystemPageShell label="Agent 管理系统" view="orchestration">
        <LazyView><OrchestrationView /></LazyView>
      </SystemPageShell>
    ),
    view: "orchestration",
  },
  "health-system": {
    label: "健康系统",
    render: () => (
      <SystemPageShell label="健康系统" view="health-system">
        <LazyView><HealthSystemView /></LazyView>
      </SystemPageShell>
    ),
    view: "health-system",
  },
  memory: {
    label: "长期记忆",
    render: () => (
      <SystemPageShell label="长期记忆" view="memory">
        <LazyView><MemoryView /></LazyView>
      </SystemPageShell>
    ),
    view: "memory",
  },
  "capability-system": {
    label: "能力系统",
    render: () => (
      <SystemPageShell label="能力系统" view="capability-system">
        <LazyView><CapabilitySystemView /></LazyView>
      </SystemPageShell>
    ),
    view: "capability-system",
  },
  "system-config": {
    label: "配置",
    render: () => (
      <SystemPageShell label="配置" view="system-config">
        <LazyView><SystemConfigView /></LazyView>
      </SystemPageShell>
    ),
    view: "system-config",
  },
};

export function resolveWorkspaceView(view: WorkspaceView) {
  return WORKSPACE_REGISTRY[view] ?? WORKSPACE_REGISTRY.chat;
}

export function WorkspaceRegistry({
  centerTaskEnvironmentId,
  view,
}: {
  centerTaskEnvironmentId: string;
  view: WorkspaceView;
}) {
  const definition = resolveWorkspaceView(view);
  return <>{definition.render({ centerTaskEnvironmentId, view: definition.view })}</>;
}
