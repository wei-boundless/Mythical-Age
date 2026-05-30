"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getHealthSystemOverview,
  getHealthSystemTaskDetail,
  getHealthSystemTaskRecordMaintenance,
  pruneHealthSystemTaskRecords,
  type HealthSystemOverview,
  type HealthTaskRecordMaintenance,
} from "@/lib/api";

import { byRisk, type HealthPage, type MaintenanceBucket, type TokenChartMode } from "./healthFormatters";
import { buildHealthSystemViewModel } from "./healthSelectors";

export function useHealthSystemController() {
  const [activePage, setActivePage] = useState<HealthPage>("overview");
  const [overview, setOverview] = useState<HealthSystemOverview | null>(null);
  const [maintenance, setMaintenance] = useState<HealthTaskRecordMaintenance | null>(null);
  const [tokenChartMode, setTokenChartMode] = useState<TokenChartMode>("daily");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [taskDetail, setTaskDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [maintenanceBusy, setMaintenanceBusy] = useState("");
  const [maintenanceMessage, setMaintenanceMessage] = useState("");

  const view = useMemo(
    () => buildHealthSystemViewModel(overview, maintenance, selectedTaskId, tokenChartMode),
    [maintenance, overview, selectedTaskId, tokenChartMode],
  );

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await getHealthSystemOverview();
      setOverview(payload);
      const firstTask = [...(payload.tasks ?? [])].sort(byRisk)[0];
      setSelectedTaskId((current) => current || firstTask?.task_run_id || "");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "健康系统数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const loadMaintenance = useCallback(async () => {
    try {
      const payload = await getHealthSystemTaskRecordMaintenance("static", 24 * 60 * 60);
      setMaintenance(payload);
    } catch {
      setMaintenance(null);
    }
  }, []);

  useEffect(() => {
    if (activePage === "maintenance") {
      void loadMaintenance();
    }
  }, [activePage, loadMaintenance]);

  useEffect(() => {
    const taskRunId = view.selectedTask?.task_run_id || "";
    if (activePage !== "tasks" || !taskRunId) {
      setDetailLoading(false);
      if (!taskRunId) setTaskDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void getHealthSystemTaskDetail(taskRunId)
      .then((payload) => {
        if (!cancelled) setTaskDetail(payload);
      })
      .catch(() => {
        if (!cancelled) setTaskDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activePage, view.selectedTask?.task_run_id]);

  const pruneRecords = useCallback(async (bucket: MaintenanceBucket, taskRunIds: string[] = []) => {
    setMaintenanceBusy(taskRunIds.length ? taskRunIds[0] : bucket);
    setMaintenanceMessage("");
    setError("");
    try {
      const result = await pruneHealthSystemTaskRecords({
        bucket,
        task_run_ids: taskRunIds,
        dry_run: false,
        min_age_seconds: 24 * 60 * 60,
      });
      setMaintenanceMessage(`维护完成：删除 ${result.deleted_task_run_ids.length} 条，保护 ${result.protected_task_run_ids?.length ?? result.skipped.length} 条。回执 ${String(result.maintenance_receipt?.receipt_id || "未持久化")}`);
      setSelectedTaskId((current) => result.deleted_task_run_ids.includes(current) ? "" : current);
      await loadMaintenance();
      await loadOverview();
    } catch (pruneError) {
      setError(pruneError instanceof Error ? pruneError.message : "任务记录清理失败");
    } finally {
      setMaintenanceBusy("");
    }
  }, [loadMaintenance, loadOverview]);

  return {
    activePage,
    detailLoading,
    error,
    loadMaintenance,
    loadOverview,
    loading,
    maintenance,
    maintenanceBusy,
    maintenanceMessage,
    overview,
    pruneRecords,
    selectedTaskId,
    setActivePage,
    setSelectedTaskId,
    setTokenChartMode,
    taskDetail,
    tokenChartMode,
    view,
  };
}
