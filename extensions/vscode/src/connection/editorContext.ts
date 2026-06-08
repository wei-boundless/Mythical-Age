import * as vscode from "vscode";
import type { EditorContextSnapshot, EditorPosition, EditorRange } from "./types";

const SELECTED_TEXT_LIMIT = 8000;
const ACTIVE_CONTENT_PREVIEW_LIMIT = 24000;
const VISIBLE_FILES_LIMIT = 20;
const DIAGNOSTICS_LIMIT = 50;
const WORKSPACE_ROOTS_LIMIT = 8;

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
      content_preview_chars: activeFile?.content_preview?.text.length || 0,
      diagnostics_count: diagnostics.length,
      visible_files_count: visibleEditors.length
    }
  };
}

function activeFileSnapshot(editor: vscode.TextEditor): NonNullable<EditorContextSnapshot["active_file"]> {
  const selectionText = editor.document.getText(editor.selection);
  const selectedTextTruncated = selectionText.length > SELECTED_TEXT_LIMIT;
  const documentText = editor.document.getText();
  const previewTruncated = documentText.length > ACTIVE_CONTENT_PREVIEW_LIMIT;
  return {
    path: documentPath(editor.document),
    language_id: editor.document.languageId,
    dirty: editor.document.isDirty,
    selection: {
      start: position(editor.selection.start),
      end: position(editor.selection.end),
      text: selectionText.slice(0, SELECTED_TEXT_LIMIT),
      truncated: selectedTextTruncated
    },
    content_preview: {
      text: documentText.slice(0, ACTIVE_CONTENT_PREVIEW_LIMIT),
      truncated: previewTruncated,
      source: editor.document.isDirty ? "dirty_buffer" : "saved_document"
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
