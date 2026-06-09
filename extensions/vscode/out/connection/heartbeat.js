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
exports.startContextHeartbeat = startContextHeartbeat;
const vscode = __importStar(require("vscode"));
const apiClient_1 = require("./apiClient");
const editorContext_1 = require("./editorContext");
const sessionBinding_1 = require("./sessionBinding");
const HEARTBEAT_INTERVAL_MS = 15000;
const DEBOUNCE_MS = 800;
function startContextHeartbeat(context, output) {
    let disposed = false;
    let debounceTimer;
    const interval = setInterval(() => schedulePublish(), HEARTBEAT_INTERVAL_MS);
    const subscriptions = [
        vscode.window.onDidChangeActiveTextEditor(() => schedulePublish()),
        vscode.window.onDidChangeVisibleTextEditors(() => schedulePublish()),
        vscode.window.onDidChangeTextEditorSelection(() => schedulePublish()),
        vscode.workspace.onDidChangeTextDocument(() => schedulePublish()),
        vscode.languages.onDidChangeDiagnostics(() => schedulePublish())
    ];
    function schedulePublish() {
        if (disposed) {
            return;
        }
        if (debounceTimer) {
            clearTimeout(debounceTimer);
        }
        debounceTimer = setTimeout(() => {
            void publishContext();
        }, DEBOUNCE_MS);
    }
    async function publishContext() {
        if (disposed) {
            return;
        }
        try {
            const snapshot = (0, editorContext_1.collectEditorContext)();
            const sessionId = await (0, sessionBinding_1.resolveSessionId)(context, snapshot, { createIfMissing: false });
            if (!sessionId) {
                return;
            }
            await (0, apiClient_1.postEditorContext)(sessionId, snapshot);
        }
        catch (error) {
            const text = error instanceof Error ? error.message : String(error);
            output.appendLine(text);
        }
    }
    schedulePublish();
    return new vscode.Disposable(() => {
        disposed = true;
        clearInterval(interval);
        if (debounceTimer) {
            clearTimeout(debounceTimer);
        }
        for (const subscription of subscriptions) {
            subscription.dispose();
        }
    });
}
//# sourceMappingURL=heartbeat.js.map