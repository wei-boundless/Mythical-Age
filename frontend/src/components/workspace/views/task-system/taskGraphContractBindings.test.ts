import { describe, expect, it } from "vitest";

import {
  edgePayloadContractIdOf,
  graphContractIdOf,
  nodeExecutionContractIdOf,
  nodeInputContractIdOf,
  nodeOutputContractIdOf,
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
});
