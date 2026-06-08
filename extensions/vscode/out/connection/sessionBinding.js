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
exports.resolveSessionId = resolveSessionId;
const vscode = __importStar(require("vscode"));
const apiClient_1 = require("./apiClient");
const SESSION_STATE_KEY = "langchainAgent.sessionId";
async function resolveSessionId(context, editorContext, options) {
    const configured = (0, apiClient_1.configuredSessionId)();
    if (configured) {
        await context.workspaceState.update(SESSION_STATE_KEY, configured);
        return configured;
    }
    const launchSession = await (0, apiClient_1.resolveLaunchSession)(editorContext.workspace_roots);
    if (launchSession && await (0, apiClient_1.sessionExists)(launchSession)) {
        await context.workspaceState.update(SESSION_STATE_KEY, launchSession);
        return launchSession;
    }
    const stored = context.workspaceState.get(SESSION_STATE_KEY) || "";
    if (stored && await (0, apiClient_1.sessionExists)(stored)) {
        return stored;
    }
    if (stored) {
        await context.workspaceState.update(SESSION_STATE_KEY, undefined);
    }
    if (!options.createIfMissing) {
        return "";
    }
    const projectBinding = await projectBindingFromEditorContext(editorContext);
    const created = await (0, apiClient_1.createSession)("VS Code Agent Session", projectBinding);
    await context.workspaceState.update(SESSION_STATE_KEY, created.id);
    return created.id;
}
async function projectBindingFromEditorContext(editorContext) {
    const roots = Array.from(new Set(editorContext.workspace_roots.map((item) => item.trim()).filter(Boolean)));
    if (roots.length === 0) {
        return undefined;
    }
    if (roots.length === 1) {
        return { workspace_root: roots[0], source: "vscode" };
    }
    const selected = await vscode.window.showQuickPick(roots, {
        title: "Bind Langchain Agent Session",
        placeHolder: "Select the project root for this local agent session.",
        ignoreFocusOut: true
    });
    if (!selected) {
        throw new Error("A project root must be selected before creating a VS Code agent session.");
    }
    return { workspace_root: selected, source: "vscode" };
}
//# sourceMappingURL=sessionBinding.js.map