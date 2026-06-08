"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useConfirmDialog } from "@/components/layout/ConfirmDialogProvider";
import { ContractManagementWorkbench } from "@/components/workspace/views/task-system/contracts/ContractManagementWorkbench";
import { contractSpecTitle } from "@/components/workspace/views/task-system/contracts/contractUtils";
import { EnvironmentContextPicker } from "@/components/workspace/views/task-system/environment/EnvironmentContextPicker";
import {
  taskEnvironmentDisplayTitle,
  taskEnvironmentLoadSummary,
} from "@/components/workspace/views/task-system/environment/environmentPresentation";
import {
  TaskEnvironmentManagementWorkbench,
  defaultEnvironmentDraft,
  environmentDraftFromItem,
  environmentGroupPayload,
  environmentPayloadFromDraft,
  taskAssignmentPayloadFromRecord,
  type EnvironmentDraft,
  type EnvironmentSubpage,
} from "@/components/workspace/views/task-system/environment/TaskEnvironmentManagementWorkbench";
import { NodeConfigurationWorkbench } from "@/components/workspace/views/task-system/nodes/NodeConfigurationWorkbench";
import {
  RunManagementWorkbench,
  type RunManagementSubpage,
} from "@/components/workspace/views/task-system/runs/RunManagementWorkbench";
import { TaskSystemShell } from "@/components/workspace/views/task-system/TaskSystemShell";
import {
  deleteTaskSystemContract,
  deleteTaskSystemEnvironment,
  deleteTaskSystemEnvironmentKindTemplate,
  deleteTaskSystemNodeConfiguration,
  getOrchestrationAgents,
  getOrchestrationCapabilityItems,
  getTaskSystemOverview,
  previewTaskSystemNodeConfigurationRuntime,
  upsertTaskSystemContract,
  upsertTaskSystemEnvironment,
  upsertTaskSystemEnvironmentGroup,
  upsertTaskSystemEnvironmentKindTemplate,
  upsertTaskSystemNodeConfiguration,
  upsertTaskSystemTaskAssignment,
  type ContractSpec,
  type OrchestrationAgentRuntimeCatalog,
  type TaskEnvironmentKindTemplate,
  type TaskNodeConfigurationSpec,
  type TaskSystemOverview,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";

type TaskSystemDomain = "environments" | "contracts" | "nodes" | "runs";
type ContractSubpage = "catalog" | "detail" | "usage";
type NodeSubpage = "catalog" | "detail" | "capability" | "preview";

type LayerNavItem<T extends string> = {
  value: T;
  label: string;
  meta: string;
  detail: string;
};

function environmentRecordTitle(environmentId: string, overview?: TaskSystemOverview | null) {
  const item = taskEnvironmentItem(environmentId, overview);
  if (item) return taskEnvironmentDisplayTitle(item);
  const record = overview?.task_environment_management?.records?.find((entry) => entry.environment_id === environmentId);
  return record?.title || environmentId;
}

function taskEnvironmentItem(environmentId: string, overview?: TaskSystemOverview | null) {
  return overview?.task_environment_management?.environments?.find((item) => item.record.environment_id === environmentId) ?? null;
}

export function TaskSystemView() {
  const confirm = useConfirmDialog();
  const {
    activeWorkspaceView,
    chatTaskEnvironmentBinding,
    clearChatTaskEnvironmentBinding,
    clearTaskGraphWorkspaceTarget,
    setChatTaskEnvironmentBinding,
    taskGraphWorkspaceTarget,
  } = useAppStore();
  const [consolePayload, setConsolePayload] = useState<TaskSystemOverview | null>(null);
  const [nodeRuntimeCatalog, setNodeRuntimeCatalog] = useState<OrchestrationAgentRuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState("");
  const [activeDomain, setActiveDomain] = useState<TaskSystemDomain>("environments");
  const [environmentSubpage, setEnvironmentSubpage] = useState<EnvironmentSubpage>("loadout");
  const [selectedTaskSystemGraphId, setSelectedTaskSystemGraphId] = useState("");
  const [contractSubpage, setContractSubpage] = useState<ContractSubpage>("catalog");
  const [nodeSubpage, setNodeSubpage] = useState<NodeSubpage>("catalog");
  const [runSubpage, setRunSubpage] = useState<RunManagementSubpage>("queue");
  const [environmentDraft, setEnvironmentDraft] = useState<EnvironmentDraft>(() => defaultEnvironmentDraft());
  const loadInFlightRef = useRef<Promise<void> | null>(null);
  const nodeRuntimeCatalogLoadRef = useRef<Promise<void> | null>(null);
  const taskSystemActive = activeWorkspaceView === "task-system";

  const applyOverview = useCallback((overview: TaskSystemOverview) => {
    setConsolePayload(overview);
    const environmentRecords = overview.task_environment_management?.records ?? [];
    setSelectedEnvironmentId((current) => current && environmentRecords.some((item) => item.environment_id === current)
      ? current
      : environmentRecords[0]?.environment_id || "");
  }, []);

  const loadNodeRuntimeCatalog = useCallback(async () => {
    if (nodeRuntimeCatalogLoadRef.current) return nodeRuntimeCatalogLoadRef.current;
    const run = (async () => {
      try {
        const [catalog, capabilityItems] = await Promise.all([
          getOrchestrationAgents(),
          getOrchestrationCapabilityItems().catch(() => ({ capability_items: [] })),
        ]);
        setNodeRuntimeCatalog({
          ...catalog,
          options: {
            ...catalog.options,
            capability_items: capabilityItems.capability_items,
          },
        });
      } catch {
        setNodeRuntimeCatalog((current) => current ?? null);
      } finally {
        nodeRuntimeCatalogLoadRef.current = null;
      }
    })();
    nodeRuntimeCatalogLoadRef.current = run;
    return run;
  }, []);

  const load = useCallback(async () => {
    if (loadInFlightRef.current) return loadInFlightRef.current;
    const run = (async () => {
      setLoading(true);
      setError("");
      try {
        const overview = await getTaskSystemOverview();
        applyOverview(overview);
        void loadNodeRuntimeCatalog();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "任务系统加载失败");
      } finally {
        setLoading(false);
        loadInFlightRef.current = null;
      }
    })();
    loadInFlightRef.current = run;
    return run;
  }, [applyOverview, loadNodeRuntimeCatalog]);

  useEffect(() => {
    if (!taskSystemActive) return;
    void load();
  }, [load, taskSystemActive]);

  const contractManagement = useMemo(() => consolePayload?.contract_management ?? null, [consolePayload]);
  const contractSpecs = useMemo(() => contractManagement?.contract_specs ?? [], [contractManagement]);
  const environmentItems = useMemo(
    () => consolePayload?.task_environment_management?.environments ?? [],
    [consolePayload],
  );
  const selectedEnvironmentItem = useMemo(
    () => environmentItems.find((item) => item.record.environment_id === selectedEnvironmentId)
      ?? environmentItems[0]
      ?? null,
    [environmentItems, selectedEnvironmentId],
  );
  const environmentGroupOptions = useMemo(
    () => consolePayload?.task_environment_management?.groups?.map((item) => ({
      value: item.group_id,
      label: `${item.title || item.group_id} · ${item.group_id}`,
    })) ?? [],
    [consolePayload],
  );
  const kindTemplates = consolePayload?.environment_kind_management?.kind_templates ?? [];
  const selectedEnvironmentGraphRows = useMemo(
    () => (consolePayload?.environment_graph_inventory?.items ?? [])
      .filter((item) => String(item.environment_id || "") === selectedEnvironmentId),
    [consolePayload, selectedEnvironmentId],
  );

  useEffect(() => {
    if (!selectedEnvironmentItem) return;
    setEnvironmentDraft(environmentDraftFromItem(selectedEnvironmentItem));
  }, [selectedEnvironmentItem]);

  useEffect(() => {
    const currentStillVisible = selectedEnvironmentGraphRows
      .some((item) => String(item.graph_id ?? "") === selectedTaskSystemGraphId);
    if (!currentStillVisible) {
      setSelectedTaskSystemGraphId(String(selectedEnvironmentGraphRows[0]?.graph_id ?? ""));
    }
  }, [selectedEnvironmentGraphRows, selectedTaskSystemGraphId]);

  useEffect(() => {
    if (!taskSystemActive || !taskGraphWorkspaceTarget) return;
    setActiveDomain("environments");
    setEnvironmentSubpage("graphs");

    const targetGraphId = String(taskGraphWorkspaceTarget.graph_id || "").trim();
    const targetEnvironmentId = String(taskGraphWorkspaceTarget.task_environment_id || "").trim();
    if (targetGraphId) {
      setSelectedTaskSystemGraphId(targetGraphId);
    }
    if (targetEnvironmentId) {
      setSelectedEnvironmentId(targetEnvironmentId);
    }
    if (!consolePayload) return;

    const graphInventoryRow = targetGraphId
      ? (consolePayload.environment_graph_inventory?.items ?? []).find((item) => String(item.graph_id ?? "") === targetGraphId)
      : null;
    const resolvedEnvironmentId = targetEnvironmentId || String(graphInventoryRow?.environment_id || "").trim();
    if (resolvedEnvironmentId) {
      setSelectedEnvironmentId(resolvedEnvironmentId);
      setEnvironmentDraft(environmentDraftFromItem(taskEnvironmentItem(resolvedEnvironmentId, consolePayload)));
    }
    clearTaskGraphWorkspaceTarget();
  }, [clearTaskGraphWorkspaceTarget, consolePayload, taskGraphWorkspaceTarget, taskSystemActive]);

  function createEnvironmentDraft() {
    const index = environmentItems.length + 1;
    const suffix = String(index).padStart(2, "0");
    setSelectedEnvironmentId("");
    setEnvironmentDraft({
      ...defaultEnvironmentDraft(),
      environment_id: `env.custom.workspace_${suffix}`,
      prompt_id: `environment.custom.workspace_${suffix}`,
      storage_namespace: `custom/workspace_${suffix}`,
    });
    setActiveDomain("environments");
    setEnvironmentSubpage("loadout");
    setNotice("已创建任务环境草稿。");
  }

  async function saveEnvironmentDraft() {
    const environmentId = environmentDraft.environment_id.trim();
    if (!environmentId.startsWith("env.")) {
      setError("任务环境标识必须以 env. 开头。");
      return;
    }
    setSaving("task-environment");
    setError("");
    setNotice("");
    try {
      if (!environmentGroupOptions.some((item) => item.value === environmentDraft.group_id)) {
        await upsertTaskSystemEnvironmentGroup(
          environmentDraft.group_id,
          environmentGroupPayload(environmentDraft.group_id, consolePayload),
        );
      }
      const payload = await upsertTaskSystemEnvironment(environmentId, environmentPayloadFromDraft(environmentDraft));
      setConsolePayload(payload);
      setSelectedEnvironmentId(environmentId);
      setNotice("任务环境已保存并可被 runtime 装配。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务环境失败");
    } finally {
      setSaving("");
    }
  }

  async function removeSelectedEnvironment() {
    const environmentId = selectedEnvironmentItem?.record.environment_id || environmentDraft.environment_id;
    if (!environmentId) return;
    const approved = await confirm({
      title: `删除任务环境「${environmentRecordTitle(environmentId, consolePayload) || environmentId}」`,
      body: "只会删除配置文件中的自定义环境。内置默认环境不会被删除。",
      confirmLabel: "删除环境",
      tone: "warning",
    });
    if (!approved) return;
    setSaving("task-environment-delete");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemEnvironment(environmentId);
      setConsolePayload(payload);
      const nextId = payload.task_environment_management?.records?.[0]?.environment_id || "";
      setSelectedEnvironmentId(nextId);
      setEnvironmentDraft(environmentDraftFromItem(taskEnvironmentItem(nextId, payload)));
      if (chatTaskEnvironmentBinding?.task_environment_id === environmentId) clearChatTaskEnvironmentBinding();
      setNotice("任务环境配置已删除。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除任务环境失败");
    } finally {
      setSaving("");
    }
  }

  async function saveKindTemplate(template: TaskEnvironmentKindTemplate) {
    setSaving("environment-kind");
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemEnvironmentKindTemplate(template.kind_id, template);
      setConsolePayload(payload);
      setNotice(`环境类型「${template.title || template.kind_id}」已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存环境类型失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function removeKindTemplate(kindId: string) {
    if (!kindId) return;
    const approved = await confirm({
      title: `删除环境类型「${kindId}」`,
      body: "删除类型模板不会删除已经存在的任务环境，但这些环境需要重新选择有效类型。",
      confirmLabel: "删除类型",
      tone: "warning",
    });
    if (!approved) return;
    setSaving("environment-kind");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemEnvironmentKindTemplate(kindId);
      setConsolePayload(payload);
      setNotice(`环境类型「${kindId}」已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除环境类型失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function assignTaskEnvironment(record: Record<string, unknown>, environmentId: string) {
    const taskId = String(record.task_id || "");
    if (!taskId) return;
    setSaving(`task-assignment:${taskId}`);
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemTaskAssignment(taskId, taskAssignmentPayloadFromRecord(record, environmentId));
      setConsolePayload(payload);
      setNotice(environmentId ? `任务「${taskId}」已归属到 ${environmentId}。` : `任务「${taskId}」已取消环境归属。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存任务归属失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function saveContractSpec(spec: ContractSpec) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemContract(spec.contract_id, spec);
      setConsolePayload(payload);
      setNotice(`契约“${contractSpecTitle(spec)}”已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存契约失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function removeContractSpec(contractId: string) {
    setSaving("contract-spec");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemContract(contractId);
      setConsolePayload(payload);
      setNotice(`契约“${contractId}”已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除契约失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function saveNodeConfiguration(spec: TaskNodeConfigurationSpec) {
    setSaving("node-configuration");
    setError("");
    setNotice("");
    try {
      const payload = await upsertTaskSystemNodeConfiguration(spec.node_config_id, spec);
      setConsolePayload(payload);
      setNotice(`节点配置「${spec.title || spec.node_config_id}」已保存。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存节点配置失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function removeNodeConfiguration(nodeConfigId: string) {
    setSaving("node-configuration");
    setError("");
    setNotice("");
    try {
      const payload = await deleteTaskSystemNodeConfiguration(nodeConfigId);
      setConsolePayload(payload);
      setNotice(`节点配置「${nodeConfigId}」已删除。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除节点配置失败");
      throw exc;
    } finally {
      setSaving("");
    }
  }

  async function previewNodeConfiguration(nodeConfigId: string, environmentId = "") {
    return previewTaskSystemNodeConfigurationRuntime(nodeConfigId, { environment_id: environmentId });
  }

  const selectedEnvironmentLabel = selectedEnvironmentItem
    ? taskEnvironmentDisplayTitle(selectedEnvironmentItem)
    : environmentDraft.title || selectedEnvironmentId || "未选择任务环境";
  const domainItems: Array<LayerNavItem<TaskSystemDomain>> = [
    {
      value: "environments",
      label: "环境管理",
      meta: selectedEnvironmentItem ? taskEnvironmentDisplayTitle(selectedEnvironmentItem) : `${environmentItems.length} 个环境`,
      detail: "环境类型、资源装载、环境说明、环境内任务和环境任务图",
    },
    {
      value: "contracts",
      label: "契约库",
      meta: `${contractSpecs.length} 个契约`,
      detail: "可复用输入输出、产物、验收和运行策略",
    },
    {
      value: "nodes",
      label: "节点配置",
      meta: `${consolePayload?.node_configuration_management?.summary?.node_configuration_count ?? 0} 个配置`,
      detail: "节点角色、执行者引用、契约绑定和装配预览",
    },
    {
      value: "runs",
      label: "运行管理",
      meta: "队列和记录",
      detail: "工作队列、图任务项目、历史记录和清理预览",
    },
  ];
  const environmentPages: Array<LayerNavItem<EnvironmentSubpage>> = [
    { value: "types", label: "环境类型", meta: `${kindTemplates.length} 类模板`, detail: "按用途预设默认资源和策略" },
    { value: "loadout", label: "资源装载", meta: selectedEnvironmentItem ? taskEnvironmentLoadSummary(selectedEnvironmentItem) : "未保存", detail: "资料、记忆、检索和产物空间" },
    { value: "prompts", label: "环境说明", meta: `${selectedEnvironmentItem?.environment_prompts?.length ?? (environmentDraft.prompt_content.trim() ? 1 : 0)} 条`, detail: "Agent 进入环境后可读取的说明" },
    { value: "tasks", label: "环境内任务", meta: `${consolePayload?.environment_task_inventory?.summary?.task_inventory_count ?? 0} 项任务`, detail: "任务归属和默认执行链路" },
    { value: "graphs", label: "环境任务图", meta: `${consolePayload?.environment_graph_inventory?.summary?.graph_inventory_count ?? 0} 张图`, detail: "任务图归属、发布态和健康摘要" },
  ];
  const contractPages: Array<LayerNavItem<ContractSubpage>> = [
    { value: "catalog", label: "契约目录", meta: `${contractSpecs.length} 个契约`, detail: "筛选、搜索和定位契约" },
    { value: "detail", label: "契约详情", meta: "详情", detail: "输入输出、产物、验收和策略" },
    { value: "usage", label: "使用影响", meta: `${consolePayload?.contract_usage_index?.summary?.usage_count ?? 0} 处引用`, detail: "任务、图、节点和边引用" },
  ];
  const nodePages: Array<LayerNavItem<NodeSubpage>> = [
    { value: "catalog", label: "节点目录", meta: `${consolePayload?.node_configuration_management?.summary?.node_configuration_count ?? 0} 个配置`, detail: "按环境、执行者和问题筛选" },
    { value: "detail", label: "节点详情", meta: "角色说明", detail: "角色、职责、边界和执行者引用" },
    { value: "capability", label: "能力与权限", meta: `${nodeRuntimeCatalog?.options?.capability_items?.length ?? 0} 项能力`, detail: "工具、记忆、产物和失败边界" },
    { value: "preview", label: "装配预览", meta: "可见输入", detail: "Agent 实际会拿到的运行输入" },
  ];
  const runPages: Array<LayerNavItem<RunManagementSubpage>> = [
    { value: "queue", label: "工作队列", meta: "当前运行", detail: "运行、等待、停滞和失败任务" },
    { value: "projects", label: "图任务项目", meta: "总任务", detail: "按项目查看 graph run 和节点进度" },
    { value: "records", label: "历史记录", meta: "已完成/已清出", detail: "查看最近完成和隐藏记录" },
    { value: "cleanup", label: "清理预览", meta: "后端保护", detail: "预览可删除记录和保护原因" },
  ];

  const contextSlot = (
    <EnvironmentContextPicker
      environmentItems={environmentItems}
      onCreate={createEnvironmentDraft}
      onSelectEnvironment={(environmentId) => {
        setSelectedEnvironmentId(environmentId);
        setEnvironmentDraft(environmentDraftFromItem(taskEnvironmentItem(environmentId, consolePayload)));
      }}
      selectedEnvironmentId={selectedEnvironmentId}
    />
  );

  const subpageItems = activeDomain === "environments"
    ? environmentPages
    : activeDomain === "contracts"
      ? contractPages
      : activeDomain === "nodes"
        ? nodePages
        : runPages;
  const activeSubpage = activeDomain === "environments"
    ? environmentSubpage
    : activeDomain === "contracts"
      ? contractSubpage
      : activeDomain === "nodes"
        ? nodeSubpage
        : runSubpage;

  const managementLayerSlot = (
    <div className="task-system-layer-groups" aria-label="任务系统配置层级">
      <section className="task-system-layer-group">
        <header>
          <strong>配置域</strong>
          <span>任务系统只维护环境、契约和节点配置资产</span>
        </header>
        <div className="task-system-object-table task-system-object-table--home-switch">
          {domainItems.map((item) => {
            const active = activeDomain === item.value;
            return (
              <button
                aria-current={active ? "page" : undefined}
                className={active ? "task-system-object-row task-system-object-row--active" : "task-system-object-row"}
                key={item.value}
                onClick={() => setActiveDomain(item.value)}
                type="button"
              >
                <strong><span className="task-system-object-row__scope">配置域</span>{item.label}</strong>
                <span className="task-system-object-row__meta">{item.meta}</span>
                <em>{active ? "当前" : "进入"}</em>
              </button>
            );
          })}
        </div>
      </section>
      <section className="task-system-layer-group">
        <header>
          <strong>当前域页面</strong>
          <span>切换子页面不会离开任务系统</span>
        </header>
        <div className="task-system-object-table task-system-object-table--subpages">
          {subpageItems.map((item) => {
            const active = activeSubpage === item.value;
            return (
              <button
                aria-current={active ? "page" : undefined}
                className={active ? "task-system-object-row task-system-object-row--active" : "task-system-object-row"}
                key={item.value}
                onClick={() => {
                  if (activeDomain === "environments") setEnvironmentSubpage(item.value as EnvironmentSubpage);
                  if (activeDomain === "contracts") setContractSubpage(item.value as ContractSubpage);
                  if (activeDomain === "nodes") setNodeSubpage(item.value as NodeSubpage);
                  if (activeDomain === "runs") setRunSubpage(item.value as RunManagementSubpage);
                }}
                type="button"
              >
                <strong><span className="task-system-object-row__scope">子页</span>{item.label}</strong>
                <span className="task-system-object-row__meta">{item.meta}</span>
                <em>{active ? "当前" : "查看"}</em>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );

  const path = activeDomain === "environments"
    ? `环境管理 / ${environmentPages.find((item) => item.value === environmentSubpage)?.label ?? ""} / ${selectedEnvironmentLabel}`
    : activeDomain === "contracts"
      ? `契约库 / ${contractPages.find((item) => item.value === contractSubpage)?.label ?? ""}`
      : activeDomain === "nodes"
        ? `节点配置 / ${nodePages.find((item) => item.value === nodeSubpage)?.label ?? ""}`
        : `运行管理 / ${runPages.find((item) => item.value === runSubpage)?.label ?? ""}`;

  return (
    <TaskSystemShell
      activeLayer={activeDomain}
      contextSlot={contextSlot}
      error={loading ? "" : error}
      layerSlot={managementLayerSlot}
      navItems={domainItems}
      notice={notice || (loading ? "任务系统正在加载..." : "")}
      onRefresh={() => void load()}
      onSelectLayer={(layer) => {
        void load();
        setActiveDomain(layer);
      }}
      path={path}
      title="任务系统"
    >
      <section className={`task-management-stage task-management-stage--${activeDomain}`}>
        {activeDomain === "environments" ? (
          <TaskEnvironmentManagementWorkbench
            activePage={environmentSubpage}
            chatTaskEnvironmentBinding={chatTaskEnvironmentBinding}
            draft={environmentDraft}
            environmentItems={environmentItems}
            groupOptions={environmentGroupOptions}
            kindTemplates={kindTemplates}
            onAssignTaskEnvironment={assignTaskEnvironment}
            onBindEnvironment={(environmentId, environmentLabel) => {
              setChatTaskEnvironmentBinding({
                task_environment_id: environmentId,
                environment_label: environmentLabel,
                source: "task-system",
              });
              setNotice(`主会话已绑定任务环境：${environmentLabel || environmentId}`);
            }}
            onClearEnvironmentBinding={() => {
              clearChatTaskEnvironmentBinding();
              setNotice("主会话任务环境绑定已解除。");
            }}
            onCreate={createEnvironmentDraft}
            onDelete={() => void removeSelectedEnvironment()}
            onDeleteKindTemplate={removeKindTemplate}
            onSave={() => void saveEnvironmentDraft()}
            onSaveKindTemplate={saveKindTemplate}
            onSelectGraph={setSelectedTaskSystemGraphId}
            onSetDraft={setEnvironmentDraft}
            saving={saving}
            selectedEnvironmentId={selectedEnvironmentItem?.record.environment_id || ""}
            selectedGraphId={selectedTaskSystemGraphId}
            taskSystemOverview={consolePayload}
          />
        ) : null}

        {activeDomain === "contracts" ? (
          <ContractManagementWorkbench
            activePage={contractSubpage}
            contractManagement={contractManagement}
            contractSpecs={contractSpecs}
            contractUsageIndex={consolePayload?.contract_usage_index}
            onDeleteContract={removeContractSpec}
            onSaveContract={saveContractSpec}
            saving={saving === "contract-spec"}
          />
        ) : null}

        {activeDomain === "nodes" ? (
          <NodeConfigurationWorkbench
            activePage={nodeSubpage}
            contractSpecs={contractSpecs}
            environmentItems={environmentItems}
            nodeRuntimeCatalog={nodeRuntimeCatalog}
            onDeleteNodeConfiguration={removeNodeConfiguration}
            onPreviewNodeConfiguration={previewNodeConfiguration}
            onSaveNodeConfiguration={saveNodeConfiguration}
            saving={saving === "node-configuration"}
            selectedEnvironmentId={selectedEnvironmentId}
            taskSystemOverview={consolePayload}
          />
        ) : null}

        {activeDomain === "runs" ? (
          <RunManagementWorkbench activePage={runSubpage} />
        ) : null}
      </section>
    </TaskSystemShell>
  );
}
