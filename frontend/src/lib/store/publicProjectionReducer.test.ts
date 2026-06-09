import { describe, expect, it } from "vitest";

import { getDefaultState } from "./core";
import { reduceStreamEvent, startStreamingTurn } from "./events";

describe("public projection reducer contract", () => {
  it("renders body only from explicit model body slot in a public projection envelope", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:body",
        lifecycle: "running",
        source_authority: "model",
        surface: "assistant_body",
        items: [
          {
            item_id: "body:1",
            kind: "stage_summary",
            slot: "body",
            surface: "assistant_body",
            source_authority: "model",
            text: "I am checking the projection chain.",
            state: "running",
          },
        ],
      },
    });

    expect(transition.state.messages.at(-1)?.content).toBe("I am checking the projection chain.");
  });

  it("fails closed for body-looking projection items without explicit slot", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "assistant_text", {
      public_projection_envelope: {
        authority: "harness.public_projection.v1",
        projection_id: "publicproj:no-slot",
        lifecycle: "running",
        source_authority: "model",
        surface: "assistant_body",
        items: [
          {
            item_id: "legacy-body",
            kind: "final_summary",
            surface: "assistant_body",
            source_authority: "model",
            text: "Legacy body must not render.",
            state: "done",
          },
        ],
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.runtimePublicTimelineDraft).toEqual([]);
  });

  it("does not use done content as an assistant body fallback", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "done", {
      content: "Done content must not become visible body.",
      answer_channel: "conversation",
      answer_source: "model",
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.stageStatus).toBe("完成");
  });

  it("ignores legacy public timeline delta without an envelope", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_step_summary", {
      public_timeline_delta: [
        {
          item_id: "body:legacy",
          kind: "final_summary",
          slot: "body",
          surface: "assistant_body",
          source_authority: "model",
          text: "Legacy delta must not render.",
          state: "done",
        },
      ],
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.content).toBe("");
    expect(assistant?.runtimePublicTimelineDraft).toEqual([]);
  });

  it("still attaches task projection carried by a raw monitor event", () => {
    let transition = startStreamingTurn(getDefaultState(), "run task");
    transition = reduceStreamEvent(transition.state, transition.session, "runtime_status", {
      task_projection_delta: {
        authority: "harness.runtime.single_agent_task_projection.v1",
        projection_id: "projection:taskrun:test",
        task_run_id: "taskrun:test",
        status: "running",
      },
    });

    const assistant = transition.state.messages.at(-1);
    expect(assistant?.runtimeAttachments?.[0]?.task_projection).toMatchObject({
      task_run_id: "taskrun:test",
      status: "running",
    });
  });
});
