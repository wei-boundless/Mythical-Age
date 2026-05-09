"use client";

import type { Dispatch, SetStateAction } from "react";

import {
  TaskSystemField,
  TaskSystemSelectField,
} from "@/components/workspace/views/task-system/TaskSystemWorkbenchUi";
import { contractSpecTitle } from "@/components/workspace/views/task-system/ContractLibraryPanel";
import type { ContractSpec, SpecificTaskRecord } from "@/lib/api";

function contractOptions(specs: ContractSpec[], value: string, kinds: string[] = []) {
  const allowed = kinds.length ? specs.filter((item) => kinds.includes(item.contract_kind)) : specs;
  return Array.from(new Set([value, ...allowed.map((item) => item.contract_id)].filter(Boolean)));
}

function formatContract(specs: ContractSpec[]) {
  return (contractId: string) => {
    const spec = specs.find((item) => item.contract_id === contractId);
    return spec ? `${contractSpecTitle(spec)} · ${contractId}` : contractId || "不绑定";
  };
}

export function TaskContractPanel({
  contractSpecs,
  taskDraft,
  setTaskDraft,
  workflowOutputContractId,
  onWorkflowOutputContractChange,
}: {
  contractSpecs: ContractSpec[];
  taskDraft: SpecificTaskRecord;
  setTaskDraft: Dispatch<SetStateAction<SpecificTaskRecord>>;
  workflowOutputContractId: string;
  onWorkflowOutputContractChange: (contractId: string) => void;
}) {
  const formatter = formatContract(contractSpecs);
  return (
    <section className="boundary-inspector-block">
      <header>
        <strong>任务契约</strong>
        <span>契约规格</span>
      </header>
      <div className="boundary-form">
        <TaskSystemSelectField
          label="默认输入契约"
          value={taskDraft.input_contract_id || ""}
          options={contractOptions(contractSpecs, taskDraft.input_contract_id || "", ["global_task", "workflow", "node_execution"])}
          onChange={(value) => setTaskDraft((current) => ({ ...current, input_contract_id: value }))}
          formatOption={formatter}
        />
        <TaskSystemSelectField
          label="默认输出契约"
          value={taskDraft.output_contract_id || ""}
          options={contractOptions(contractSpecs, taskDraft.output_contract_id || "", ["final_output", "workflow", "workflow_step", "node_execution"])}
          onChange={(value) => setTaskDraft((current) => ({ ...current, output_contract_id: value }))}
          formatOption={formatter}
        />
        <TaskSystemSelectField
          label="工作流输出契约"
          value={workflowOutputContractId || ""}
          options={contractOptions(contractSpecs, workflowOutputContractId || "", ["final_output", "workflow", "workflow_step"])}
          onChange={onWorkflowOutputContractChange}
          formatOption={formatter}
          wide
        />
        <TaskSystemField label="验收画像">
          <input value={taskDraft.acceptance_profile_id || ""} onChange={(event) => setTaskDraft((current) => ({ ...current, acceptance_profile_id: event.target.value }))} />
        </TaskSystemField>
      </div>
    </section>
  );
}
