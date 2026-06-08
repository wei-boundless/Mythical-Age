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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const apiClient_1 = require("./connection/apiClient");
const editorContext_1 = require("./connection/editorContext");
const heartbeat_1 = require("./connection/heartbeat");
const sessionBinding_1 = require("./connection/sessionBinding");
let output;
function activate(context) {
    output = vscode.window.createOutputChannel("Langchain Agent");
    context.subscriptions.push(output);
    context.subscriptions.push((0, heartbeat_1.startContextHeartbeat)(context, output));
    context.subscriptions.push(vscode.commands.registerCommand("langchainAgent.sendToAgent", () => sendCurrentContext(context)), vscode.commands.registerCommand("langchainAgent.showEditorContext", showEditorContext));
}
function deactivate() {
    output?.dispose();
    output = undefined;
}
async function sendCurrentContext(context) {
    const message = await vscode.window.showInputBox({
        title: "Send to Langchain Agent",
        prompt: "Enter the instruction to send with the current VS Code context.",
        ignoreFocusOut: true
    });
    if (!message?.trim()) {
        return;
    }
    const editorContext = (0, editorContext_1.collectEditorContext)();
    const sessionId = await (0, sessionBinding_1.resolveSessionId)(context, editorContext, { createIfMissing: true });
    output?.show(true);
    output?.appendLine(`Sending request to local agent session ${sessionId}.`);
    try {
        await (0, apiClient_1.postEditorContext)(sessionId, editorContext);
        const run = await (0, apiClient_1.createChatRun)({
            message: message.trim(),
            session_id: sessionId,
            stream: true,
            editor_context: editorContext
        });
        output?.appendLine(`Created chat run: ${run.stream_run_id || "(unknown)"}`);
        if (run.stream_url) {
            output?.appendLine(`Stream URL: ${run.stream_url}`);
        }
        vscode.window.showInformationMessage("Langchain Agent request created.");
    }
    catch (error) {
        const text = error instanceof Error ? error.message : String(error);
        output?.appendLine(text);
        vscode.window.showErrorMessage(text);
    }
}
async function showEditorContext() {
    const snapshot = (0, editorContext_1.collectEditorContext)();
    const document = await vscode.workspace.openTextDocument({
        language: "json",
        content: JSON.stringify(snapshot, null, 2)
    });
    await vscode.window.showTextDocument(document, { preview: true });
}
//# sourceMappingURL=extension.js.map