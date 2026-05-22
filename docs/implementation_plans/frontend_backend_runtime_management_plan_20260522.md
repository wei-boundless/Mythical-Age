# 前后端运行与端口管理规范计划

## 目标

- 固定项目运行契约：前端 `3000`，后端 `8002`，前端 `/api/*` 统一代理到后端 `/api/*`。
- 用项目级脚本统一启动、检查、停止，不再靠手工开多个终端或按端口盲杀进程。
- 端口冲突时先说明占用进程和归属，再决定是否停止，避免误杀非本项目服务。
- 日志、PID、健康检查结果固定落在 `output/runtime/`，方便排查 `Internal Server Error`、代理失败和后端未启动。

## 现状问题

- `frontend/package.json` 只管理 Next 自身，无法保证后端 `8002` 已经健康。
- `frontend/next.config.mjs` 已正确代理到 `127.0.0.1:8002`，但没有统一的后端生命周期管理。
- `scripts/clear_project_ports.ps1` 适合救急，但默认按端口清理风险太高，容易把“端口问题”变成“进程归属不清”的问题。
- 之前出现过 stale `.next`、多个后端监听或后端未健康导致前端 `3000` 看起来“页面挂了”。

## 实施方案

1. 新增 `scripts/project_stack.ps1` 作为唯一日常入口：
   - `-Action start`：启动后端和前端，等待后端 `/health`，检查前端首页。
   - `-Action check`：列出 `3000`、`8002` 占用 PID、命令行、是否项目进程、健康接口结果。
   - `-Action stop`：只停止本脚本记录的 PID 或能明确识别为本项目的进程。
2. 运行状态统一写入：
   - `output/runtime/backend-8002.pid`
   - `output/runtime/frontend-3000.pid`
   - `output/runtime/backend-8002.out.log`
   - `output/runtime/backend-8002.err.log`
   - `output/runtime/frontend-3000.out.log`
   - `output/runtime/frontend-3000.err.log`
3. 调整 `scripts/clear_project_ports.ps1` 的定位：
   - 默认仍可用于端口清理，但文档上不作为日常入口。
   - 日常使用 `project_stack.ps1 -Action stop`，只有确认端口被无关残留占用时再用清理脚本。

## 验收标准

- `scripts/project_stack.ps1 -Action check` 能解释当前端口状态，而不是只报“端口被占用”。
- `scripts/project_stack.ps1 -Action start` 后：
  - `http://127.0.0.1:8002/health` 返回健康。
  - `http://127.0.0.1:8002/api/capability-system/catalog` 可访问。
  - `http://localhost:3000/` 可访问。
- `scripts/project_stack.ps1 -Action stop` 不会停止无法识别归属的外部进程。
