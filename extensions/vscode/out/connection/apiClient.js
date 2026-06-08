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
exports.createChatRun = createChatRun;
exports.postEditorContext = postEditorContext;
exports.configuredSessionId = configuredSessionId;
exports.createSession = createSession;
exports.sessionExists = sessionExists;
exports.resolveLaunchSession = resolveLaunchSession;
const vscode = __importStar(require("vscode"));
async function createChatRun(payload) {
    const apiBase = normalizedApiBase();
    const response = await fetch(`${apiBase}/chat/runs`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });
    if (!response.ok) {
        const text = await response.text().catch(() => "");
        throw new Error(`Local agent request failed: ${response.status} ${text}`.trim());
    }
    return (await response.json());
}
async function postEditorContext(sessionId, snapshot) {
    const apiBase = normalizedApiBase();
    const response = await fetch(`${apiBase}/vscode/sessions/${encodeURIComponent(sessionId)}/context`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(snapshot)
    });
    if (!response.ok) {
        const text = await response.text().catch(() => "");
        throw new Error(`VS Code context update failed: ${response.status} ${text}`.trim());
    }
}
function configuredSessionId() {
    const configured = vscode.workspace.getConfiguration("langchainAgent").get("sessionId");
    const fromConfig = sanitizeSessionId(configured || "");
    if (fromConfig) {
        return fromConfig;
    }
    return sanitizeSessionId(process.env.LANGCHAIN_AGENT_SESSION_ID || "");
}
async function createSession(title, projectBinding) {
    const apiBase = normalizedApiBase();
    const response = await fetch(`${apiBase}/sessions`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            title,
            scope: {
                workspace_view: "chat"
            },
            ...(projectBinding ? { project_binding: projectBinding } : {})
        })
    });
    if (!response.ok) {
        const text = await response.text().catch(() => "");
        throw new Error(`Session create failed: ${response.status} ${text}`.trim());
    }
    return (await response.json());
}
async function sessionExists(sessionId) {
    if (!sessionId) {
        return false;
    }
    const apiBase = normalizedApiBase();
    const response = await fetch(`${apiBase}/sessions/${encodeURIComponent(sessionId)}/history`, {
        method: "GET"
    });
    return response.ok;
}
async function resolveLaunchSession(workspaceRoots) {
    const apiBase = normalizedApiBase();
    const response = await fetch(`${apiBase}/vscode/sessions/resolve`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ workspace_roots: workspaceRoots })
    });
    if (!response.ok) {
        return "";
    }
    const payload = (await response.json());
    return sanitizeSessionId(payload.session_id || "");
}
function normalizedApiBase() {
    const configured = vscode.workspace.getConfiguration("langchainAgent").get("apiBase");
    const value = (configured || "http://127.0.0.1:8003/api").trim();
    return value.replace(/\/+$/, "");
}
function sanitizeSessionId(value) {
    return value.trim().replace(/[^a-zA-Z0-9:_-]/g, "-");
}
//# sourceMappingURL=apiClient.js.map