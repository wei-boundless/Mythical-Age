"use client";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { ExperimentsView } from "@/components/workspace/views/ExperimentsView";
import { HealthSystemView } from "@/components/workspace/views/HealthSystemView";
import { MemoryView } from "@/components/workspace/views/MemoryView";
import { OperationsView } from "@/components/workspace/views/OperationsView";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { TaskSystemView } from "@/components/workspace/views/TaskSystemView";
import { useAppStore } from "@/lib/store";

export function WorkspacePanel() {
  const { activeWorkspaceView } = useAppStore();

  if (activeWorkspaceView === "chat") {
    return <ChatPanel />;
  }

  const views = {
    memory: <MemoryView />,
    "test-system": <HealthSystemView />,
    "health-system": <HealthSystemView />,
    operations: <OperationsView />,
    evidence: <OperationsView initialPanel="agents" />,
    "task-system": <TaskSystemView />,
    "system-framework": <TaskSystemView />,
    experiments: <ExperimentsView />,
    playground: <PlaygroundView />
  } as const;
  const isSystemFramework = false;

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col">
      <div
        className={`panel workspace-view-shell ${isSystemFramework ? "workspace-view-shell--map p-0" : "p-5"} flex min-h-0 flex-1 flex-col overflow-hidden`}
      >
        {views[activeWorkspaceView]}
      </div>
    </section>
  );
}
