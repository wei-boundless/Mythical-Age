# Vibe Coding 环境移植计划书：Pi Sidecar + 本项目 Agent 主控

日期：2026-05-25

## 1. 目标结论

本次移植不把 Pi 改造成主平台，也不把现有前端改成只能本地运行。正确目标是：

```text
本项目 Agent 平台继续作为主控
  ├─ agent 配置、任务图、记忆、权限、运行事件仍由本项目管理
  ├─ Web 端继续保留，可作为普通工作台访问
  ├─ Electron 本地端提供本地增强能力
  └─ Pi 作为本地 vibe coding sidecar 环境被调用
```

Pi 的定位是“本地 coding 环境能力层”，不是“新的 agent 平台”。它可以提供 Node/TS coding runtime、RPC/SDK、read/edit/write/bash/grep/find/ls 工具、session/compaction/diff/事件流经验，但不能替代本项目已有的 orchestration、prompt library、runtime profile、memory、task system 和权限系统。

## 2. 当前代码依据

### 2.1 本项目现状

- 前端是 `frontend` 下的 Next.js / React / TypeScript 项目，固定运行在 `http://127.0.0.1:3000`。
- 后端是 FastAPI，入口为 `backend/app.py`，固定运行在 `http://127.0.0.1:8003`，前端 API Base 固定为 `http://127.0.0.1:8003/api`。
- Electron 已存在基础本地壳：
  - `frontend/electron/main.cjs` 已负责启动后端和前端服务。
  - `frontend/electron/preload.cjs` 已通过 `mythicalAgentHost.getConfig()` 暴露本地 host 配置。
- 本项目已有 agent / task / memory / orchestration / capability system，不需要引入第二套主控系统。
- 既有文档 `docs/系统规划/213-Vibe-Coding能力移植规划-基于当前OpenCode源码校正版-20260524.md` 已明确：vibe coding 缺口在 coding kernel、workspace state、strict tools、diff approval、verification，而不是缺一个新平台。

### 2.2 Pi 代码现状

Pi 位于 `D:/AI应用/pi-main`，是 Node/TypeScript monorepo：

- 根 `package.json` 定义 workspaces：`packages/*`。
- `packages/coding-agent/package.json` 暴露 CLI `pi`，包名为 `@earendil-works/pi-coding-agent`。
- `packages/coding-agent/docs/sdk.md` 显示 SDK 可通过 `createAgentSession()` 创建 agent session。
- `packages/coding-agent/docs/rpc.md` 显示 RPC 模式可通过 JSONL stdin/stdout 嵌入其他应用。
- `packages/coding-agent/src/modes/rpc/rpc-mode.ts` 是 headless RPC 服务端。
- `packages/coding-agent/src/modes/rpc/rpc-client.ts` 是 Node 侧 typed RPC client。
- `packages/coding-agent/src/core/agent-session.ts` 是 Pi session、事件、bash、compaction、tool registry 的核心抽象。

Pi 适合作为本地 sidecar 或 SDK runtime，不适合直接打包进浏览器 renderer。

## 3. 设计边界

### 3.1 必须保留

- 保留 Web 端：浏览器访问 `127.0.0.1:3000` 仍然可用。
- 保留 Electron 本地端：Electron renderer 继续复用同一套 TS/React UI。
- 保留本项目 FastAPI 后端作为主 API。
- 保留本项目 agent 配置作为权威配置。
- 保留固定端口：前端 `3000`，后端 `8003`，API Base `8003/api`。

### 3.2 Pi 只承担

- 本地 coding tool 环境。
- RPC/SDK 事件流。
- 可选的 read/edit/write/bash/grep/find/ls 能力。
- coding session 的外部执行通道。
- 后续 strict edit、change set、verification 设计的参考实现来源。

### 3.3 Pi 不承担

- 不作为主会话系统。
- 不作为主 agent 配置系统。
- 不替换本项目 task graph / orchestration。
- 不替换本项目 memory。
- 不直接控制前端路由。
- 不把 Pi TUI 做成本项目主 UI。

## 4. 目标架构

```text
Browser Web Mode
  └─ Next/React UI
      └─ FastAPI /api
          └─ 本项目 agent / task / memory / orchestration

Electron Desktop Mode
  └─ Next/React UI
      ├─ FastAPI /api
      │   └─ 本项目 agent / task / memory / orchestration
      └─ Electron preload host capability
          └─ local host metadata / future IPC

Local Vibe Coding Runtime
  └─ Pi sidecar process or SDK bridge
      ├─ JSONL RPC
      ├─ coding tools
      ├─ event stream
      └─ local workspace cwd
```

主调用链应为：

```text
用户请求
  -> 本项目 chat / task / orchestration
  -> 选择 vibe coding capability
  -> 后端 Pi adapter 创建或复用 sidecar
  -> 发送受控 prompt / command
  -> 接收 Pi events
  -> 转成本项目 runtime event / receipt / change set
  -> 前端展示状态、diff、验证和审批
```

## 5. 数据合同

第一版不要让前端直接消费 Pi 原始事件。后端需要把 Pi RPC 事件投影成本项目自己的合同：

```text
PiRuntimeStatus
- available: boolean
- mode: web_only | desktop_host | sidecar_ready | sidecar_running | error
- pi_source_root
- pi_cli_path
- node_version
- workspace_root
- diagnostics[]

VibeCodingSession
- session_id
- owner_session_id
- workspace_root
- provider_ref
- model_ref
- status
- pi_session_id
- pi_session_file
- created_at
- updated_at

VibeCodingEvent
- event_id
- session_id
- event_type
- phase: prompt | model | tool | change | verification | approval | terminal | error
- title
- body
- raw_event_ref
- created_at

VibeCodingToolReceipt
- receipt_id
- session_id
- tool_name
- status
- input_summary
- output_summary
- details
- artifact_refs[]

VibeCodingChangeSet
- change_set_id
- session_id
- files[]
- diff_ref
- approval_status
- verification_status
```

Pi 原始 JSONL 事件只作为 `raw_event_ref` 存档，不直接进入长期记忆或最终回答。

## 6. 分阶段实施计划

### Phase 1：环境接入与健康检查

目标：让项目能识别 Pi 环境，但不启动真实 coding 任务。

改动范围：

- 新增后端模块：
  - `backend/vibe_coding/pi_environment.py`
  - `backend/vibe_coding/models.py`
  - `backend/api/vibe_coding.py`
- 改造：
  - `backend/app.py` 注册 `/api/vibe-coding/*` router。
- 新增本地配置：
  - `backend/config.json` 或独立 `storage/vibe_coding/pi_environment.json` 记录 Pi 根目录、CLI 路径、启用状态。

完成标准：

- `GET /api/vibe-coding/environment` 返回 Node 版本、Pi 根目录、CLI/RPC 可用性、当前工作区。
- Web 模式也能看到环境状态。
- 未安装或未构建 Pi 时返回明确 diagnostics，不假装可用。

### Phase 2：Pi Sidecar 管理

目标：后端能以受控方式启动、停止、检查 Pi RPC sidecar。

改动范围：

- 新增：
  - `backend/vibe_coding/pi_rpc_process.py`
  - `backend/vibe_coding/pi_rpc_client.py`
  - `backend/vibe_coding/event_store.py`
- API：
  - `POST /api/vibe-coding/sidecar/start`
  - `POST /api/vibe-coding/sidecar/stop`
  - `GET /api/vibe-coding/sidecar/status`

规则：

- sidecar cwd 必须是本项目根目录或用户显式选择的 workspace。
- stdout 使用严格 JSONL 解析。
- stderr 和原始事件落盘到 `output/vibe-coding/pi-sidecar/`。
- sidecar 不直接写本项目 memory。

完成标准：

- 可以启动 Pi RPC。
- 可以发送 `get_state`。
- 可以停止 sidecar。
- 异常退出有清晰 diagnostics。

### Phase 3：Agent 主控接入

目标：本项目 agent 配置可以选择使用 Pi sidecar，但 Pi 不接管任务决策。

改动范围：

- `backend/capability_system` 增加 `vibe_coding.pi_sidecar` 能力声明。
- `backend/runtime/tool_runtime` 或独立 adapter 增加 Pi prompt/command 调用入口。
- `storage/orchestration/agent_runtime_profiles.json` 只增加引用，不改成 Pi profile 主控。
- Prompt library 中新增面向 agent 的角色 prompt，而不是开发说明。

Agent prompt 原则：

```text
你是一名代码执行代理。
你只在收到明确代码修改、验证或项目检查任务时使用本地 vibe coding 环境。
你必须先确认工作区、目标文件和验证方式。
你不能绕过本项目权限、任务合同和最终证据要求。
你调用 Pi sidecar 得到的是执行事件和工具回执，不是最终事实本身。
你需要把变更、验证和风险整理成可审查结果。
```

完成标准：

- 本项目 runtime 能把一次 coding 请求发给 Pi sidecar。
- Pi 返回事件被转换为本项目 `VibeCodingEvent`。
- 最终回答仍由本项目 closeout 决定。

### Phase 4：Web 保留 + Desktop 增强

目标：同一套前端同时支持 Web 模式和 Electron 本地增强模式。

改动范围：

- `frontend/electron/preload.cjs` 增加 host capability：
  - `mode`
  - `localRuntimeAvailable`
  - `vibeCodingHostAvailable`
- `frontend/src/lib/api.ts` 增加 vibe coding API 类型和请求函数。
- 新增前端视图：
  - `frontend/src/components/workspace/views/VibeCodingView.tsx`
- `frontend/src/app/page.tsx` 增加 `vibe-coding` 工作台入口。
- `frontend/src/lib/store/types.ts` 增加 `WorkspaceView = "vibe-coding"`。

Web 模式行为：

- 展示环境状态。
- 如果 sidecar 不可用，明确显示“本地 vibe coding 环境未连接”。
- 仍可查看历史事件和后端状态。

Electron 模式行为：

- 展示本地 host 已连接。
- 可启动/停止 sidecar。
- 后续可展示 diff、验证、审批。

完成标准：

- 浏览器网页不报错。
- Electron 本地模式能看到本地 host 信息。
- 前端不直接调用 `fs`、`child_process`。

### Phase 5：Change Set 与验证闭环

目标：从“能调用 Pi”升级为“能审查代码变更”。

改动范围：

- 新增：
  - `backend/vibe_coding/change_set.py`
  - `backend/vibe_coding/diff_parser.py`
  - `backend/vibe_coding/verification.py`
- 前端增强：
  - change set 文件列表
  - diff viewer
  - tool receipt
  - verification receipt

规则：

- Pi tool result 中的 diff/patch 需要转成本项目 `VibeCodingChangeSet`。
- 大输出只保存 ref 和摘要。
- verification 命令需要记录 exit code、tail、full output ref。
- final answer 只能消费 change set 和 verification receipt。

完成标准：

- 能看到本轮改了哪些文件。
- 能查看 diff。
- 能看到验证命令与结果。
- 失败时有可追溯原因。

### Phase 6：权限与审批对齐

目标：让 Pi 的本地编辑能力受本项目权限系统约束。

改动范围：

- `backend/permissions/*`
- `backend/runtime/execution_permit/*`
- `backend/vibe_coding/approval_payloads.py`
- 前端 approval dock

规则：

- 用户批准的是 change set，不是抽象工具名。
- edit/write/patch 统一归入 workspace edit 权限。
- 外部目录、删除、移动、大范围修改必须 ask 或 deny。
- 被拒绝后必须熔断或停止，不允许无限重试。

完成标准：

- Pi 产生编辑意图时，本项目可以拦截和展示 diff approval。
- 未审批的 change set 不进入 canonical final。

## 7. 迁移与切换规则

### 7.1 兼容策略

- Web 端永远保留。
- Electron 是增强模式，不是替代 Web。
- Pi sidecar 默认可配置关闭。
- 未检测到 Pi 时，vibe coding 页面只显示 diagnostics，不触发任务执行。

### 7.2 Cutover 规则

第一版不把所有代码任务自动切到 Pi。只有满足以下条件才进入 Pi sidecar：

- 用户显式选择 vibe coding。
- 或 task profile 明确要求 local coding execution。
- 环境健康检查通过。
- 当前 workspace_root 明确且在允许范围内。

### 7.3 Rollback 规则

- 关闭 `vibe_coding.pi_sidecar.enabled` 后，所有代码任务回退现有 professional runtime。
- sidecar 异常时不影响普通 chat、memory、task、orchestration。
- 不删除现有 vibe coding 静态 profile，只禁用 sidecar execution path。

## 8. 风险控制

### 风险 1：Pi 反客为主

控制：Pi adapter 只返回事件、receipt、change set。任务裁决、记忆、最终输出仍由本项目 runtime 决定。

### 风险 2：Web 端被本地能力污染

控制：Web 只通过 FastAPI 查询状态，不直接依赖 Electron API。本地能力通过 host capability 显式判断。

### 风险 3：权限绕过

控制：Pi sidecar 的编辑结果必须转成本项目 change set 和 approval payload。后续 strict mode 再把编辑前审批前移。

### 风险 4：上下文污染

控制：Pi raw event 和大输出落盘为 ref，模型只看摘要、tail、change set、verification receipt。

### 风险 5：端口和进程混乱

控制：仍使用固定 `3000` / `8003`。Pi sidecar 不占用随机 Web 端口，走 stdio JSONL 或本地受控 IPC。

## 9. 第一版最小交付

第一版只做环境移植，不做完整 IDE：

1. Pi 环境健康检查。
2. Pi RPC sidecar 启停。
3. 后端 thin adapter。
4. 前端 Vibe Coding 环境页。
5. Web/Electron capability 区分。
6. 一次只读 `get_state` / `get_available_models` / 简单 prompt smoke test。

不在第一版做：

- 完整 diff approval。
- 自动接管所有代码任务。
- 真 LSP diagnostics。
- Git commit / PR。
- 仿 Pi TUI。
- 浏览器内直接文件编辑。

## 10. 文件级执行清单

### 后端新增

- `backend/vibe_coding/__init__.py`
- `backend/vibe_coding/models.py`
- `backend/vibe_coding/pi_environment.py`
- `backend/vibe_coding/pi_rpc_process.py`
- `backend/vibe_coding/pi_rpc_client.py`
- `backend/vibe_coding/event_store.py`
- `backend/api/vibe_coding.py`

### 后端改造

- `backend/app.py`
  - 注册 `vibe_coding_router`。
- `backend/config.json`
  - 增加 `vibe_coding.pi_sidecar` 配置，默认关闭或 diagnostic-only。

### 前端新增

- `frontend/src/components/workspace/views/VibeCodingView.tsx`
- `frontend/src/lib/api/vibeCoding.ts` 或合并进 `frontend/src/lib/api.ts`

### 前端改造

- `frontend/electron/preload.cjs`
  - 增加 host capability。
- `frontend/src/lib/store/types.ts`
  - 增加 `vibe-coding` workspace view。
- `frontend/src/app/page.tsx`
  - 增加 lazy view、导航项和 query view。
- `frontend/src/app/globals.css`
  - 增加 vibe coding 页面样式。

### 文档与配置

- `.pi/AGENTS.md` 或 `.pi/prompts/*`
  - 只写给 Pi/agent 理解的角色职责，不写开发说明。
- `docs/implementation_plans/vibe_coding_pi_environment_migration_plan_20260525.md`
  - 本计划书作为实施依据。

## 11. 验证矩阵

### 环境验证

- `node -v` 满足 Pi `>=22.19.0`。
- `npm -v` 可用。
- Pi root 存在。
- Pi CLI 或 `packages/coding-agent/dist/cli.js` 可用。

### 后端验证

- `GET /health` 正常。
- `GET /api/vibe-coding/environment` 正常。
- sidecar 启动失败能返回明确错误。
- sidecar 停止后无残留子进程。

### 前端验证

- Web 浏览器访问 `http://127.0.0.1:3000` 不报错。
- Electron 启动后 `mythicalAgentHost.getConfig()` 仍正常。
- Vibe Coding 页面在 Web 模式显示 diagnostics。
- Vibe Coding 页面在 Electron 模式显示 local host capability。

### 集成验证

- 发送 `get_state` 能收到 Pi RPC response。
- 发送简单 prompt 能收到 `message_update` 和 `agent_end`。
- stderr、stdout、raw events 都有落盘路径。

## 12. 最终判断

这条路线是兼容迁移，不是大改前端，也不是把 Pi 变成主平台。

最重要的设计原则是：

```text
本项目决定任务、权限、记忆和最终裁决。
Pi 只提供本地 coding 执行环境。
Web 继续保留。
Electron 提供本地增强。
所有 Pi 输出必须转成本项目可审查的事件、回执和变更集。
```

