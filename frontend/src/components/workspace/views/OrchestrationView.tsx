"use client";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { OrchestrationAgentAssemblyPages } from "@/components/workspace/views/orchestration/OrchestrationAgentAssemblyPages";
import { OrchestrationAssemblyShell } from "@/components/workspace/views/orchestration/OrchestrationAssemblyShell";
import { OrchestrationDirectoryRail } from "@/components/workspace/views/orchestration/OrchestrationDirectoryRail";
import { useOrchestrationAssemblyController } from "@/components/workspace/views/orchestration/useOrchestrationAssemblyController";
import { DEFAULT_SUB_AGENT_GROUP_ID } from "@/components/workspace/views/orchestration/orchestrationAssemblyModel";

export function OrchestrationView() {
  const confirm = useConfirmDialog();
  const controller = useOrchestrationAssemblyController();

  const directory = (
    <OrchestrationDirectoryRail
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
          body: "该 Agent 会从编排配置中移除。",
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
          body: "该组会从编排配置中移除，组内 Agent 不会被删除。",
          confirmLabel: "删除组",
          tone: "warning",
        })) {
          void controller.removeAgentGroup();
        }
      }}
    />
  );

  return (
    <OrchestrationAssemblyShell controller={controller} directory={directory}>
      <OrchestrationAgentAssemblyPages controller={controller} />
    </OrchestrationAssemblyShell>
  );
}
