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

export type VSCodeCommand = {
  command_id?: string;
  type?: string;
  left_uri?: string;
  right_uri?: string;
  title?: string;
  record_id?: string;
};

export type VSCodeCommandPollResponse = {
  session_id: string;
  status: "ok" | "empty" | string;
  command?: VSCodeCommand | null;
  commands?: VSCodeCommand[];
};
