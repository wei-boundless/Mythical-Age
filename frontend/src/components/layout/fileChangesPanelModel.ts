import type { FileChangeRecord } from "@/lib/api";

type TaskRunRef = {
  task_run_id?: string;
  latest_task_run_id?: string;
};

type SessionTaskRef = {
  active_task?: TaskRunRef;
  task_binding?: TaskRunRef;
};

type MessageTaskRef = {
  sourceTaskRunId?: string;
  runtimeProgress?: Array<{ taskRunId?: string }>;
};

type ActiveTurnTaskRef = {
  task_run_id?: string;
};

export type FileChangeRecordPartition = {
  conversationRecords: FileChangeRecord[];
  otherTaskRecords: FileChangeRecord[];
};

export function textValue(value: unknown) {
  return String(value ?? "").trim();
}

export function collectCurrentConversationTaskRunIds(input: {
  activeTurnSnapshot?: ActiveTurnTaskRef | null;
  currentSession?: SessionTaskRef | null;
  messages?: MessageTaskRef[];
}) {
  const ids = new Set<string>();
  const add = (value: unknown) => {
    const text = textValue(value);
    if (text) ids.add(text);
  };

  add(input.activeTurnSnapshot?.task_run_id);
  add(input.currentSession?.active_task?.task_run_id);
  add(input.currentSession?.active_task?.latest_task_run_id);
  add(input.currentSession?.task_binding?.task_run_id);

  for (const message of input.messages ?? []) {
    add(message.sourceTaskRunId);
    for (const progress of message.runtimeProgress ?? []) {
      add(progress.taskRunId);
    }
  }

  return ids;
}

export function partitionFileChangeRecords(
  records: FileChangeRecord[],
  currentConversationTaskRunIds: Set<string>,
): FileChangeRecordPartition {
  const conversationRecords: FileChangeRecord[] = [];
  const otherTaskRecords: FileChangeRecord[] = [];

  for (const record of records) {
    const taskRunId = textValue(record.task_run_id);
    if (!taskRunId || currentConversationTaskRunIds.has(taskRunId)) {
      conversationRecords.push(record);
    } else {
      otherTaskRecords.push(record);
    }
  }

  return { conversationRecords, otherTaskRecords };
}
