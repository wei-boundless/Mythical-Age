"use client";

import { useEffect } from "react";
import { MessageSquare, Sparkles, Workflow } from "lucide-react";

import { Sidebar } from "@/components/layout/Sidebar";
import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
import { TaskSystemView } from "@/components/workspace/views/TaskSystemView";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import { AppProvider, useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

const WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
  "playground",
  "task-system",
  "system-framework"
]);

const MAIN_LAYERS: Array<{
  icon: typeof MessageSquare;
  label: string;
  description: string;
  view: WorkspaceView;
}> = [
  {
    icon: MessageSquare,
    label: "主会话",
    description: "对话、任务入口与普通协作",
    view: "chat",
  },
  {
    icon: Workflow,
    label: "图任务层",
    description: "任务图、任务域、编辑器与运行配置",
    view: "task-system",
  },
  {
    icon: Sparkles,
    label: "灵魂系统",
    description: "世界观、灵魂卡片、投影与共同契约",
    view: "playground",
  },
];

function Workspace() {
  const {
    activeWorkspaceView,
    setWorkspaceView,
    clearTaskGraphMonitorRun,
    evaluateBoundTaskGraphMonitor,
    setTaskGraphRunInteractionOpen,
    submitTaskGraphMonitorDecision,
    taskGraphBoundRunMonitor,
    taskGraphMonitorActionLoading,
    taskGraphMonitorBinding,
    taskGraphMonitorDecision,
    taskGraphMonitorError,
    taskGraphMonitorLoading,
    taskGraphRunInteractionOpen,
  } = useAppStore();
  const mainView = activeWorkspaceView === "task-system" || activeWorkspaceView === "playground"
    ? activeWorkspaceView
    : "chat";

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get("view");
    if (view && WORKSPACE_QUERY_VIEWS.has(view as WorkspaceView)) {
      setWorkspaceView(view as WorkspaceView);
    }
  }, [setWorkspaceView]);

  useEffect(() => {
    if (
      activeWorkspaceView !== "chat"
      && activeWorkspaceView !== "playground"
      && activeWorkspaceView !== "task-system"
      && activeWorkspaceView !== "system-framework"
    ) {
      setWorkspaceView("chat");
    }
  }, [activeWorkspaceView, setWorkspaceView]);

  if (activeWorkspaceView === "system-framework") {
    return (
      <main className="system-framework-stage min-h-screen">
        <SystemFrameworkView />
        <TaskGraphRunInteractionDock
          actionLoading={taskGraphMonitorActionLoading}
          binding={taskGraphMonitorBinding}
          decision={taskGraphMonitorDecision}
          error={taskGraphMonitorError}
          monitor={taskGraphBoundRunMonitor}
          monitorLoading={taskGraphMonitorLoading}
          onClear={clearTaskGraphMonitorRun}
          onEvaluate={() => void evaluateBoundTaskGraphMonitor()}
          onOpenChange={setTaskGraphRunInteractionOpen}
          onSubmitDecision={(decision, controlAction, resumePayload) => void submitTaskGraphMonitorDecision(decision, controlAction, resumePayload)}
          open={taskGraphRunInteractionOpen}
        />
      </main>
    );
  }

  return (
    <main className="practical-workspace">
      <Sidebar />

      <section className="practical-main" aria-label="主工作区">
        <header className="practical-mainbar">
          <div className="practical-mainbar__title">
            <span>LangChain Agent</span>
            <strong>
              {mainView === "chat" ? "主会话页面" : mainView === "task-system" ? "图任务层" : "灵魂系统"}
            </strong>
          </div>
          <nav className="practical-layer-tabs" aria-label="主工作层">
            {MAIN_LAYERS.map((item) => {
              const Icon = item.icon;
              const active = mainView === item.view;
              return (
                <button
                  aria-pressed={active}
                  className={active ? "practical-layer-tab practical-layer-tab--active" : "practical-layer-tab"}
                  key={item.view}
                  onClick={() => setWorkspaceView(item.view)}
                  type="button"
                >
                  <Icon size={16} />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </header>

        <section className="practical-layer-context" aria-label="当前层说明">
          {MAIN_LAYERS.map((item) => {
            if (item.view !== mainView) return null;
            const Icon = item.icon;
            return (
              <div className="practical-layer-card" key={item.view}>
                <Icon size={17} />
                <div>
                  <strong>{item.label}</strong>
                  <span>{item.description}</span>
                </div>
              </div>
            );
          })}
        </section>

        <section className="practical-content">
          {mainView === "chat" ? <ChatPanel /> : mainView === "task-system" ? <TaskSystemView /> : <PlaygroundView />}
        </section>
      </section>

      <TaskMonitorDock />

      <TaskGraphRunInteractionDock
        actionLoading={taskGraphMonitorActionLoading}
        binding={taskGraphMonitorBinding}
        decision={taskGraphMonitorDecision}
        error={taskGraphMonitorError}
        monitor={taskGraphBoundRunMonitor}
        monitorLoading={taskGraphMonitorLoading}
        onClear={clearTaskGraphMonitorRun}
        onEvaluate={() => void evaluateBoundTaskGraphMonitor()}
        onOpenChange={setTaskGraphRunInteractionOpen}
        onSubmitDecision={(decision, controlAction, resumePayload) => void submitTaskGraphMonitorDecision(decision, controlAction, resumePayload)}
        open={taskGraphRunInteractionOpen}
      />
    </main>
  );
}

export default function Page() {
  return (
    <AppProvider>
      <Workspace />
    </AppProvider>
  );
}
