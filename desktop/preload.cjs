const { contextBridge } = require("electron");

/**
 * 渲染进程可见的宿主能力。
 *
 * 前端 `getApiBase()` 优先读取这里的 apiBase，其次才回退到构建期注入的地址。
 * 桌面版两条路径指向同一个固定节点，保持一致以免出现两个真相源。
 */

const config = {
  apiBase: process.env.MYTHICAL_AGENT_API_BASE || "http://127.0.0.1:8003/api",
  frontendUrl: process.env.MYTHICAL_AGENT_FRONTEND_URL || "http://127.0.0.1:3000/",
  backendHealthUrl: process.env.MYTHICAL_AGENT_BACKEND_HEALTH_URL || "http://127.0.0.1:8003/health",
  frontendPort: Number(process.env.MYTHICAL_AGENT_FRONTEND_PORT || 3000),
  backendPort: Number(process.env.MYTHICAL_AGENT_BACKEND_PORT || 8003),
  mode: "desktop",
  hostMode: "desktop",
  localRuntimeAvailable: true,
  codeEnvironmentHostAvailable: true,
};

globalThis.__MYTHICAL_AGENT_HOST__ = config;

contextBridge.exposeInMainWorld("mythicalAgentHost", {
  getConfig: () => ({ ...config }),
});
