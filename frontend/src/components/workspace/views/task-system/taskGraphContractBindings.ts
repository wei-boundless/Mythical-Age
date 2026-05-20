import { asRecord } from "./taskGraphDraftV2";

export function contractBindingValue(target: Record<string, unknown>, section: string, key: string): string {
  return String(asRecord(asRecord(target.contract_bindings)[section])[key] ?? "").trim();
}

export function graphContractIdOf(graph: Record<string, unknown>): string {
  return contractBindingValue(graph, "schema", "graph_contract_id") || String(graph.graph_contract_id ?? "").trim();
}

export function nodeInputContractIdOf(node: Record<string, unknown>): string {
  return contractBindingValue(node, "schema", "input_contract_id") || String(node.input_contract_id ?? "").trim();
}

export function nodeOutputContractIdOf(node: Record<string, unknown>): string {
  return contractBindingValue(node, "schema", "output_contract_id") || String(node.output_contract_id ?? "").trim();
}

export function nodeExecutionContractIdOf(node: Record<string, unknown>): string {
  return contractBindingValue(node, "execution", "node_contract_id") || String(node.node_contract_id ?? node.contract_id ?? "").trim();
}

export function edgePayloadContractIdOf(edge: Record<string, unknown>): string {
  return contractBindingValue(edge, "schema", "payload_contract_id") || String(edge.payload_contract_id ?? edge.contract_id ?? "").trim();
}

export function mergeContractBindingSection(
  target: Record<string, unknown>,
  section: string,
  patch: Record<string, unknown>,
): { contract_bindings: Record<string, unknown> } {
  const current = asRecord(target.contract_bindings);
  return {
    contract_bindings: {
      ...current,
      [section]: {
        ...asRecord(current[section]),
        ...patch,
      },
    },
  };
}

export function runtimeModelRequirementOf(target: Record<string, unknown>): Record<string, unknown> {
  return asRecord(asRecord(asRecord(target.contract_bindings).runtime).model_requirement);
}

export function mergeRuntimeModelRequirement(
  target: Record<string, unknown>,
  patch: Record<string, unknown>,
): { contract_bindings: Record<string, unknown> } {
  const current = asRecord(target.contract_bindings);
  const runtime = asRecord(current.runtime);
  const currentRequirement = asRecord(runtime.model_requirement);
  const nextRequirement = Object.fromEntries(
    Object.entries({
      ...currentRequirement,
      ...patch,
    }).filter(([, value]) => value !== "" && value !== null && value !== undefined && !(Array.isArray(value) && value.length === 0)),
  );
  return {
    contract_bindings: {
      ...current,
      runtime: {
        ...runtime,
        model_requirement: nextRequirement,
      },
    },
  };
}
