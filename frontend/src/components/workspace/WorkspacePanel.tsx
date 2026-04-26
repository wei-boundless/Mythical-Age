"use client";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { EvidenceView } from "@/components/workspace/views/EvidenceView";
import { ExperimentsView } from "@/components/workspace/views/ExperimentsView";
import { MemoryView } from "@/components/workspace/views/MemoryView";
import { PlaygroundView } from "@/components/workspace/views/PlaygroundView";
import { SystemFrameworkView } from "@/components/workspace/views/SystemFrameworkView";
import { TestSystemView } from "@/components/workspace/views/TestSystemView";
import { useAppStore } from "@/lib/store";

export function WorkspacePanel() {
  const { activeWorkspaceView } = useAppStore();

  if (activeWorkspaceView === "chat") {
    return <ChatPanel />;
  }

  const views = {
    memory: <MemoryView />,
    "test-system": <TestSystemView />,
    evidence: <EvidenceView />,
    "system-framework": <SystemFrameworkView />,
    experiments: <ExperimentsView />,
    playground: <PlaygroundView />
  } as const;
  const isSystemFramework = activeWorkspaceView === "system-framework";

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
