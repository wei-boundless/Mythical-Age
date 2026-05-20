import { taskSystemOptionLabel } from "./TaskSystemWorkbenchUi";

export type RuntimeSupportStatus = "supported" | "partial" | "unsupported";

export const RUNTIME_SUPPORT_LABELS: Record<RuntimeSupportStatus, string> = {
  supported: "运行支持",
  partial: "预览",
  unsupported: "未支持",
};

const TEMPORAL_SUPPORT: Record<string, Record<string, RuntimeSupportStatus>> = {
  trigger_timing: {
    after_source_success: "supported",
    after_source_commit: "supported",
    after_required_contracts: "partial",
    manual_release: "unsupported",
    phase_entry: "unsupported",
    phase_exit: "unsupported",
    phase_gate_passed: "unsupported",
  },
  visibility_timing: {
    after_commit: "supported",
    next_clock: "supported",
    same_clock: "partial",
    after_ack: "partial",
    next_iteration: "unsupported",
    manual_release: "unsupported",
  },
  acknowledgement_timing: {
    explicit_ack: "supported",
    ack_before_downstream: "supported",
    before_downstream_ready: "supported",
    no_ack: "supported",
    none: "supported",
    implicit_ack: "supported",
    manual_ack: "partial",
    ack_before_phase_exit: "partial",
  },
  propagation_timing: {
    buffer_until_commit: "supported",
    blocked_on_failure: "supported",
    refs_only: "partial",
    immediate_refs_only: "partial",
    summary_only: "partial",
    immediate: "partial",
    manual_release: "partial",
    block_until_ack: "partial",
  },
  phase_timing: {
    within_phase: "partial",
    cross_phase_handoff: "partial",
    blocks_phase_exit: "partial",
    revision_return: "partial",
    non_blocking_feedback: "partial",
  },
  dependency_gate: {
    handoff_ack: "supported",
  },
};

const EDGE_POLICY_SUPPORT: Record<string, Record<string, RuntimeSupportStatus>> = {
  wait_policy: {
    wait_all_upstream_completed: "partial",
    wait_any_upstream_completed: "partial",
    wait_required_contracts: "partial",
    wait_handoff_ack: "supported",
    fire_and_continue: "unsupported",
    manual_release: "unsupported",
  },
  ack_policy: {
    explicit_ack: "supported",
    implicit_ack: "partial",
    manual_ack: "partial",
    none: "partial",
  },
  failure_propagation_policy: {
    fail_downstream: "supported",
    isolate_failure: "supported",
    allow_partial: "supported",
    coordinator_decides: "supported",
  },
  result_delivery_policy: {
    contract_payload_and_refs: "supported",
    summary_and_refs: "partial",
    notification_only: "partial",
  },
};

export function runtimeSupportFor(field: string, value: string): RuntimeSupportStatus {
  if (field === "phase_timing") {
    return TEMPORAL_SUPPORT.phase_timing[value] ?? "partial";
  }
  if (field === "dependency_gate") {
    return TEMPORAL_SUPPORT.dependency_gate[value] ?? "partial";
  }
  return TEMPORAL_SUPPORT[field]?.[value] ?? EDGE_POLICY_SUPPORT[field]?.[value] ?? "unsupported";
}

export function formatRuntimeSupportOption(field: string) {
  return (value: string) => {
    const status = runtimeSupportFor(field, value);
    return `${taskSystemOptionLabel(value)} · ${RUNTIME_SUPPORT_LABELS[status]}`;
  };
}

export function runtimeOptionIsUnsupported(field: string, value: string) {
  return runtimeSupportFor(field, value) === "unsupported";
}
