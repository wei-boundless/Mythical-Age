import { describe, expect, it } from "vitest";

import type { HealthSystemOverview, HealthTaskRecordMaintenance } from "@/lib/api";

import { buildHealthSystemViewModel } from "./healthSelectors";

const baseTask = {
  task_run_id: "taskrun:1",
  session_id: "session-abcdef",
  task_contract_ref: "",
  title: "",
  task_id: "",
  agent_id: "",
  agent_profile_id: "",
  runtime_lane: "",
  status: "completed",
  terminal_reason: "",
  created_at: 10,
  updated_at: 10,
  duration_seconds: 2,
  agent_count: 1,
  worker_request_count: 0,
  worker_result_count: 0,
  tool_call_count: 0,
  event_count: 1,
  error_count: 0,
  token_total: 10,
  risk_level: "normal",
  latest_risk_event: "",
  supervision_count: 0,
  latest_event_type: "completed",
  monitor_ref: "",
  record_refs: {},
};

function overviewFixture(): HealthSystemOverview {
  return {
    authority: "health-system",
    summary: {
      task_count: 2,
      running_task_count: 0,
      high_risk_count: 1,
      critical_risk_count: 0,
      token_total: 300,
    },
    tasks: [
      { ...baseTask, task_run_id: "taskrun:normal", updated_at: 20, risk_level: "normal" },
      { ...baseTask, task_run_id: "taskrun:high", updated_at: 10, risk_level: "high" },
    ],
    risks: [],
    system_risks: [],
    token_usage: {
      authority: "health-system",
      summary: {
        exact_total_tokens: 200,
        week_total_tokens: 200,
        overall_total_tokens: 300,
        predicted_total_tokens: 260,
        trace_estimate_total_tokens: 40,
        cache_savings_tokens: 50,
        cached_tokens: 20,
        provider_usage_task_count: 1,
        prediction_only_task_count: 1,
        trace_estimate_task_count: 0,
        record_count: 3,
      },
      sessions: [],
      tasks: [],
      daily: [{ bucket: "2026-05-30", tokens: 200 }],
      updated_at: 1,
    },
    efficiency: {
      authority: "health-system",
      summary: { task_count: 2, average_duration_seconds: 3, slow_task_count: 0 },
      tasks: [],
      updated_at: 1,
    },
    recommendations: [],
    monitor: {
      revision: "monitor-revision",
      summary: { running: 9, stale: 1 },
    },
    monitor_governance: {
      authority: "health-system",
      monitor_authority: "runtime-monitor",
      revision: "governance-revision",
      status: "healthy",
      summary: { running: 1, action_required: 2 },
      risk_escalations: [],
      recommended_actions: [],
      updated_at: 1,
    },
    updated_at: 1,
  };
}

describe("buildHealthSystemViewModel", () => {
  it("sorts task records by health risk and falls back to the highest risk task", () => {
    const view = buildHealthSystemViewModel(overviewFixture(), null, "");

    expect(view.tasks.map((task) => task.task_run_id)).toEqual(["taskrun:high", "taskrun:normal"]);
    expect(view.selectedTask?.task_run_id).toBe("taskrun:high");
  });

  it("derives monitor facts from health governance before raw monitor fallback", () => {
    const view = buildHealthSystemViewModel(overviewFixture(), null, "");

    expect(view.monitorRevision).toBe("governance-revision");
    expect(view.monitorSummary).toMatchObject({ running: 1, action_required: 2 });
  });

  it("builds token chart and accounting structure without mixing token sources", () => {
    const view = buildHealthSystemViewModel(overviewFixture(), null, "");

    expect(view.activeTokenBuckets).toHaveLength(1);
    expect(view.maxActiveTokenBucket).toBe(200);
    expect(view.weeklyTokenTotal).toBe(200);
    expect(view.overallTokenTotal).toBe(300);
    expect(view.predictionDelta).toBe(60);
    expect(view.providerCoverage).toBeCloseTo(1 / 3);
    expect(view.providerCoverageCaption).toBe("1 / 3 个运行记录已有 provider usage");
    expect(view.missingTokenTaskCount).toBe(1);
    expect(view.sourceStructureTotal).toBe(3);
  });

  it("separates maintenance candidates from protected records", () => {
    const maintenance: HealthTaskRecordMaintenance = {
      authority: "health-system",
      mode: "preflight",
      bucket: "static",
      requested_task_run_ids: [],
      policy: {},
      summary: { candidate_count: 2, eligible_count: 1, protected_count: 1 },
      candidates: [
        { task_run_id: "taskrun:old", eligible: true },
        { task_run_id: "taskrun:running", eligible: false, protection_reasons: ["running"] },
      ],
      recent_receipts: [],
      updated_at: 1,
    };

    const view = buildHealthSystemViewModel(overviewFixture(), maintenance, "");

    expect(view.maintenanceCandidates).toHaveLength(2);
    expect(view.protectedMaintenanceCandidates).toEqual([
      { task_run_id: "taskrun:running", eligible: false, protection_reasons: ["running"] },
    ]);
  });
});
