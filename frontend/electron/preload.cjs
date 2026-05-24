const { contextBridge } = require("electron");

const config = {
  apiBase: process.env.MYTHICAL_AGENT_API_BASE || "http://127.0.0.1:8003/api",
  frontendUrl: process.env.MYTHICAL_AGENT_FRONTEND_URL || "http://127.0.0.1:3000/",
  backendHealthUrl: process.env.MYTHICAL_AGENT_BACKEND_HEALTH_URL || "http://127.0.0.1:8003/health",
  frontendPort: Number(process.env.MYTHICAL_AGENT_FRONTEND_PORT || 3000),
  backendPort: Number(process.env.MYTHICAL_AGENT_BACKEND_PORT || 8003),
  mode: "dev",
  hostMode: "desktop",
  localRuntimeAvailable: true,
  codeEnvironmentHostAvailable: true,
};

globalThis.__MYTHICAL_AGENT_HOST__ = config;

contextBridge.exposeInMainWorld("mythicalAgentHost", {
  getConfig: () => ({ ...config }),
});
