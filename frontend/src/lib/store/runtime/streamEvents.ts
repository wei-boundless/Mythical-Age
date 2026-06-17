import { runtimeText } from "./text";

export function streamEventStopsActiveWork(event: string, data: Record<string, unknown>) {
  const eventName = runtimeText(event).toLowerCase();
  const terminalReason = runtimeText(data.terminal_reason).toLowerCase();
  const completionState = runtimeText(data.completion_state).toLowerCase();
  const status = runtimeText(data.status).toLowerCase();
  const state = runtimeText(data.state).toLowerCase();
  const phase = runtimeText(data.phase).toLowerCase();
  const stopValues = ["stop_active_work", "conversation_stop", "user_stopped", "stopped", "aborted", "cancelled", "canceled"];
  if (stopValues.includes(terminalReason) || stopValues.includes(completionState)) {
    return true;
  }
  if (eventName === "stopped") {
    return true;
  }
  if (eventName === "turn_completed" && stopValues.includes(status)) {
    return true;
  }
  return eventName === "runtime_status" && phase === "work_control" && stopValues.includes(state);
}
