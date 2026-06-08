const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const frontendRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(frontendRoot, "..");
const backendRoot = path.join(repoRoot, "backend");
const runtimeDir = path.join(repoRoot, "output", "electron-host");
const preferredFrontendPort = Number(process.env.MYTHICAL_AGENT_FRONTEND_PORT || 3000);
const preferredBackendPort = Number(process.env.MYTHICAL_AGENT_BACKEND_PORT || 8003);
const pythonExe = process.env.MYTHICAL_AGENT_PYTHON || "C:\\Users\\admin\\.conda\\envs\\agent\\python.exe";

const children = new Map();
const serviceSpecs = new Map();
let mainWindow = null;
let shuttingDown = false;

function ensureRuntimeDir() {
  fs.mkdirSync(runtimeDir, { recursive: true });
}

function appendLog(name, chunk) {
  ensureRuntimeDir();
  fs.appendFileSync(path.join(runtimeDir, `${name}.log`), chunk);
}

function canConnect(port, host) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ port, host });
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

function canBind(port, host) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

async function isPortFree(port) {
  const connectHosts = ["127.0.0.1", "::1", "localhost"];
  for (const host of connectHosts) {
    if (await canConnect(port, host)) {
      return false;
    }
  }

  if (!(await canBind(port, "127.0.0.1"))) {
    return false;
  }
  if (!(await canBind(port, "::1"))) {
    return false;
  }
  return true;
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

async function waitForUrl(url, label, timeoutMs = 60000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await requestOk(url)) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  throw new Error(`${label} did not become healthy: ${url}`);
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
  serviceSpecs.set(name, { command, args, options });
  fs.writeFileSync(path.join(runtimeDir, `${name}.pid`), String(child.pid || ""));
  child.stdout.on("data", (chunk) => appendLog(`${name}.out`, chunk));
  child.stderr.on("data", (chunk) => appendLog(`${name}.err`, chunk));
  child.on("exit", (code, signal) => {
    children.delete(name);
    appendLog("host.out", `[${name}] exited code=${code} signal=${signal}\n`);
    if (!shuttingDown && mainWindow) {
      mainWindow.webContents.send("service-exit", { name, code, signal });
      const spec = serviceSpecs.get(name);
      if (spec) {
        setTimeout(() => {
          if (!shuttingDown && !children.has(name)) {
            appendLog("host.out", `[${name}] restarting\n`);
            spawnManaged(name, spec.command, spec.args, spec.options);
          }
        }, 1200);
      }
    }
  });
  return child;
}

function stopProcessTree(pid) {
  if (!pid) {
    return;
  }
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
    return;
  }
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // Process is already gone.
  }
}

function stopChildren() {
  shuttingDown = true;
  for (const child of children.values()) {
    if (!child.killed) {
      stopProcessTree(child.pid);
    }
  }
  children.clear();
}

async function startServices() {
  const frontendPort = preferredFrontendPort;
  const backendPort = preferredBackendPort;
  if (!(await isPortFree(frontendPort))) {
    throw new Error(`Fixed frontend port ${frontendPort} is occupied. Close the old project frontend process before starting.`);
  }
  if (!(await isPortFree(backendPort))) {
    throw new Error(`Fixed backend port ${backendPort} is occupied. Close the old project backend process before starting.`);
  }
  const frontendUrl = `http://127.0.0.1:${frontendPort}/`;
  const backendHealthUrl = `http://127.0.0.1:${backendPort}/health`;
  const apiBase = `http://127.0.0.1:${backendPort}/api`;

  spawnManaged(
    "backend",
    pythonExe,
    ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", String(backendPort), "--reload"],
    {
      cwd: backendRoot,
      env: { PYTHONPATH: backendRoot },
    }
  );
  await waitForUrl(backendHealthUrl, "Backend");

  const frontendCommand = `npm run dev:next -- -p ${frontendPort}`;
  const frontendSpawn = process.platform === "win32"
    ? { command: "cmd.exe", args: ["/d", "/s", "/c", frontendCommand] }
    : { command: "npm", args: ["run", "dev:next", "--", "-p", String(frontendPort)] };
  spawnManaged("frontend", frontendSpawn.command, frontendSpawn.args, {
    cwd: frontendRoot,
    env: {
      NEXT_PUBLIC_API_BASE: apiBase,
      API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
    },
  });
  await waitForUrl(frontendUrl, "Frontend");

  return { frontendPort, backendPort, frontendUrl, backendHealthUrl, apiBase };
}

function createWindow(config) {
  process.env.MYTHICAL_AGENT_API_BASE = config.apiBase;
  process.env.MYTHICAL_AGENT_FRONTEND_URL = config.frontendUrl;
  process.env.MYTHICAL_AGENT_BACKEND_HEALTH_URL = config.backendHealthUrl;
  process.env.MYTHICAL_AGENT_FRONTEND_PORT = String(config.frontendPort);
  process.env.MYTHICAL_AGENT_BACKEND_PORT = String(config.backendPort);

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1100,
    minHeight: 720,
    title: "Mythical Age · 洪荒智能",
    backgroundColor: "#f6f1e7",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(config.frontendUrl);
}

app.whenReady().then(async () => {
  try {
    const config = await startServices();
    createWindow(config);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    appendLog("host.err", `${message}\n`);
    dialog.showErrorBox("Mythical Age · 洪荒智能 failed to start", message);
    app.quit();
  }
});

app.on("window-all-closed", () => {
  stopChildren();
  app.quit();
});

app.on("before-quit", () => {
  stopChildren();
});
