"use client";

import { MoreHorizontal } from "lucide-react";
import React, { useMemo, useState } from "react";

import type { RuntimeMonitorActionPayload } from "@/lib/api";
import type { RunMonitorSignal } from "@/lib/run-monitor/types";

type RunMonitorActionMenuProps = {
  signal: RunMonitorSignal;
  loadingAction: string;
  onAction: (payload: RuntimeMonitorActionPayload) => void;
};

const HIDDEN_ACTIONS = new Set(["open", "inspect", "resume_task"]);
const DANGER_ACTIONS = new Set(["delete_record"]);

export function RunMonitorActionMenu({ signal, loadingAction, onAction }: RunMonitorActionMenuProps) {
  const [open, setOpen] = useState(false);
  const actions = useMemo(
    () => (signal.actions ?? []).filter((item) => item.enabled && !HIDDEN_ACTIONS.has(item.action)),
    [signal.actions],
  );
  if (!actions.length) return null;
  const signalId = signal.signal_id || signal.task_instance_id || signal.task_run_id;
  return (
    <div
      className="run-monitor-action-menu"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <button
        aria-expanded={open}
        aria-label="运行操作"
        className="run-monitor-action-menu__trigger"
        disabled={Boolean(loadingAction)}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((current) => !current);
        }}
        type="button"
      >
        <MoreHorizontal size={15} />
      </button>
      {open ? (
        <div className="run-monitor-action-menu__list" role="menu">
          {actions.map((action) => (
            <button
              className={DANGER_ACTIONS.has(action.action) ? "run-monitor-action-menu__item run-monitor-action-menu__item--danger" : "run-monitor-action-menu__item"}
              disabled={loadingAction === action.action}
              key={action.action}
              onClick={(event) => {
                event.stopPropagation();
                setOpen(false);
                onAction({
                  action: action.action,
                  signal_id: signalId,
                  task_run_id: signal.task_run_id,
                  graph_run_id: signal.graph_run_id || signal.graph_ref?.graph_run_id || "",
                });
              }}
              role="menuitem"
              type="button"
            >
              {loadingAction === action.action ? "处理中" : action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
