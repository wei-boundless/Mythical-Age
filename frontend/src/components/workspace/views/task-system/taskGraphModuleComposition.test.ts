import { describe, expect, it } from "vitest";

import {
  removeTaskGraphOverlayPortEdge,
  TASK_GRAPH_MODULE_FACET_ITEMS,
  taskGraphComposableOverlayFromMetadata,
  taskGraphModuleFacetFromEditorFocus,
  upsertTaskGraphOverlayPortEdge,
} from "./taskGraphModuleComposition";

describe("TaskGraph module composition facets", () => {
  it("keeps publish diagnostics on the matching module facet", () => {
    expect(taskGraphModuleFacetFromEditorFocus("connections")).toBe("connections");
    expect(taskGraphModuleFacetFromEditorFocus("interfaces")).toBe("interfaces");
    expect(taskGraphModuleFacetFromEditorFocus("nested_runtime")).toBe("nested_runtime");
    expect(taskGraphModuleFacetFromEditorFocus("units")).toBe("units");
  });

  it("maps timeline block focus to the stitching facet", () => {
    expect(taskGraphModuleFacetFromEditorFocus("blocks")).toBe("stitching");
  });

  it("falls back to unit composition for unknown focus facets", () => {
    expect(taskGraphModuleFacetFromEditorFocus(undefined)).toBe("units");
    expect(taskGraphModuleFacetFromEditorFocus("unknown")).toBe("units");
  });

  it("keeps the layer switch list aligned with the supported facets", () => {
    expect(TASK_GRAPH_MODULE_FACET_ITEMS.map((item) => item.id)).toEqual([
      "units",
      "interfaces",
      "connections",
      "nested_runtime",
      "stitching",
    ]);
  });

  it("reads and updates the composable graph overlay port edges", () => {
    const metadata = {
      keep: "unchanged",
      composable_graph: {
        version: "v1",
        port_edges: [
          {
            edge_id: "port_edge.one",
            source_unit_id: "unit.a",
            source_port_id: "output.default",
            target_unit_id: "unit.b",
            target_port_id: "input.default",
          },
        ],
      },
    };

    const initial = taskGraphComposableOverlayFromMetadata(metadata);
    expect(initial.port_edges).toHaveLength(1);

    const upserted = upsertTaskGraphOverlayPortEdge(metadata, {
      edge_id: "port_edge.two",
      source_unit_id: "unit.b",
      source_port_id: "output.default",
      target_unit_id: "unit.c",
      target_port_id: "input.default",
      payload_contract_id: "contract.test",
      edge_type: "handoff",
      temporal_semantics: { trigger_timing: "after_source_success" },
      handoff: {},
      metadata: {},
    });

    expect(upserted.composable_graph.port_edges).toHaveLength(2);
    expect(upserted.composable_graph.port_edges[1]?.metadata?.explicit_overlay).toBe(true);

    const removed = removeTaskGraphOverlayPortEdge({ composable_graph: upserted.composable_graph }, "port_edge.one");
    expect(removed.composable_graph.port_edges.map((edge) => edge.edge_id)).toEqual(["port_edge.two"]);
  });
});
