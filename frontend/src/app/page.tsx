"use client";

import { useEffect } from "react";

import { Navbar } from "@/components/layout/Navbar";
import { ResizeHandle } from "@/components/layout/ResizeHandle";
import { RightRail } from "@/components/layout/RightRail";
import { Sidebar } from "@/components/layout/Sidebar";
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
import { AppProvider, useAppStore } from "@/lib/store";

function Workspace() {
  const { sidebarWidth, setSidebarWidth, activeSoulKey, activeWorkspaceView, setWorkspaceView } = useAppStore();
  const isBoundaryWorkspace = activeWorkspaceView === "task-system" || activeWorkspaceView === "orchestration";
  const showRightRail = !isBoundaryWorkspace;

  useEffect(() => {
    if (activeSoulKey) {
      document.documentElement.dataset.soul = activeSoulKey;
      return;
    }
    delete document.documentElement.dataset.soul;
  }, [activeSoulKey]);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get("view");
    if (view === "task-system" || view === "orchestration") {
      setWorkspaceView(view);
    }
  }, [setWorkspaceView]);

  if (activeWorkspaceView === "system-framework") {
    return (
      <main className="system-framework-stage min-h-screen">
        <SystemFrameworkView />
      </main>
    );
  }

  return (
    <main className={`workspace-shell ${isBoundaryWorkspace ? "workspace-shell--task-focus" : ""} min-h-screen px-3 py-4 md:px-6 md:py-6`}>
      <div className={`workspace-grid mx-auto flex flex-col gap-4 ${isBoundaryWorkspace ? "max-w-[1920px]" : "max-w-[1820px]"}`}>
        <Navbar />
        <div className={`workspace-frame flex min-h-[calc(100vh-144px)] flex-col gap-4 xl:flex-row ${isBoundaryWorkspace ? "xl:gap-3" : "xl:gap-0"}`}>
          <div className="w-full xl:shrink-0" style={{ width: `min(100%, ${isBoundaryWorkspace ? Math.min(sidebarWidth, 248) : sidebarWidth}px)` }}>
            <Sidebar />
          </div>
          <ResizeHandle onResize={(delta) => setSidebarWidth(Math.max(280, sidebarWidth + delta))} />
          <WorkspacePanel />
          {showRightRail ? (
            <div className={`w-full xl:shrink-0 ${isBoundaryWorkspace ? "xl:ml-0 xl:w-[308px]" : "xl:ml-4 xl:w-[320px]"}`}>
              <RightRail />
            </div>
          ) : null}
        </div>
      </div>
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
