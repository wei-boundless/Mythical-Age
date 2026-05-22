"use client";

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { AppProvider, useAppStore } from "@/lib/store";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { CapabilitySystemView } from "@/components/workspace/views/CapabilitySystemView";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
import { TaskSystemView } from "@/components/workspace/views/TaskSystemView";
import { TaskMonitorDock } from "@/components/layout/TaskMonitorDock";
import { Sidebar } from "@/components/layout/Sidebar";
import { TaskGraphRunInteractionDock } from "@/components/workspace/views/task-system/TaskGraphRunInteractionDock";
import { isChatVisualMode, isSoulChatVisualMode, normalizeChatVisualMode, type ChatVisualMode } from "@/lib/chatVisualModes";
import type { WorkspaceView } from "@/lib/store/types";

const WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
  "playground",
  "task-system",
  "capability-system",
  "system-framework",
]);

function isTaskLayerView(view: WorkspaceView) {
  return view === "task-system" || view === "capability-system";
}

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
    activeSoulKey,
    soulOptions,
  } = useAppStore();
  const [mounted, setMounted] = useState(false);
  const [forcedPlayground, setForcedPlayground] = useState(false);
  const [chatVisualMode, setChatVisualMode] = useState<ChatVisualMode>("hebo");
  const soulVisualMode = isSoulChatVisualMode(chatVisualMode);
  const visualSoulKey = soulVisualMode ? chatVisualMode : activeSoulKey ?? "hebo";
  const visualSoul = soulOptions.find((soul) => soul.key === visualSoulKey) ?? soulOptions[0] ?? null;
  const soulBackgroundPath = visualSoul?.backgroundPath ?? `/souls/backgrounds/${visualSoulKey}-bg.png`;

  const mainView: WorkspaceView = isTaskLayerView(activeWorkspaceView)
    ? "task-system"
    : activeWorkspaceView === "playground"
      ? "playground"
      : "chat";

  useEffect(() => {
    setMounted(true);
    const storedMode = window.localStorage.getItem("chatVisualMode");
    setChatVisualMode(normalizeChatVisualMode(storedMode));
  }, []);

  useEffect(() => {
    if (isSoulChatVisualMode(chatVisualMode)) {
      document.documentElement.dataset.soul = chatVisualMode;
      return;
    }
    delete document.documentElement.dataset.soul;
  }, [chatVisualMode]);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get("view");
    if (view && WORKSPACE_QUERY_VIEWS.has(view as WorkspaceView)) {
      setWorkspaceView(view as WorkspaceView);
      setForcedPlayground(view === "playground");
    }
  }, [setWorkspaceView]);

  useEffect(() => {
    if (
      activeWorkspaceView !== "chat"
      && activeWorkspaceView !== "playground"
      && !isTaskLayerView(activeWorkspaceView)
      && activeWorkspaceView !== "system-framework"
    ) {
      setWorkspaceView("chat");
    }
  }, [activeWorkspaceView, setWorkspaceView]);

  function returnToWorkspace() {
    setForcedPlayground(false);
    setWorkspaceView("chat");
    const url = new URL(window.location.href);
    url.searchParams.delete("view");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function updateChatVisualMode(mode: ChatVisualMode) {
    const nextMode = mode === "default" ? "hebo" : mode;
    setChatVisualMode(nextMode);
    window.localStorage.setItem("chatVisualMode", nextMode);
  }

  function buildWorkspaceClassName() {
    const classes = ["practical-workspace"];
    if (soulVisualMode) {
      classes.push("practical-workspace--soul-chat");
    }
    return classes.join(" ");
  }

  if (!mounted) {
    return <main className="app-boot-stage" aria-label="正在启动" />;
  }

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
    forcedPlayground || activeWorkspaceView === "playground" ? (
      <PlaygroundView onReturnToWorkspace={returnToWorkspace} />
    ) : (
      <main
        className={buildWorkspaceClassName()}
        data-chat-visual={chatVisualMode}
        style={soulVisualMode ? { "--soul-background-image": `url(${soulBackgroundPath})` } as CSSProperties : undefined}
      >
        {soulVisualMode ? <div aria-hidden="true" className="soul-chat-background-figure" /> : null}
        <Sidebar />
        {activeWorkspaceView === "capability-system" ? (
          <section className="practical-main practical-main--immersive" aria-label="主工作区">
            <section className="practical-content">
              <CapabilitySystemView />
            </section>
          </section>
        ) : mainView === "task-system" ? (
          <section className="practical-main practical-main--immersive" aria-label="主工作区">
            <section className="practical-content">
              <TaskSystemView />
            </section>
          </section>
        ) : (
          <section className="practical-main practical-main--immersive" aria-label="主工作区">
            <section className="practical-content">
              <ChatPanel onVisualModeChange={updateChatVisualMode} visualMode={chatVisualMode} />
            </section>
          </section>
        )}
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
    )
  );
}

export default function Page() {
  return (
    <AppProvider>
      <Workspace />
    </AppProvider>
  );
}
