"use client";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { AgentSystemAssemblyPages } from "@/components/workspace/views/agent-system/AgentSystemAssemblyPages";
import { AgentSystemAssemblyShell } from "@/components/workspace/views/agent-system/AgentSystemAssemblyShell";
import { AgentSystemDirectoryRail } from "@/components/workspace/views/agent-system/AgentSystemDirectoryRail";
import { useAgentSystemAssemblyController } from "@/components/workspace/views/agent-system/useAgentSystemAssemblyController";
import { DEFAULT_SUB_AGENT_GROUP_ID } from "@/components/workspace/views/agent-system/agentSystemAssemblyModel";

export function AgentSystemView() {
  const confirm = useConfirmDialog();
  const controller = useAgentSystemAssemblyController();

  const directory = (
    <AgentSystemDirectoryRail
      activeSection={controller.activeSection}
      activeSectionItems={controller.activeDirectoryGroup?.items ?? []}
      agentGroups={controller.agentGroups}
      agents={controller.agents}
      sectionCounts={controller.sectionCounts}
      loading={controller.loading}
      query={controller.query}
      selectAgent={controller.selectAgent}
      selectCategory={controller.selectCategory}
      selectedAgentId={controller.selectedAgentId}
      selectedGroupId={controller.selectedGroupId}
      selectionKind={controller.selectionKind}
      selectSubAgentGroup={controller.selectSubAgentGroup}
      setQuery={controller.setQuery}
      selectedGroupAgents={controller.selectedGroupAgents}
      saving={controller.saving}
      startBlankAgentDraft={controller.startBlankAgentDraft}
      startBlankGroupDraft={controller.startBlankGroupDraft}
      ungroupedCustomAgents={controller.ungroupedCustomAgents}
      removeAgentById={async (agentId, agentName) => {
        if (await confirm({
          title: `删除 Agent「${agentName || agentId}」`,
          body: "该 Agent 会从 Agent 管理配置中移除。",
          confirmLabel: "删除 Agent",
        })) {
          void controller.removeAgent(agentId);
        }
      }}
      removeSelectedGroup={async () => {
        if (!controller.selectedGroupId || controller.selectedGroupId === DEFAULT_SUB_AGENT_GROUP_ID) return;
        const groupName = controller.selectedGroup?.title || controller.selectedGroupId;
        if (await confirm({
          title: `删除 Agent 组「${groupName}」`,
          body: "该组会从 Agent 管理配置中移除，组内 Agent 不会被删除。",
          confirmLabel: "删除组",
          tone: "warning",
        })) {
          void controller.removeAgentGroup();
        }
      }}
    />
  );

  return (
    <AgentSystemAssemblyShell controller={controller} directory={directory}>
      <AgentSystemAssemblyPages controller={controller} />
    </AgentSystemAssemblyShell>
  );
}




