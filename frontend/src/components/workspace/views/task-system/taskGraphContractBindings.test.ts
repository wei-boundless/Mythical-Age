import { describe, expect, it } from "vitest";

import {
  edgePayloadContractIdOf,
  graphContractIdOf,
  nodeExecutionContractIdOf,
  nodeInputContractIdOf,
  nodeOutputContractIdOf,
  runtimeBatchAcceptancePolicyOf,
  runtimeMergePolicyOf,
  runtimeSplitPolicyOf,
  unitBatchContractOf,
} from "./taskGraphContractBindings";

describe("TaskGraph contract bindings", () => {
  it("reads explicit contract_bindings before legacy contract fields", () => {
    const graph = {
      graph_contract_id: "contract.legacy.graph",
      contract_bindings: { schema: { graph_contract_id: "contract.binding.graph" } },
    };
    const node = {
      input_contract_id: "contract.legacy.input",
      output_contract_id: "contract.legacy.output",
      node_contract_id: "contract.legacy.node",
      contract_bindings: {
        schema: {
          input_contract_id: "contract.binding.input",
          output_contract_id: "contract.binding.output",
        },
        execution: { node_contract_id: "contract.binding.node" },
      },
    };
    const edge = {
      payload_contract_id: "contract.legacy.payload",
      contract_bindings: { schema: { payload_contract_id: "contract.binding.payload" } },
    };

    expect(graphContractIdOf(graph)).toBe("contract.binding.graph");
    expect(nodeInputContractIdOf(node)).toBe("contract.binding.input");
    expect(nodeOutputContractIdOf(node)).toBe("contract.binding.output");
    expect(nodeExecutionContractIdOf(node)).toBe("contract.binding.node");
    expect(edgePayloadContractIdOf(edge)).toBe("contract.binding.payload");
  });

  it("reads split loop review merge contract sections from canonical bindings", () => {
    const node = {
      contract_bindings: {
        unit_batch: {
          unit_kind: "chapter",
          requested_count: 50,
        },
        runtime: {
          split_policy: {
            mode: "static_batch",
            batch_size: 10,
            child_execution_mode: "parallel",
            max_parallel_batches: 3,
          },
          batch_acceptance_policy: {
            mode: "review_then_commit",
          },
          merge_policy: {
            mode: "wait_all_committed",
          },
        },
      },
    };

    expect(unitBatchContractOf(node).unit_kind).toBe("chapter");
    expect(runtimeSplitPolicyOf(node).batch_size).toBe(10);
    expect(runtimeSplitPolicyOf(node).child_execution_mode).toBe("parallel");
    expect(runtimeSplitPolicyOf(node).max_parallel_batches).toBe(3);
    expect(runtimeBatchAcceptancePolicyOf(node).mode).toBe("review_then_commit");
    expect(runtimeMergePolicyOf(node).mode).toBe("wait_all_committed");
  });
});
