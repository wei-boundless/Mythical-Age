export type VSCodeEditorFile = {
  path?: string;
  label?: string;
  language_id?: string;
  dirty?: boolean;
  active?: boolean;
  visible?: boolean;
};

export type VSCodeConnectionStatus = {
  session_id: string;
  status: "connected" | "stale" | "disconnected" | string;
  connected: boolean;
  stale: boolean;
  last_seen_at: number;
  age_seconds?: number;
  stale_after_seconds?: number;
  workspace_root: string;
  project_key?: string;
  active_file?: VSCodeEditorFile;
  visible_files?: VSCodeEditorFile[];
  open_tabs?: VSCodeEditorFile[];
  limits?: {
    visible_files_count?: number;
    open_tabs_count?: number;
    diagnostics_count?: number;
    [key: string]: unknown;
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
