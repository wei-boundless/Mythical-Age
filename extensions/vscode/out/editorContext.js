"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.collectEditorContext = collectEditorContext;
const vscode = __importStar(require("vscode"));
const SELECTED_TEXT_LIMIT = 8000;
const VISIBLE_FILES_LIMIT = 20;
const DIAGNOSTICS_LIMIT = 50;
const WORKSPACE_ROOTS_LIMIT = 8;
function collectEditorContext() {
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
function activeFileSnapshot(editor) {
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
function collectDiagnostics() {
    const result = [];
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
function documentPath(document) {
    return document.uri.fsPath || document.uri.toString();
}
function position(value) {
    return {
        line: value.line,
        character: value.character
    };
}
function range(value) {
    return {
        start: position(value.start),
        end: position(value.end)
    };
}
function severity(value) {
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
//# sourceMappingURL=editorContext.js.map