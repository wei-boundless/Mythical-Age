import { describe, expect, it } from "vitest";

import type { FileChangeRecord } from "@/lib/api";
import {
  collectCurrentConversationTaskRunIds,
  partitionFileChangeRecords,
} from "./fileChangesPanelModel";

function change(patch: Partial<FileChangeRecord>): FileChangeRecord {
  return {
    absolute_path: "",
    after_exists: true,
    after_sha256: "",
    after_snapshot_path: "",
    agent_run_id: "",
    before_exists: true,
    before_sha256: "",
    before_snapshot_path: "",
    created_at: 1,
    logical_path: "src/file.ts",
    operation_id: "",
    record_id: "filechange-test",
    session_id: "session:test",
    status: "active",
    task_run_id: "",
    tool_call_id: "",
    tool_name: "",
    workspace_root: "",
    ...patch,
  };
}

describe("fileChangesPanelModel", () => {
  it("keeps direct conversation changes in the primary scope", () => {
    const records = [
      change({ record_id: "filechange-direct", task_run_id: "" }),
      change({ record_id: "filechange-task", task_run_id: "taskrun:other" }),
    ];

    const partition = partitionFileChangeRecords(records, new Set());

    expect(partition.conversationRecords.map((record) => record.record_id)).toEqual(["filechange-direct"]);
    expect(partition.otherTaskRecords.map((record) => record.record_id)).toEqual(["filechange-task"]);
  });

  it("keeps changes from the active conversation task in the primary scope", () => {
    const records = [
      change({ record_id: "filechange-current", task_run_id: "taskrun:current" }),
      change({ record_id: "filechange-other", task_run_id: "taskrun:other" }),
    ];

    const partition = partitionFileChangeRecords(records, new Set(["taskrun:current"]));

    expect(partition.conversationRecords.map((record) => record.record_id)).toEqual(["filechange-current"]);
    expect(partition.otherTaskRecords.map((record) => record.record_id)).toEqual(["filechange-other"]);
  });

  it("collects task run ids from session, active turn, and visible conversation messages", () => {
    const ids = collectCurrentConversationTaskRunIds({
      activeTurnSnapshot: { task_run_id: "taskrun:active" },
      currentSession: {
        active_task: { task_run_id: "taskrun:session", latest_task_run_id: "taskrun:latest" },
        task_binding: { task_run_id: "taskrun:binding" },
      },
      messages: [
        {
          sourceTaskRunId: "taskrun:message",
          runtimeProgress: [{ taskRunId: "taskrun:progress" }],
        },
      ],
    });

    expect(Array.from(ids).sort()).toEqual([
      "taskrun:active",
      "taskrun:binding",
      "taskrun:latest",
      "taskrun:message",
      "taskrun:progress",
      "taskrun:session",
    ]);
  });
});
