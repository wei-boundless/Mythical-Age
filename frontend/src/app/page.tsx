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
  const { sidebarWidth, setSidebarWidth, activeSoulKey, activeWorkspaceView } = useAppStore();

  useEffect(() => {
    if (activeSoulKey) {
      document.documentElement.dataset.soul = activeSoulKey;
      return;
    }
    delete document.documentElement.dataset.soul;
  }, [activeSoulKey]);

  if (activeWorkspaceView === "system-framework") {
    return (
      <main className="system-framework-stage min-h-screen">
        <SystemFrameworkView />
      </main>
    );
  }

  return (
    <main className="workspace-shell min-h-screen px-3 py-4 md:px-6 md:py-6">
      <div className="workspace-grid mx-auto flex max-w-[1820px] flex-col gap-4">
        <Navbar />
        <div className="workspace-frame flex min-h-[calc(100vh-144px)] flex-col gap-4 xl:flex-row xl:gap-0">
          <div className="w-full xl:shrink-0" style={{ width: `min(100%, ${sidebarWidth}px)` }}>
            <Sidebar />
          </div>
          <ResizeHandle onResize={(delta) => setSidebarWidth(Math.max(280, sidebarWidth + delta))} />
          <WorkspacePanel />
          <div className="w-full xl:ml-4 xl:w-[320px] xl:shrink-0">
            <RightRail />
          </div>
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
