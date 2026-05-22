const { contextBridge } = require("electron");

const config = {
  apiBase: process.env.MYTHICAL_AGENT_API_BASE || "http://127.0.0.1:8002/api",
  frontendUrl: process.env.MYTHICAL_AGENT_FRONTEND_URL || "http://127.0.0.1:3000/",
  backendHealthUrl: process.env.MYTHICAL_AGENT_BACKEND_HEALTH_URL || "http://127.0.0.1:8002/health",
  frontendPort: Number(process.env.MYTHICAL_AGENT_FRONTEND_PORT || 3000),
  backendPort: Number(process.env.MYTHICAL_AGENT_BACKEND_PORT || 8002),
  mode: "dev",
};

globalThis.__MYTHICAL_AGENT_HOST__ = config;

contextBridge.exposeInMainWorld("mythicalAgentHost", {
  getConfig: () => ({ ...config }),
});
