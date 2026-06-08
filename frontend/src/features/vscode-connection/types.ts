export type VSCodeConnectionStatus = {
  session_id: string;
  status: "connected" | "stale" | "disconnected" | string;
  connected: boolean;
  stale: boolean;
  last_seen_at: number;
  workspace_root: string;
  project_key?: string;
  active_file?: {
    path?: string;
    language_id?: string;
    dirty?: boolean;
  };
  connection_session_id?: string;
  connection_id?: string;
  reused_project_connection?: boolean;
  authority?: string;
};

export type OpenSessionProjectInVSCodeResponse = {
  ok: boolean;
  project_binding?: {
    workspace_root?: string;
    source?: string;
  };
  command?: string[];
  window_mode?: string;
  connection_reused?: boolean;
  connection_status?: VSCodeConnectionStatus;
  session_id?: string;
};
