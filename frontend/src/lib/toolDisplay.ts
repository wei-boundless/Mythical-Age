export type ToolDisplayFamily =
  | "browser"
  | "command"
  | "data"
  | "file"
  | "generic"
  | "inspect"
  | "media"
  | "memory"
  | "search"
  | "write";

export type ToolDisplayInput = {
  actionKind?: string;
  displayName?: string;
  operationId?: string;
  title?: string;
  toolName?: string;
};

export const TOOL_ACTION_LABELS = [
  "运行命令",
  "匹配路径",
  "列出目录",
  "检查路径",
  "读取工作区",
  "读取文件",
  "读取工具结果",
  "搜索文件",
  "搜索文本",
  "搜索工作区",
  "查找符号",
  "写入文件",
  "编辑文件",
  "批量编辑文件",
  "应用补丁",
  "查看 Git",
  "执行 Git 操作",
  "项目网络",
  "读取记忆",
  "写入记忆候选",
  "网络搜索",
  "读取网页",
  "操作浏览器",
  "生成图片",
  "编辑文档",
  "读取表格",
  "调度子 Agent",
  "更新任务清单",
  "服务调用",
  "工具操作",
];

const COMMAND_TOOL_NAMES = new Set([
  "bash",
  "cmd",
  "command",
  "local_execution",
  "powershell",
  "python_repl",
  "shell",
  "terminal",
]);

const TOOL_ACTION_LABEL_BY_NAME: Record<string, string> = {
  agent_state: "更新任务清单",
  apply_patch: "应用补丁",
  attachment_extract_text: "提取附件文字",
  batch_edit_file: "批量编辑文件",
  batch_edit: "批量编辑文件",
  browser: "操作浏览器",
  browser_control: "操作浏览器",
  code_structure: "分析代码结构",
  command: "运行命令",
  edit: "编辑文件",
  edit_file: "编辑文件",
  fetch: "读取网页",
  generate_image: "生成图片",
  git: "查看 Git",
  glob: "匹配路径",
  glob_paths: "匹配路径",
  image: "生成图片",
  image_edit: "编辑图片",
  image_generate: "生成图片",
  list: "列出目录",
  dir: "列出目录",
  directory: "列出目录",
  list_dir: "列出目录",
  local_execution: "运行命令",
  mcp_structured_data: "读取结构化数据",
  memory: "读取记忆",
  memory_read: "读取记忆",
  memory_write: "写入记忆",
  memory_write_candidate: "写入记忆候选",
  office_document: "编辑文档",
  path_exists: "检查路径",
  playwright: "操作浏览器",
  project_network: "项目网络",
  read: "读取文件",
  read_file: "读取文件",
  read_files: "读取文件",
  read_path: "读取文件",
  result: "读取工具结果",
  read_spreadsheet: "读取表格",
  read_table: "读取表格",
  search_files: "搜索文件",
  search_text: "搜索文本",
  shell: "运行命令",
  exists: "检查路径",
  stat: "检查路径",
  stat_path: "检查路径",
  symbol: "查找符号",
  structured_data: "读取结构化数据",
  subagent: "调度子 Agent",
  terminal: "运行命令",
  web: "网络搜索",
  web_search: "网络搜索",
  write: "写入文件",
  batch: "批量编辑文件",
  create: "写入文件",
  file: "读取文件",
  metadata: "检查路径",
  multi_edit: "批量编辑文件",
  overwrite: "写入文件",
  path: "匹配路径",
  patch: "编辑文件",
  replace: "编辑文件",
  text: "搜索文本",
  tool_result: "读取工具结果",
  workspace_edit: "编辑文件",
  workspace_read: "读取工作区",
  workspace_result_read: "读取工具结果",
  workspace_search: "搜索工作区",
  write_file: "写入文件",
};

const OPERATION_ACTION_LABEL_BY_ID: Record<string, string> = {
  "op.agent_todo": "更新任务清单",
  "op.browser_control": "操作浏览器",
  "op.code_structure_read": "分析代码结构",
  "op.fetch_url": "读取网页",
  "op.git_read": "查看 Git",
  "op.git_remote": "执行 Git 操作",
  "op.git_write": "执行 Git 操作",
  "op.image_generate": "生成图片",
  "op.memory_read": "读取记忆",
  "op.memory_write_candidate": "写入记忆候选",
  "op.office_document": "编辑文档",
  "op.project_network_build": "项目网络",
  "op.project_network_control": "项目网络",
  "op.project_network_maintenance": "项目网络",
  "op.project_network_read": "项目网络",
  "op.project_network_semantic_submit": "项目网络",
  "op.shell": "运行命令",
  "op.subagent_close": "调度子 Agent",
  "op.subagent_list": "调度子 Agent",
  "op.subagent_message": "调度子 Agent",
  "op.subagent_spawn": "调度子 Agent",
  "op.subagent_wait": "调度子 Agent",
  "op.web_search": "网络搜索",
  "op.workspace_edit": "编辑文件",
  "op.workspace_read": "读取工作区",
  "op.workspace_search": "搜索工作区",
  "op.workspace_write": "写入文件",
};

export function displayToolActionName(input: ToolDisplayInput | string) {
  const payload = typeof input === "string" ? { toolName: input } : input;
  const toolName = normalizeToolKey(payload.toolName);
  const actionKind = normalizeToolKey(payload.actionKind);
  const operationId = normalizeOperationId(payload.operationId);
  const actionSpecific = actionLabelForToolAction(toolName, actionKind);
  if (actionSpecific) return actionSpecific;
  if (operationId && OPERATION_ACTION_LABEL_BY_ID[operationId]) return OPERATION_ACTION_LABEL_BY_ID[operationId];
  if (toolName && TOOL_ACTION_LABEL_BY_NAME[toolName]) return TOOL_ACTION_LABEL_BY_NAME[toolName];
  if (actionKind && TOOL_ACTION_LABEL_BY_NAME[actionKind]) return TOOL_ACTION_LABEL_BY_NAME[actionKind];
  return cleanDisplayText(payload.title)
    || cleanDisplayText(payload.displayName)
    || cleanDisplayText(payload.toolName)
    || cleanDisplayText(payload.operationId)
    || "工具操作";
}

export function displayCapabilityToolName(input: ToolDisplayInput) {
  const action = displayToolActionName(input);
  const name = cleanDisplayText(input.displayName);
  if (!name || looksLikeInternalToolName(name) || looksLikeEnglishNativeToolName(name)) return action;
  return name;
}

export function toolInvocationTitle(input: ToolDisplayInput & { target?: string }) {
  return [displayToolActionName(input), cleanDisplayText(input.target)].filter(Boolean).join(" ");
}

export function isCommandToolName(value: string) {
  return COMMAND_TOOL_NAMES.has(normalizeToolKey(value));
}

export function toolDisplayFamily(input: ToolDisplayInput | string): ToolDisplayFamily {
  const payload = typeof input === "string" ? { toolName: input } : input;
  const toolName = normalizeToolKey(payload.toolName);
  const actionKind = normalizeToolKey(payload.actionKind);
  const toolKey = toolName || actionKind;
  const operationId = normalizeOperationId(payload.operationId);
  const actionOnlyFamily = actionDisplayFamily(actionKind);
  if (actionOnlyFamily && (!toolName || isGenericToolKey(toolName))) return actionOnlyFamily;
  if (isCommandToolName(toolKey) || operationId === "op.shell") return "command";
  if (toolName === "workspace_read") {
    if (["dir", "directory", "list", "list_dir", "stat", "exists", "metadata", "path_exists"].includes(actionKind)) return "inspect";
    if (["result", "tool_result", "workspace_result_read"].includes(actionKind)) return "data";
    return "file";
  }
  if (["read_file", "read_files", "read_path", "attachment_extract_text", "workspace_result_read"].includes(toolKey)) return "file";
  if (["workspace_search", "search_files", "search_text", "glob_paths", "web_search", "deepsearch", "web"].includes(toolKey)) return "search";
  if (["dir", "directory", "list", "list_dir", "stat", "exists", "stat_path", "path_exists", "code_structure"].includes(toolKey)) return "inspect";
  if (["workspace_edit", "write_file", "edit_file", "batch_edit_file", "apply_patch", "office_document"].includes(toolKey)) return "write";
  if (["image", "image_generate", "generate_image", "image_edit"].includes(toolKey)) return "media";
  if (["mcp_structured_data", "structured_data", "read_spreadsheet", "read_table", "result", "tool_result"].includes(toolKey)) return "data";
  if (["memory", "memory_read", "memory_write", "memory_write_candidate", "agent_state"].includes(toolKey)) return "memory";
  if (["browser", "browser_control", "playwright"].includes(toolKey)) return "browser";
  if (operationId.startsWith("op.workspace_write") || operationId.startsWith("op.workspace_edit") || operationId === "op.office_document") return "write";
  if (operationId.startsWith("op.workspace_read")) return "file";
  if (operationId.startsWith("op.workspace_search") || operationId === "op.web_search" || operationId === "op.fetch_url") return "search";
  if (operationId.startsWith("op.git")) return "command";
  if (operationId.startsWith("op.memory") || operationId === "op.agent_todo") return "memory";
  if (operationId === "op.browser_control") return "browser";
  if (operationId === "op.image_generate") return "media";
  if (operationId === "op.code_structure_read" || operationId.startsWith("op.project_network")) return "inspect";
  return "generic";
}

function actionLabelForToolAction(toolName: string, actionKind: string) {
  if (!toolName || !actionKind) return "";
  if (toolName === "workspace_edit") {
    if (["write", "create", "overwrite"].includes(actionKind)) return "写入文件";
    if (["batch_edit", "batch", "multi_edit"].includes(actionKind)) return "批量编辑文件";
    if (["edit", "replace", "patch"].includes(actionKind)) return "编辑文件";
  }
  if (toolName === "workspace_search") {
    if (["path", "glob"].includes(actionKind)) return "匹配路径";
    if (actionKind === "text") return "搜索文本";
    if (actionKind === "symbol") return "查找符号";
  }
  if (toolName === "workspace_read") {
    if (["dir", "list", "list_dir", "directory"].includes(actionKind)) return "列出目录";
    if (["stat", "exists", "metadata"].includes(actionKind)) return "检查路径";
    if (["result", "tool_result"].includes(actionKind)) return "读取工具结果";
    if (["file", "read", "read_file"].includes(actionKind)) return "读取文件";
    return "读取工作区";
  }
  if (toolName === "git") {
    if (["status", "diff", "log", "show", "branch_list"].includes(actionKind)) return "查看 Git";
    return "执行 Git 操作";
  }
  if (toolName === "web") {
    if (actionKind === "fetch") return "读取网页";
    return "网络搜索";
  }
  if (toolName === "project_network") return "项目网络";
  if (toolName === "subagent") return "调度子 Agent";
  if (toolName === "memory") return actionKind.includes("write") ? "写入记忆候选" : "读取记忆";
  return "";
}

function actionDisplayFamily(actionKind: string): ToolDisplayFamily | "" {
  if (["file", "read", "read_file", "read_path"].includes(actionKind)) return "file";
  if (["dir", "directory", "list", "list_dir", "stat", "exists", "metadata", "path_exists"].includes(actionKind)) return "inspect";
  if (["result", "tool_result", "workspace_result_read"].includes(actionKind)) return "data";
  if (["path", "glob", "search", "text", "symbol"].includes(actionKind)) return "search";
  if (["write", "create", "overwrite", "edit", "replace", "patch", "batch", "batch_edit", "multi_edit"].includes(actionKind)) return "write";
  if (["run", "verify", "command"].includes(actionKind)) return "command";
  return "";
}

function normalizeToolKey(value: unknown) {
  return cleanDisplayText(value).toLowerCase().replace(/[\s-]+/g, "_");
}

function normalizeOperationId(value: unknown) {
  return cleanDisplayText(value).toLowerCase();
}

function cleanDisplayText(value: unknown) {
  return String(value ?? "").replace(/[ \t\f\v]+/g, " ").trim();
}

function looksLikeInternalToolName(value: string) {
  return /^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$/u.test(value.trim());
}

function isGenericToolKey(value: string) {
  return !value || value === "tool" || value === "generic" || value === "工具";
}

function looksLikeEnglishNativeToolName(value: string) {
  return [
    "Agent State",
    "Browser",
    "Code Structure",
    "Git",
    "Image",
    "Local Execution",
    "Memory",
    "Office Document",
    "Project Network",
    "Subagent",
    "Web",
    "Workspace Edit",
    "Workspace Read",
    "Workspace Search",
  ].includes(value.trim());
}
