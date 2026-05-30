import { FileCheck2 } from "lucide-react";

import {
  contractBindingPathValue,
  mergeContractBindingPath,
  mergeContractBindingSection,
} from "./taskGraphContractBindings";
import { TaskGraphInspectorSection, TaskGraphObjectSelectField } from "./TaskGraphInspectorPrimitives";
import {
  TaskSystemField,
  TaskSystemSelectField,
  taskSystemOptionLabel,
} from "./TaskSystemWorkbenchUi";

type ContractBindingSectionId =
  | "schema"
  | "execution"
  | "memory"
  | "output"
  | "artifact"
  | "handoff"
  | "acceptance"
  | "runtime"
  | "temporal"
  | "governance";

type ContractBindingFieldSpec = {
  kind: "contract" | "text" | "number" | "select" | "boolean" | "list";
  label: string;
  path: string[];
  options?: string[];
  placeholder?: string;
  wide?: boolean;
};

type ContractBindingSectionSpec = {
  id: ContractBindingSectionId;
  title: string;
  aside: string;
  description: string;
  fields: ContractBindingFieldSpec[];
};

const CONTRACT_BINDING_SECTIONS: ContractBindingSectionSpec[] = [
  {
    id: "schema",
    title: "Schema",
    aside: "输入 / 输出 / 载荷",
    description: "声明这个对象接收、提交或交接的数据结构契约。",
    fields: [
      { kind: "contract", label: "图契约", path: ["graph_contract_id"], wide: true },
      { kind: "contract", label: "输入契约", path: ["input_contract_id"] },
      { kind: "contract", label: "输出契约", path: ["output_contract_id"] },
      { kind: "contract", label: "载荷契约", path: ["payload_contract_id"], wide: true },
    ],
  },
  {
    id: "execution",
    title: "Execution",
    aside: "执行协议",
    description: "声明节点如何被执行，以及执行端需要遵守的任务契约。",
    fields: [
      { kind: "contract", label: "节点执行契约", path: ["node_contract_id"], wide: true },
      { kind: "text", label: "执行器策略", path: ["executor_policy_ref"], placeholder: "executor policy / skill set", wide: true },
      { kind: "text", label: "工具集", path: ["toolset_ref"], placeholder: "toolset id" },
      { kind: "text", label: "Skill 集", path: ["skillset_ref"], placeholder: "skill bundle id" },
    ],
  },
  {
    id: "memory",
    title: "Memory",
    aside: "读写 / 动态记忆",
    description: "声明对象读取哪些记忆、写回哪些状态，以及是否需要提交后可见。",
    fields: [
      { kind: "text", label: "读取策略", path: ["memory_read_policy_ref"], placeholder: "memory read policy", wide: true },
      { kind: "text", label: "动态记忆读取", path: ["dynamic_memory_read_policy_ref"], placeholder: "dynamic memory policy", wide: true },
      { kind: "text", label: "写回策略", path: ["memory_writeback_policy_ref"], placeholder: "writeback policy", wide: true },
      { kind: "list", label: "交接记忆 Kind", path: ["working_memory_handoff_policy", "carry_kinds"], placeholder: "handoff_note, decision" },
      { kind: "list", label: "交接记忆 Scope", path: ["working_memory_handoff_policy", "carry_scopes"], placeholder: "edge_scope, artifact_scope" },
    ],
  },
  {
    id: "output",
    title: "Output",
    aside: "切分 / 落盘 / 登记",
    description: "声明模型输出如何抽取、验收、落盘并登记到产物区。",
    fields: [
      { kind: "contract", label: "输出政策", path: ["output_policy_ref"], wide: true },
      { kind: "text", label: "主内容键", path: ["primary_content_key"], placeholder: "final_answer / chapter_draft_text" },
      { kind: "text", label: "目标仓库", path: ["artifact_materialization_policy", "target_repository_id"], placeholder: "repo.writing.artifact_repository", wide: true },
      { kind: "text", label: "目标集合", path: ["artifact_materialization_policy", "target_collection_id"], placeholder: "chapter_drafts" },
      { kind: "boolean", label: "必须落盘", path: ["artifact_materialization_policy", "required"] },
    ],
  },
  {
    id: "artifact",
    title: "Artifact",
    aside: "产物 / 引用",
    description: "声明产物目标、引用方式和是否允许只传引用。",
    fields: [
      { kind: "text", label: "产物目标", path: ["artifact_policy", "artifact_target"], placeholder: "artifact target", wide: true },
      { kind: "select", label: "产物可见性", path: ["artifact_policy", "visibility_policy"], options: ["refs_only", "summary_and_refs", "contract_payload_and_refs"] },
      { kind: "boolean", label: "必须产出", path: ["artifact_policy", "required"] },
      { kind: "text", label: "引用策略", path: ["artifact_ref_policy_ref"], placeholder: "artifact ref policy", wide: true },
    ],
  },
  {
    id: "handoff",
    title: "Handoff",
    aside: "交接 / 确认",
    description: "声明边或图模块如何把上游结果交给下游。",
    fields: [
      { kind: "contract", label: "图模块交接契约", path: ["handoff_contract_id"], wide: true },
      { kind: "select", label: "确认策略", path: ["ack_policy"], options: ["explicit_ack", "implicit_ack", "manual_ack", "none"] },
      { kind: "boolean", label: "需要确认", path: ["ack_required"] },
      { kind: "select", label: "等待策略", path: ["wait_policy"], options: ["wait_all_upstream_completed", "wait_any_upstream_completed", "wait_required_contracts", "wait_handoff_ack", "fire_and_continue", "manual_release"] },
      { kind: "select", label: "失败传播", path: ["failure_propagation_policy"], options: ["fail_downstream", "isolate_failure", "allow_partial", "coordinator_decides"] },
      { kind: "select", label: "结果投递", path: ["result_delivery_policy"], options: ["contract_payload_and_refs", "summary_and_refs", "notification_only"] },
    ],
  },
  {
    id: "acceptance",
    title: "Acceptance",
    aside: "验收 / 人工门",
    description: "声明这个对象是否需要质量门、人工确认或审核结果。",
    fields: [
      { kind: "text", label: "审核策略", path: ["review_gate_policy_ref"], placeholder: "review gate policy", wide: true },
      { kind: "select", label: "人工门模式", path: ["human_gate_policy", "mode"], options: ["manual_required", "auto_continue", "non_blocking", "disabled"] },
      { kind: "boolean", label: "阻塞后续", path: ["human_gate_policy", "blocking"] },
      { kind: "text", label: "验收配置", path: ["acceptance_policy_ref"], placeholder: "acceptance policy id", wide: true },
    ],
  },
  {
    id: "runtime",
    title: "Runtime",
    aside: "模型需求 / 运行档案",
    description: "只声明模型能力需求；Provider、Base URL、密钥由系统配置和 Agent 运行档案解析。",
    fields: [
      { kind: "text", label: "模型档案", path: ["model_requirement", "profile_ref"], placeholder: "runtime profile ref" },
      { kind: "text", label: "Provider 家族", path: ["model_requirement", "provider_family"], placeholder: "deepseek / openai-compatible" },
      { kind: "number", label: "最小输出 tokens", path: ["model_requirement", "min_output_tokens"] },
      { kind: "number", label: "期望输出 tokens", path: ["model_requirement", "preferred_output_tokens"] },
      { kind: "list", label: "能力标签", path: ["model_requirement", "capability_tags"], placeholder: "long_output, reasoning", wide: true },
      { kind: "select", label: "流式要求", path: ["model_requirement", "streaming_required"], options: ["", "true", "false"] },
      { kind: "boolean", label: "启用长度预算验收", path: ["length_budget", "enabled"] },
      { kind: "select", label: "长度范围", path: ["length_budget", "budget_scope"], options: ["graph", "group", "batch", "node"] },
      { kind: "select", label: "长度计量", path: ["length_budget", "measurement_mode"], options: ["text_units", "tokens", "hybrid"] },
      { kind: "text", label: "工作单元", path: ["length_budget", "unit_kind"], placeholder: "unit / item / record" },
      { kind: "text", label: "中文单元", path: ["length_budget", "unit_label_zh"], placeholder: "单元 / 条目" },
      { kind: "number", label: "目标长度", path: ["length_budget", "target_units"] },
      { kind: "number", label: "最小长度", path: ["length_budget", "min_units"] },
      { kind: "number", label: "最大长度", path: ["length_budget", "max_units"] },
      { kind: "number", label: "单元数量", path: ["length_budget", "batch_unit_count"] },
      { kind: "select", label: "修复模式", path: ["length_budget", "repair_policy", "mode"], options: ["expand_or_split", "split_first", "expand_first"] },
      { kind: "number", label: "修复轮次", path: ["length_budget", "repair_policy", "max_repair_rounds"] },
      { kind: "boolean", label: "要求连续性", path: ["length_budget", "acceptance_policy", "require_continuity"] },
      { kind: "boolean", label: "要求正式标题", path: ["length_budget", "acceptance_policy", "require_formal_headings"] },
    ],
  },
  {
    id: "temporal",
    title: "Temporal",
    aside: "触发 / 可见",
    description: "声明交接在时序上的触发、可见和传播语义。",
    fields: [
      { kind: "select", label: "触发时机", path: ["trigger_timing"], options: ["after_source_success", "after_required_contracts", "after_source_commit", "manual_release", "phase_entry", "phase_exit"] },
      { kind: "select", label: "可见时机", path: ["visibility_timing"], options: ["same_clock", "next_clock", "after_commit", "next_iteration", "manual_release"] },
      { kind: "select", label: "确认时机", path: ["acknowledgement_timing"], options: ["explicit_ack", "implicit_ack", "ack_before_downstream", "ack_before_phase_exit", "none"] },
      { kind: "select", label: "传播策略", path: ["propagation_timing"], options: ["immediate", "buffer_until_commit", "summary_only", "refs_only", "blocked_on_failure"] },
    ],
  },
  {
    id: "governance",
    title: "Governance",
    aside: "风险 / 账本",
    description: "声明风险治理、线程账本和问题台账的通用策略引用。",
    fields: [
      { kind: "text", label: "线程账本策略", path: ["thread_ledger_policy_ref"], placeholder: "thread ledger policy", wide: true },
      { kind: "text", label: "问题台账策略", path: ["issue_ledger_policy_ref"], placeholder: "issue ledger policy", wide: true },
      { kind: "text", label: "上下文边界", path: ["context_boundary_policy_ref"], placeholder: "context boundary policy", wide: true },
    ],
  },
];

function stringValue(value: unknown, fallback = "") {
  const next = String(value ?? "").trim();
  return next || fallback;
}

function listText(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join(", ") : "";
}

function splitList(value: string) {
  return value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function fieldValue(target: Record<string, unknown>, section: string, path: string[]) {
  return contractBindingPathValue(target, section, path);
}

function nextValueForKind(kind: ContractBindingFieldSpec["kind"], value: string | boolean): unknown {
  if (kind === "boolean") return Boolean(value);
  if (kind === "number") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  if (kind === "list") return splitList(String(value));
  if (value === "true") return true;
  if (value === "false") return false;
  return value;
}

export function TaskGraphContractBindingInspector({
  contractOptions,
  fieldKeysBySection,
  formatContract,
  onChange,
  sections,
  target,
}: {
  contractOptions: string[];
  fieldKeysBySection?: Partial<Record<ContractBindingSectionId, string[]>>;
  formatContract: (contractId: string) => string;
  onChange: (patch: Record<string, unknown>) => void;
  sections?: ContractBindingSectionId[];
  target: Record<string, unknown>;
}) {
  const visibleSectionIds = new Set(sections ?? CONTRACT_BINDING_SECTIONS.map((item) => item.id));
  const visibleSections = CONTRACT_BINDING_SECTIONS.filter((section) => visibleSectionIds.has(section.id));

  const updateField = (section: ContractBindingSectionSpec, field: ContractBindingFieldSpec, value: string | boolean) => {
    onChange(mergeContractBindingPath(target, section.id, field.path, nextValueForKind(field.kind, value)));
  };

  return (
    <TaskGraphInspectorSection icon={<FileCheck2 aria-hidden="true" size={15} />} title="契约绑定" aside="contract_bindings">
      <div className="task-graph-contract-binding-inspector">
        {visibleSections.map((section) => (
          <section className="task-graph-contract-binding-section" key={section.id}>
            <header>
              <div>
                <strong>{section.title}</strong>
                <span>{section.description}</span>
              </div>
              <em>{section.aside}</em>
            </header>
            <div className="boundary-form task-graph-composer-inspector-form">
              {section.fields.filter((field) => {
                const allowed = fieldKeysBySection?.[section.id];
                return !allowed || allowed.includes(field.path.join("."));
              }).map((field) => {
                const value = fieldValue(target, section.id, field.path);
                const key = `${section.id}:${field.path.join(".")}`;
                if (field.kind === "contract") {
                  return (
                    <TaskGraphObjectSelectField
                      emptyLabel="未绑定契约"
                      formatOption={formatContract}
                      key={key}
                      label={field.label}
                      onChange={(next) => updateField(section, field, next)}
                      options={contractOptions}
                      value={stringValue(value)}
                      wide={field.wide ?? false}
                    />
                  );
                }
                if (field.kind === "select") {
                  const resolvedOptions = field.options ?? [];
                  return (
                    <TaskSystemSelectField
                      formatOption={taskSystemOptionLabel}
                      key={key}
                      label={field.label}
                      onChange={(next) => updateField(section, field, next)}
                      options={resolvedOptions}
                      value={typeof value === "boolean" ? String(value) : stringValue(value)}
                      wide={field.wide ?? false}
                    />
                  );
                }
                if (field.kind === "boolean") {
                  return (
                    <label className="boundary-check" key={key}>
                      <input checked={booleanValue(value)} onChange={(event) => updateField(section, field, event.target.checked)} type="checkbox" />
                      {field.label}
                    </label>
                  );
                }
                if (field.kind === "list") {
                  return (
                    <TaskSystemField key={key} label={field.label} wide={field.wide ?? false}>
                      <input onChange={(event) => updateField(section, field, event.target.value)} placeholder={field.placeholder} value={listText(value)} />
                    </TaskSystemField>
                  );
                }
                return (
                  <TaskSystemField key={key} label={field.label} wide={field.wide ?? false}>
                    <input
                      min={field.kind === "number" ? 0 : undefined}
                      onChange={(event) => updateField(section, field, event.target.value)}
                      placeholder={field.placeholder}
                      type={field.kind === "number" ? "number" : "text"}
                      value={stringValue(value)}
                    />
                  </TaskSystemField>
                );
              })}
            </div>
          </section>
        ))}
        <button
          className="task-graph-composer-subtle-action"
          onClick={() => onChange(mergeContractBindingSection(target, "governance", { contract_binding_reviewed: true }))}
          type="button"
        >
          标记契约绑定已核对
        </button>
      </div>
    </TaskGraphInspectorSection>
  );
}
