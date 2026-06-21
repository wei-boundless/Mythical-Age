export type EditorPosition = {
  line: number;
  character: number;
};

export type EditorRange = {
  start: EditorPosition;
  end: EditorPosition;
};

export type EditorContextSnapshot = {
  source: "vscode";
  captured_at: string;
  workspace_roots: string[];
  active_file?: {
    path: string;
    label: string;
    language_id: string;
    dirty: boolean;
    selection?: EditorRange & {
      text?: string;
      truncated: boolean;
    };
    content_preview?: {
      text: string;
      truncated: boolean;
      source: "dirty_buffer" | "saved_document";
    };
    visible_ranges?: EditorRange[];
  };
  visible_files: Array<{
    path: string;
    label: string;
    language_id: string;
    dirty: boolean;
  }>;
  open_tabs: Array<{
    path: string;
    label: string;
    language_id: string;
    dirty: boolean;
    active: boolean;
    visible: boolean;
  }>;
  diagnostics: Array<{
    path: string;
    severity: "error" | "warning" | "information" | "hint";
    message: string;
    range: EditorRange;
  }>;
  limits: {
    selected_text_chars: number;
    content_preview_chars: number;
    diagnostics_count: number;
    visible_files_count: number;
    open_tabs_count: number;
  };
};

export type ProjectBindingPayload = {
  workspace_root: string;
  source: "vscode";
};

export type SessionResponse = {
  id: string;
  title?: string;
};

export type ChatRunResponse = {
  stream_run_id?: string;
  stream_url?: string;
  status?: string;
};

export type VSCodeConnectionLease = {
  session_id: string;
  workspace_root: string;
  project_key: string;
  connection_id: string;
  acquired_at: number;
  last_heartbeat_at: number;
  expires_at: number;
  source?: string;
  client_name?: string;
  duplicate_rejected_count?: number;
  authority?: string;
};

export type VSCodeConnectionAcquireResponse = {
  ok: boolean;
  lease: VSCodeConnectionLease;
  connection_status?: Record<string, unknown>;
  authority?: string;
};

export type VSCodeCommand = {
  command_id?: string;
  type?: "open_diff" | "open_file" | string;
  left_uri?: string;
  right_uri?: string;
  uri?: string;
  logical_path?: string;
  title?: string;
  record_id?: string;
  request_session_id?: string;
  target?: Record<string, unknown>;
};

export type VSCodeCommandPollResponse = {
  session_id: string;
  status: "ok" | "empty" | string;
  command?: VSCodeCommand | null;
  commands?: VSCodeCommand[];
  retry_after_ms?: number;
  poll_reason?: string;
};

export type VSCodeCommandResultPayload = {
  status: "ok" | "error" | "unsupported" | string;
  message?: string;
  dirty?: boolean;
  document_sha256?: string;
  applied_at?: string;
  metadata?: Record<string, unknown>;
};
