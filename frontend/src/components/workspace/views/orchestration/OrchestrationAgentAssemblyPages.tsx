"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

import {
  OrchestrationAssemblyOverviewWorkbench,
  OrchestrationCollaborationWorkbench,
  OrchestrationContextMemoryWorkbench,
  OrchestrationDiagnosticsWorkbench,
  OrchestrationModelRuntimeWorkbench,
  OrchestrationRuntimeConfigWorkbench,
  OrchestrationRuntimePermissionWorkbench,
} from "@/components/workspace/views/orchestration/OrchestrationAgentConfigWorkbenches";
import { OrchestrationGroupWorkbench } from "@/components/workspace/views/orchestration/OrchestrationGroupWorkbench";
import { OrchestrationRegistryWorkbench } from "@/components/workspace/views/orchestration/OrchestrationRegistryWorkbench";
import { Notice } from "@/ui/Notice";
import { CATEGORY_LABELS } from "./orchestrationAssemblyModel";
import { OrchestrationLayerNav } from "./OrchestrationLayerNav";
import type { OrchestrationAssemblyController } from "./useOrchestrationAssemblyController";

export function OrchestrationAgentAssemblyPages({
  controller,
}: {
  controller: OrchestrationAssemblyController;
}) {
  return (
    <>
      <OrchestrationLayerNav
        activeLayer={controller.activeLayer}
        groups={controller.assemblyNavGroups}
        onSelectLayer={controller.setActiveLayer}
      />

      {controller.selectionKind === "empty" ? (
        <div className="boundary-empty boundary-empty--large">请选择一个 Agent，或新建子 Agent 草稿。</div>
      ) : null}

      {controller.selectionKind === "group" ? (
        <OrchestrationGroupWorkbench
          agents={controller.agents}
          groupDraft={controller.groupDraft}
          groupDraftAvailableAgents={controller.groupDraftAvailableAgents}
          groupDraftMemberAgents={controller.groupDraftMemberAgents}
          groupMembersChanged={controller.groupMembersChanged}
          saveAgentGroup={controller.saveAgentGroup}
          saving={controller.saving}
          setGroupDraft={controller.setGroupDraft}
          toggleGroupMember={controller.toggleGroupMember}
        />
      ) : null}

      {controller.activeLayer !== "groups" && (controller.selectedAgent || controller.agentMode === "new") ? (
        <>
          {controller.activeLayer === "identity" ? (
            <OrchestrationRegistryWorkbench
              agentDeleteBlocked={controller.agentDeleteBlocked}
              agentDraft={controller.agentDraft}
              agentMode={controller.agentMode}
              categoryLabels={CATEGORY_LABELS}
              overlapOps={controller.overlapOps}
              patchAgentDraft={controller.patchAgentDraft}
              profileMissing={controller.profileMissing}
              removeAgent={controller.removeAgent}
              runtimeDraft={controller.runtimeDraft}
              runtimeSaveBlocked={controller.runtimeSaveBlocked}
              saveAgent={controller.saveAgent}
              saveRuntimeProfile={controller.saveRuntimeProfile}
              saving={controller.saving}
              selectedAgentBuiltin={Boolean(controller.selectedAgent?.builtin)}
            />
          ) : null}

          {controller.activeLayer === "runtime_permissions" ? (
            <>
              {controller.capabilityItemsError ? <Notice icon={<AlertTriangle size={16} />} tone="error">{controller.capabilityItemsError}</Notice> : null}
              {controller.capabilityItemsLoading ? <Notice icon={<RefreshCw size={16} />}>正在加载能力准入项...</Notice> : null}
              <OrchestrationRuntimePermissionWorkbench
                allowedOpsCount={controller.allowedOps.length}
                blockedOpsCount={controller.blockedOps.length}
                capabilityItems={controller.capabilityItems}
                approvalPolicies={controller.catalog?.options.approval_policies ?? ["default"]}
                approvalPolicyOptions={controller.approvalPolicyOptions}
                displayId={controller.displayId}
                patchRuntimeDraft={controller.patchRuntimeDraft}
                runtimeDraft={controller.runtimeDraft}
                tracePolicyOptions={controller.tracePolicyOptions}
                tracePolicies={controller.catalog?.options.trace_policies ?? ["runtime_event_log"]}
                operationOptionItems={controller.operationOptionItems}
                operationOptions={controller.operationOptions}
                overlapOps={controller.overlapOps}
                overlapSummary={controller.overlapSummary}
                toolPackageOptions={controller.toolPackageOptions}
              />
            </>
          ) : null}

          {controller.activeLayer === "model_runtime" ? (
            <OrchestrationModelRuntimeWorkbench
              patchRuntimeDraft={controller.patchRuntimeDraft}
              providerCatalog={(controller.catalog?.options as { model_provider_catalog?: Record<string, unknown> } | undefined)?.model_provider_catalog}
              runtimeDraft={controller.runtimeDraft}
            />
          ) : null}

          {controller.activeLayer === "runtime_config" ? (
            <OrchestrationRuntimeConfigWorkbench
              displayId={controller.displayId}
              patchRuntimeDraft={controller.patchRuntimeDraft}
              runtimeDraft={controller.runtimeDraft}
              runtimeSaveBlocked={controller.runtimeSaveBlocked}
              saveRuntimeProfile={controller.saveRuntimeProfile}
              saving={controller.saving}
              toolPackageOptions={controller.toolPackageOptions}
            />
          ) : null}

          {controller.activeLayer === "context_memory" ? (
            <OrchestrationContextMemoryWorkbench
              contextSectionOptionItems={controller.contextSectionOptionItems}
              contextSectionOptions={controller.catalog?.options.context_sections ?? []}
              contextSummary={controller.contextSummary}
              displayId={controller.displayId}
              memoryScopeOptionItems={controller.memoryScopeOptionItems}
              memoryScopeOptions={controller.catalog?.options.memory_scopes ?? []}
              memorySummary={controller.memorySummary}
              patchRuntimeDraft={controller.patchRuntimeDraft}
              runtimeDraft={controller.runtimeDraft}
              systemGroupOptionItems={controller.systemGroupOptionItems}
              systemGroupOptions={controller.catalog?.options.system_groups ?? []}
              systemGroupSummary={controller.systemGroupSummary}
            />
          ) : null}

          {controller.activeLayer === "collaboration" ? (
            <OrchestrationCollaborationWorkbench
              agentDraft={controller.agentDraft}
              subagentOptions={controller.subagentOptions}
              displayId={controller.displayId}
              patchRuntimeDraft={controller.patchRuntimeDraft}
              runtimeDraft={controller.runtimeDraft}
            />
          ) : null}

          {controller.activeLayer === "overview" ? (
            <OrchestrationAssemblyOverviewWorkbench
              agentDraft={controller.agentDraft}
              collaborationSummary={controller.collaborationSummary}
              contextSummary={controller.contextSummary}
              memorySummary={controller.memorySummary}
              openLayer={controller.setActiveLayer}
              operationSummary={controller.operationSummary}
              runtimeDraft={controller.runtimeDraft}
              modelSummary={controller.modelSummary}
            />
          ) : null}

          {controller.activeLayer === "diagnostics" ? (
            <OrchestrationDiagnosticsWorkbench
              capabilityItemsCount={controller.capabilityItems.length}
              eligibilityChecks={controller.eligibilityChecks}
              overlapOps={controller.overlapOps}
              runtimeDraft={controller.runtimeDraft}
            />
          ) : null}
        </>
      ) : null}
    </>
  );
}
