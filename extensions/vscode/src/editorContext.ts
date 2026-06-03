import * as vscode from "vscode";

const SELECTED_TEXT_LIMIT = 8000;
const VISIBLE_FILES_LIMIT = 20;
const DIAGNOSTICS_LIMIT = 50;
const WORKSPACE_ROOTS_LIMIT = 8;

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
    language_id: string;
    dirty: boolean;
    selection?: EditorRange & {
      text?: string;
      truncated: boolean;
    };
    visible_ranges?: EditorRange[];
  };
  visible_files: Array<{
    path: string;
    language_id: string;
    dirty: boolean;
  }>;
  diagnostics: Array<{
    path: string;
    severity: "error" | "warning" | "information" | "hint";
    message: string;
    range: EditorRange;
  }>;
  limits: {
    selected_text_chars: number;
    diagnostics_count: number;
    visible_files_count: number;
  };
};

export function collectEditorContext(): EditorContextSnapshot {
  const activeEditor = vscode.window.activeTextEditor;
  const visibleEditors = vscode.window.visibleTextEditors.slice(0, VISIBLE_FILES_LIMIT);
  const activeFile = activeEditor ? activeFileSnapshot(activeEditor) : undefined;
  const diagnostics = collectDiagnostics();
  return {
    source: "vscode",
    captured_at: new Date().toISOString(),
    workspace_roots: (vscode.workspace.workspaceFolders || [])
      .slice(0, WORKSPACE_ROOTS_LIMIT)
      .map((folder) => folder.uri.fsPath),
    active_file: activeFile,
    visible_files: visibleEditors.map((editor) => ({
      path: documentPath(editor.document),
      language_id: editor.document.languageId,
      dirty: editor.document.isDirty
    })),
    diagnostics,
    limits: {
      selected_text_chars: activeFile?.selection?.text?.length || 0,
      diagnostics_count: diagnostics.length,
      visible_files_count: visibleEditors.length
    }
  };
}

function activeFileSnapshot(editor: vscode.TextEditor): NonNullable<EditorContextSnapshot["active_file"]> {
  const selectionText = editor.document.getText(editor.selection);
  const truncated = selectionText.length > SELECTED_TEXT_LIMIT;
  return {
    path: documentPath(editor.document),
    language_id: editor.document.languageId,
    dirty: editor.document.isDirty,
    selection: {
      start: position(editor.selection.start),
      end: position(editor.selection.end),
      text: selectionText.slice(0, SELECTED_TEXT_LIMIT),
      truncated
    },
    visible_ranges: editor.visibleRanges.map(range).slice(0, 8)
  };
}

function collectDiagnostics(): EditorContextSnapshot["diagnostics"] {
  const result: EditorContextSnapshot["diagnostics"] = [];
  for (const [uri, diagnostics] of vscode.languages.getDiagnostics()) {
    for (const diagnostic of diagnostics) {
      if (result.length >= DIAGNOSTICS_LIMIT) {
        return result;
      }
      result.push({
        path: uri.fsPath || uri.toString(),
        severity: severity(diagnostic.severity),
        message: diagnostic.message,
        range: range(diagnostic.range)
      });
    }
  }
  return result;
}

function documentPath(document: vscode.TextDocument): string {
  return document.uri.fsPath || document.uri.toString();
}

function position(value: vscode.Position): EditorPosition {
  return {
    line: value.line,
    character: value.character
  };
}

function range(value: vscode.Range): EditorRange {
  return {
    start: position(value.start),
    end: position(value.end)
  };
}

function severity(value: vscode.DiagnosticSeverity): "error" | "warning" | "information" | "hint" {
  switch (value) {
    case vscode.DiagnosticSeverity.Error:
      return "error";
    case vscode.DiagnosticSeverity.Warning:
      return "warning";
    case vscode.DiagnosticSeverity.Information:
      return "information";
    case vscode.DiagnosticSeverity.Hint:
      return "hint";
    default:
      return "information";
  }
}
