const { app, BrowserWindow, dialog, shell, Menu } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

/**
 * 桌面程序的运行器。
 *
 * 与源码仓库中的 `frontend/electron/main.cjs` 状态一致、职责不同：那边是开发期驱动器，
 * 拉起 `uvicorn --reload` 与 `npm run dev:next`；这里只启动随包附带的两个产物——
 * 打包后的后端可执行程序与 Next standalone 服务，端口固定为项目约定的 3000 / 8003。
 *
 * 程序以「electron.exe 改名 + resources/app 目录」的形式发布，`process.execPath` 即为
 * 安装目录下的 MythicalAge.exe。用户数据与日志落在稳定的用户目录，升级时不随安装目录移动。
 */

const FIXED_BACKEND_PORT = 8003;
const FIXED_FRONTEND_PORT = 3000;

const children = new Map();
let mainWindow = null;
let shuttingDown = false;
let quitting = false;
let backendReused = false;
let frontendReused = false;

// 可执行文件已改名为 MythicalAge.exe，产品名必须与之一致，否则用户目录会落到
// 默认的 electron 路径下，日志与数据散在别处。
app.setName("Mythical Age");

const hasInstanceLock = app.requestSingleInstanceLock();
if (!hasInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
}

const exeDir = path.dirname(process.execPath);
const resourcesRoot = path.join(exeDir, "resources");

const backendExe = path.join(resourcesRoot, "backend", "mythical-backend.exe");
const frontendRoot = path.join(resourcesRoot, "frontend");
const nodeExe = path.join(resourcesRoot, "runtime", "node.exe");

// 用户数据必须独立于安装目录，否则卸载或换安装路径会把会话、配置和运行记录一起带走。
// MYTHICAL_AGE_HOME 仅用于显式部署；默认使用稳定的 Windows 用户数据目录。
const stableUserDataRoot = path.join(
  process.env.APPDATA || path.join(process.env.USERPROFILE || exeDir, "AppData", "Roaming"),
  "MythicalAge",
);
const legacyUserDataRoot = path.join(exeDir, "userdata");
const portableRoot = process.env.MYTHICAL_AGE_HOME || stableUserDataRoot;

function migrateLegacyUserData() {
  if (process.env.MYTHICAL_AGE_HOME || portableRoot === legacyUserDataRoot) return;
  if (!fs.existsSync(legacyUserDataRoot) || fs.existsSync(portableRoot)) return;
  try {
    fs.mkdirSync(path.dirname(portableRoot), { recursive: true });
    fs.cpSync(legacyUserDataRoot, portableRoot, { recursive: true, errorOnExist: false });
    TRACE(`migrated legacy userdata from ${legacyUserDataRoot} to ${portableRoot}`);
  } catch (error) {
    TRACE(`legacy userdata migration failed: ${error?.stack || error}`);
  }
}

app.setPath("userData", portableRoot);
app.setPath("sessionData", path.join(portableRoot, "session"));

// `app.getPath` 在 ready 之前不可用，路径按需解析。
function userDataDir() {
  return app.getPath("userData");
}

function dataRoot() {
  return path.join(userDataDir(), "data");
}

function runtimeDir() {
  return path.join(userDataDir(), "runtime");
}

function ensureRuntimeDir() {
  fs.mkdirSync(runtimeDir(), { recursive: true });
}

function log(name, chunk) {
  try {
    ensureRuntimeDir();
    const fileName = name.endsWith(".log") ? name : `${name}.log`;
    fs.appendFileSync(path.join(runtimeDir(), fileName), chunk);
  } catch {
    // 日志写不进去时不让它反过来打断启动。
  }
}

const TRACE = (msg) => log("trace.log", `${new Date().toISOString()} ${msg}\n`);
TRACE("module loaded");
migrateLegacyUserData();

process.on("uncaughtException", (error) => {
  log("crash.log", `${new Date().toISOString()} uncaughtException\n${error?.stack || error}\n`);
});

process.on("unhandledRejection", (reason) => {
  log("crash.log", `${new Date().toISOString()} unhandledRejection\n${reason?.stack || reason}\n`);
});

function canConnect(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ port, host: "127.0.0.1" });
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => resolve(false));
    socket.setTimeout(450, () => {
      socket.destroy();
      resolve(false);
    });
  });
}

function canBind(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, "127.0.0.1");
  });
}

async function isPortFree(port) {
  if (await canConnect(port)) {
    return false;
  }
  return canBind(port);
}

function requestOk(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 400);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForUrl(url, label, timeoutMs = 90000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await requestOk(url)) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
  throw new Error(`${label} 未能在 ${Math.round(timeoutMs / 1000)} 秒内就绪：${url}\n\n日志目录：${runtimeDir()}`);
}

function spawnManaged(name, command, args, options) {
  ensureRuntimeDir();
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: { ...process.env, ...(options.env || {}) },
    shell: false,
    windowsHide: true,
  });
  children.set(name, child);
  child.stdout.on("data", (chunk) => log(`${name}.out`, chunk));
  child.stderr.on("data", (chunk) => log(`${name}.err`, chunk));
  child.on("exit", (code, signal) => {
    children.delete(name);
    log("host.out", `[${name}] exited code=${code} signal=${signal}\n`);
    if (!shuttingDown && !quitting) {
      dialog.showErrorBox(
        "服务意外退出",
        `${name} 进程已退出（code=${code}）。\n\n日志目录：${runtimeDir()}`
      );
    }
  });
  return child;
}

function stopChildren() {
  shuttingDown = true;
  for (const child of children.values()) {
    if (child.pid && !child.killed) {
      spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true });
    }
  }
  children.clear();
}

async function startBackend() {
  if (!(await isPortFree(FIXED_BACKEND_PORT))) {
    if (await requestOk(`http://127.0.0.1:${FIXED_BACKEND_PORT}/health`)) {
      backendReused = true;
      TRACE(`reusing healthy backend on ${FIXED_BACKEND_PORT}`);
      return;
    }
    throw new Error(`端口 ${FIXED_BACKEND_PORT} 已被占用，且占用进程不是可复用的 MythicalAge 后端。请关闭占用该端口的程序后重试。`);
  }
  if (!fs.existsSync(backendExe)) {
    throw new Error(`后端程序缺失：${backendExe}`);
  }
  spawnManaged("backend", backendExe, [], {
    cwd: path.dirname(backendExe),
    env: {
      MYTHICAL_AGE_BACKEND_HOST: "127.0.0.1",
      MYTHICAL_AGE_BACKEND_PORT: String(FIXED_BACKEND_PORT),
      MYTHICAL_AGE_DATA_DIR: dataRoot(),
    },
  });
  await waitForUrl(`http://127.0.0.1:${FIXED_BACKEND_PORT}/health`, "后端服务");
}

async function startFrontend() {
  if (!(await isPortFree(FIXED_FRONTEND_PORT))) {
    if (await requestOk(`http://127.0.0.1:${FIXED_FRONTEND_PORT}/`)) {
      frontendReused = true;
      TRACE(`reusing healthy frontend on ${FIXED_FRONTEND_PORT}`);
      return;
    }
    throw new Error(`端口 ${FIXED_FRONTEND_PORT} 已被占用，且占用进程不是可复用的 MythicalAge 前端。请关闭占用该端口的程序后重试。`);
  }
  const serverEntry = path.join(frontendRoot, "server.js");
  if (!fs.existsSync(serverEntry)) {
    throw new Error(`前端服务缺失：${serverEntry}`);
  }
  if (!fs.existsSync(nodeExe)) {
    throw new Error(`Node 运行时缺失：${nodeExe}`);
  }
  spawnManaged("frontend", nodeExe, [serverEntry], {
    cwd: frontendRoot,
    env: {
      NODE_ENV: "production",
      PORT: String(FIXED_FRONTEND_PORT),
      HOSTNAME: "127.0.0.1",
      API_PROXY_TARGET: `http://127.0.0.1:${FIXED_BACKEND_PORT}`,
    },
  });
  await waitForUrl(`http://127.0.0.1:${FIXED_FRONTEND_PORT}/`, "前端服务");
}

function createWindow() {
  process.env.MYTHICAL_AGENT_API_BASE = `http://127.0.0.1:${FIXED_BACKEND_PORT}/api`;
  process.env.MYTHICAL_AGENT_FRONTEND_URL = `http://127.0.0.1:${FIXED_FRONTEND_PORT}/`;
  process.env.MYTHICAL_AGENT_BACKEND_HEALTH_URL = `http://127.0.0.1:${FIXED_BACKEND_PORT}/health`;
  process.env.MYTHICAL_AGENT_FRONTEND_PORT = String(FIXED_FRONTEND_PORT);
  process.env.MYTHICAL_AGENT_BACKEND_PORT = String(FIXED_BACKEND_PORT);

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1100,
    minHeight: 720,
    title: "Mythical Age · 洪荒智能",
    backgroundColor: "#f6f1e7",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.loadURL(`http://127.0.0.1:${FIXED_FRONTEND_PORT}/`);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

function buildMenu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "文件",
        submenu: [
          { label: "打开数据目录", click: () => shell.openPath(dataRoot()) },
          { label: "打开日志目录", click: () => shell.openPath(runtimeDir()) },
          { type: "separator" },
          { role: "quit", label: "退出" },
        ],
      },
      {
        label: "视图",
        submenu: [
          { role: "reload", label: "重新载入" },
          { role: "toggleDevTools", label: "开发者工具" },
          { type: "separator" },
          { role: "resetZoom", label: "实际大小" },
          { role: "zoomIn", label: "放大" },
          { role: "zoomOut", label: "缩小" },
          { type: "separator" },
          { role: "togglefullscreen", label: "全屏" },
        ],
      },
    ])
  );
}

if (hasInstanceLock) app.whenReady().then(async () => {
  TRACE("app ready");
  buildMenu();
  TRACE("menu built");
  try {
    TRACE("starting backend");
    await startBackend();
    TRACE("backend ready");
    await startFrontend();
    TRACE("frontend ready");
    createWindow();
    TRACE("window created");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    log("host.err", `${message}\n`);
    dialog.showErrorBox("Mythical Age · 洪荒智能 启动失败", message);
    stopChildren();
    app.quit();
  }
});

app.on("window-all-closed", () => {
  quitting = true;
  stopChildren();
  app.quit();
});

app.on("before-quit", () => {
  quitting = true;
  stopChildren();
});
