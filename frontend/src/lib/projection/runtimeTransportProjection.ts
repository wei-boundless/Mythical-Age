import type { RuntimeProgressEntry, SessionActivityLevel } from "@/lib/store/types";

export type RuntimeTransportProjection = {
  stageStatus?: string;
  activityTitle?: string;
  activityDetail?: string;
  level?: SessionActivityLevel;
  progressEntry?: RuntimeProgressEntry;
  terminalEvent?: "done" | "error" | "stopped";
};

export function projectRuntimeTransportEvent(_event?: string, _data?: Record<string, unknown>): RuntimeTransportProjection {
  return {};
}
