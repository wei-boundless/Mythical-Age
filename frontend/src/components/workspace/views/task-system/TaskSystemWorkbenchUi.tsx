"use client";

import { useState, type ReactNode } from "react";

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.map((item) => String(item ?? "").trim()).filter(Boolean)));
}

export function taskSystemOptionLabel(value: string) {
  const labels: Record<string, string> = {
    default: "默认",
    enabled: "已启用",
    disabled: "已停用",
    draft: "草稿",
    published: "已发布",
    active: "运行中",
    pending: "等待中",
    completed: "已完成",
    failed: "失败",
    warning: "警告",
    error: "错误",
    info: "信息",
    global_task: "全局任务",
    workflow: "单任务工作流",
    workflow_step: "工作流步骤",
    node_execution: "节点执行",
    edge_handoff: "边交接",
    final_output: "最终输出",
    runtime: "运行要求",
    failure: "失败处理",
    human_gate: "人工门控",
    coordinator: "协调者",
    participant: "协作节点",
    reviewer: "审查节点",
    writer: "写作节点",
    planner: "规划节点",
    executor: "执行节点",
    verifier: "验证节点",
    summarizer: "整理节点",
    merge: "汇总节点",
    acceptance: "验收节点",
    review_merge: "审查汇总",
    pipeline: "流水推进",
    parallel_review: "并行审查",
    structured_handoff: "结构化交接",
    review_feedback: "审查反馈",
    draft_request: "起草请求",
    audit_request: "审计请求",
    merge_signal: "合并信号",
    explicit_join: "显式汇合",
    coordinator_join: "协调汇合",
    sequential_join: "顺序汇合",
    fail_closed: "失败即关闭",
    retry_once: "失败重试一次",
    coordinator_decides: "协调者裁定",
    coordinator_terminal: "协调者终止",
    all_nodes_complete: "全节点完成",
    manual_close: "手动关闭",
    explicit_ack: "显式确认",
    implicit_ack: "隐式确认",
    escalate_to_coordinator: "升级给协调者",
    raise_to_coordinator: "上报协调者",
    return_to_sender: "退回发送方",
    halt_chain: "中止链路",
    task_goal: "任务目标",
    plan_fragment: "计划片段",
    decision_record: "决策记录",
    intermediate_result: "中间结果",
    review_note: "审查意见",
    split_plan: "拆分计划",
    static_batch: "静态批次",
    sequential: "顺序批次",
    review_then_commit: "审核后提交",
    manual_review_then_commit: "人工审核后提交",
    auto_commit_without_review: "无审核自动提交",
    repair_until_pass_or_manual_gate: "返修直到通过或人工门",
    next_batch_after_acceptance: "验收后下一批可见",
    wait_all_committed: "等待全部提交",
    manual_merge: "手动合并",
    batch_sequence: "批次顺序",
    range_start: "范围起点",
    conflict_flag: "冲突标记",
    handoff_context: "交接上下文",
    artifact_ref: "产物引用",
    promotion_candidate: "晋升候选",
    chapter_draft: "章节草稿",
    character_state_delta: "人物状态变化",
    world_bible_delta: "世界观设定变化",
    node_scope: "节点范围",
    graph_scope: "图范围",
    task_scope: "任务范围",
    edge_scope: "边范围",
    artifact_scope: "产物范围",
    private_to_node: "节点私有",
    shared_in_graph: "图内共享",
    handoff_only: "仅交接",
    coordinator_only: "仅协调者",
    human_review_only: "仅人工审查",
    working_fact: "工作事实",
    draft_artifact: "草稿产物",
    reflection: "反思",
    instruction: "指令",
    temporal_event: "时间事件",
    conflict: "冲突",
    decision: "决策",
    handoff_note: "交接说明",
    evaluation: "评估",
    bounded_patch: "受限补丁",
    sync: "同步阻塞",
    async: "异步派发",
    parallel: "并行批次",
    max_parallel_batches: "并行批次上限",
    background: "后台节点",
    barrier: "汇合节点",
    manual_gate: "人工门控",
    manual_required: "人工确认后继续",
    auto_continue: "自动继续",
    non_blocking: "非阻塞记录",
    phase_sequence: "阶段顺序推进",
    phase_then_sequence_index: "先阶段后顺序号",
    all_blocking_nodes_complete: "全部阻塞节点完成",
    review_gate_passed: "审核门通过",
    wait_all_upstream_completed: "等待全部上游完成",
    wait_any_upstream_completed: "等待任一上游完成",
    wait_required_contracts: "等待必需契约",
    wait_handoff_ack: "等待交接确认",
    fire_and_continue: "发出后继续",
    manual_release: "人工释放",
    all_success: "全部成功",
    any_success: "任一成功",
    quorum: "法定数量",
    allow_partial_with_issues: "允许带问题部分通过",
    fail_on_any_error: "任一失败即失败",
    fail_downstream: "失败传递到下游",
    isolate_failure: "隔离失败",
    allow_partial: "允许部分结果",
    contract_payload_and_refs: "契约载荷与引用",
    summary_and_refs: "摘要与引用",
    notification_only: "仅通知",
    phase_frame: "阶段框",
    parallel_frame: "并行展示框",
    loop_frame: "循环框",
    review_gate_frame: "审核门框",
    contract_output_ready: "契约输出就绪",
    single_agent_chain: "单 Agent 循环",
    coordination_chain: "协调链",
    graph_run_loop: "图运行循环",
    orchestration_default: "按编排默认选择",
    fixed_agent: "固定 Agent",
    graph_node_binding: "按图模块绑定",
    standard: "标准任务",
    long_running: "长周期任务",
    critical: "关键任务",
    bounded: "受限准入",
    main_agent: "主 Agent",
    builtin_agent: "内置 Agent",
    custom_agent: "自定义 Agent",
    conversation: "会话记忆",
    state: "状态记忆",
    working: "工作记忆",
    long_term: "长期记忆",
    high: "高优先级",
    normal: "普通优先级",
    task_default: "任务默认",
    task_summary_only: "仅写回任务摘要",
    session_and_durable: "会话与长期写回",
    explicit_refs_only: "仅显式引用",
    shared_task_context: "共享任务上下文",
    isolated_by_default: "默认隔离",
    shared_readonly: "只读共享",
    general: "通用任务域",
    development: "开发任务域",
    writing: "写作任务域",
    health: "健康任务域",
    capability: "能力调用域",
    general_task: "通用任务",
    light_web_game: "轻量网页小游戏",
    arcade_game_bundle: "复合网页游戏包",
    knowledge_retrieval: "知识检索",
    information_search: "信息搜索",
    capability_execution: "能力执行",
    main_conversation_entry: "主会话入口",
    issue_triage: "健康问题分诊",
    trace_analysis: "健康链路分析",
    case_draft: "健康用例草案",
    fix_verification: "健康修复验证",
    full_interactive: "完整交互运行",
    task_dispatch: "任务分派",
    final_integration: "最终整合",
    game_delivery: "游戏交付",
    main_conversation: "主会话通道",
    health_issue_read: "健康问题只读",
    health_trace_read: "健康链路只读",
    case_draft_candidate: "用例草案候选",
    fix_verification_candidate: "修复验证候选",
    memory_repository: "记忆仓库",
    memory_collection: "记忆集合",
    memory_resource: "记忆资源",
    artifact_repository: "产物仓库",
    thread_ledger: "线程账本",
    progress_ledger: "线程账本（旧名）",
    issue_ledger: "问题台账",
    runtime_state_store: "运行状态仓库",
    working_memory_store: "工作记忆仓库",
    append_version: "追加版本",
    replace_latest: "替换最新版本",
    immutable_once_committed: "提交后不可改",
    readonly_after_seed: "种子写入后只读",
    mutable: "可变",
    latest_committed_before_stage_start: "阶段启动前最新提交",
    latest_committed_before_iteration: "迭代启动前最新提交",
    fixed_version: "固定版本",
    manual_snapshot: "手动快照",
    snapshot_before_iteration: "迭代前快照",
    memory_read: "记忆读取",
    memory_write: "记忆写入",
    memory_commit: "记忆提交",
    memory_handoff: "记忆交接",
    expand_text_for_model: "展开正文给模型",
    refs_only: "仅传引用",
    block: "阻塞",
    warn: "警告后继续",
    skip: "跳过",
    read: "读取",
    write: "写入",
    handoff: "交接",
    commit: "提交",
    finalize: "最终化",
    fixed_iteration: "固定轮次",
    until_gate_passed: "直到质量门通过",
    while_target_not_met: "目标未达成时循环",
    gate_passed: "质量门通过",
  };
  return labels[value] ?? value;
}

export function taskSystemDisplayLabel(value: unknown, fallback = "未配置") {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const label = taskSystemOptionLabel(raw);
  return label === raw ? raw : `${label} · ${raw}`;
}

type TaskGraphChromeSelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export function TaskGraphChromeSelect({
  disabled = false,
  emptyLabel,
  label,
  onChange,
  options,
  placeholder,
  value,
}: {
  disabled?: boolean;
  emptyLabel?: string;
  label: string;
  onChange: (value: string) => void;
  options: TaskGraphChromeSelectOption[];
  placeholder: string;
  value: string;
}) {
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.value === value);
  const displayLabel = selected?.label || emptyLabel || placeholder;
  const selectableOptions = options.filter((option) => !option.disabled);
  const isDisabled = disabled || selectableOptions.length === 0;

  return (
    <label
      className={isDisabled ? "task-graph-editor-chrome__field task-graph-editor-chrome__field--disabled" : "task-graph-editor-chrome__field"}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <span className="task-graph-editor-chrome__field-label">{label}</span>
      <div className="task-graph-editor-select">
        <button
          aria-expanded={open}
          disabled={isDisabled}
          onClick={() => setOpen((current) => !current)}
          type="button"
        >
          <span>{displayLabel}</span>
          <i aria-hidden="true" />
        </button>
        {open && !isDisabled ? (
          <div className="task-graph-editor-select__menu" role="listbox">
            {options.map((option) => (
              <button
                aria-selected={option.value === value}
                className={option.value === value ? "task-graph-editor-select__option task-graph-editor-select__option--active" : "task-graph-editor-select__option"}
                disabled={option.disabled}
                key={option.value || option.label}
                onClick={() => {
                  if (!option.disabled) {
                    onChange(option.value);
                    setOpen(false);
                  }
                }}
                role="option"
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </label>
  );
}

export function TaskSystemField({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={wide ? "boundary-field boundary-field--wide" : "boundary-field"}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export function TaskSystemToolbarButton({
  children,
  onClick,
  disabled,
  variant = "ghost",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "ghost" | "primary";
}) {
  return (
    <button className={`boundary-button boundary-button--${variant}`} disabled={disabled} onClick={onClick} type="button">
      {children}
    </button>
  );
}

export function TaskSystemSelectField({
  label,
  value,
  options,
  onChange,
  wide = false,
  formatOption = taskSystemOptionLabel,
  isOptionDisabled,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  wide?: boolean;
  formatOption?: (value: string) => string;
  isOptionDisabled?: (value: string) => boolean;
}) {
  const resolvedOptions = uniqueStrings([value, ...options]);
  return (
    <TaskSystemField label={label} wide={wide}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {resolvedOptions.map((item) => (
          <option disabled={isOptionDisabled?.(item) === true && item !== value} key={item} value={item}>{formatOption(item)}</option>
        ))}
      </select>
    </TaskSystemField>
  );
}

export function TaskSystemDomainTaskSelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  const resolvedOptions = value && !options.some((item) => item.value === value)
    ? [{ value, label: value }, ...options]
    : options;
  return (
    <TaskSystemField label={label}>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">不绑定</option>
        {resolvedOptions.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
    </TaskSystemField>
  );
}

export function TaskSystemMultiSelectField({
  label,
  value,
  options,
  onChange,
  wide = false,
  formatOption = taskSystemOptionLabel,
}: {
  label: string;
  value: string[];
  options: string[];
  onChange: (value: string[]) => void;
  wide?: boolean;
  formatOption?: (value: string) => string;
}) {
  const selected = new Set(value ?? []);
  return (
    <TaskSystemField label={label} wide={wide}>
      <div className="boundary-choice-grid">
        {uniqueStrings([...options, ...(value ?? [])]).map((item) => (
          <button
            className={selected.has(item) ? "boundary-choice boundary-choice--active" : "boundary-choice"}
            key={item}
            onClick={() => {
              const next = selected.has(item)
                ? (value ?? []).filter((current) => current !== item)
                : [...(value ?? []), item];
              onChange(next);
            }}
            type="button"
          >
            {formatOption(item)}
          </button>
        ))}
      </div>
    </TaskSystemField>
  );
}
