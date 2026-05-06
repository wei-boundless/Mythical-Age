"use client";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { ExperimentsView } from "@/components/workspace/views/ExperimentsView";
import { HealthSystemView } from "@/components/workspace/views/HealthSystemView";
import { MemoryView } from "@/components/workspace/views/MemoryView";
import { MCPSystemView } from "@/components/workspace/views/MCPSystemView";
import { OrchestrationView } from "@/components/workspace/views/OrchestrationView";
import { CapabilitySystemView } from "@/components/workspace/views/CapabilitySystemView";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { SystemConfigView } from "@/components/workspace/views/SystemConfigView";
import { TaskSystemView } from "@/components/workspace/views/TaskSystemView";
import { useAppStore } from "@/lib/store";

export function WorkspacePanel() {
  const { activeWorkspaceView } = useAppStore();
  const isBoundaryStudio = activeWorkspaceView === "task-system" || activeWorkspaceView === "orchestration";

  if (activeWorkspaceView === "chat") {
    return <ChatPanel />;
  }

  const views = {
    memory: <MemoryView />,
    "test-system": <HealthSystemView />,
    "health-system": <HealthSystemView />,
    "capability-system": <CapabilitySystemView />,
    "mcp-system": <MCPSystemView />,
    evidence: <CapabilitySystemView initialPanel="tools" />,
    "task-system": <TaskSystemView />,
    orchestration: <OrchestrationView />,
    "system-framework": <TaskSystemView />,
    experiments: <ExperimentsView />,
    playground: <PlaygroundView />,
    "system-config": <SystemConfigView />
  } as const;
  const isSystemFramework = false;

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col">
      <div
        className={`panel workspace-view-shell ${isSystemFramework ? "workspace-view-shell--map p-0" : isBoundaryStudio ? "workspace-view-shell--task-system p-0" : "p-5"} flex min-h-0 flex-1 flex-col overflow-hidden`}
      >
        {views[activeWorkspaceView as keyof typeof views]}
      </div>
    </section>
  );
}

