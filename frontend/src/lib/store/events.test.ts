import { describe, expect, it } from "vitest";

import { getDefaultState } from "./core";
import { reduceStreamEvent, startStreamingTurn } from "./events";

describe("store stream reducer", () => {
  it("appends optimistic user and assistant messages", () => {
    const transition = startStreamingTurn(getDefaultState(), "hello");
    expect(transition.state.messages).toHaveLength(2);
    expect(transition.state.messages[0].role).toBe("user");
    expect(transition.state.messages[1].role).toBe("assistant");
    expect(transition.state.messages[1].stageStatus).toBe("接收请求");
    expect(transition.state.isStreaming).toBe(true);
  });

  it("accumulates streamed assistant content", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "token",
      { content: "First " }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "token",
      { content: "response" }
    );
    expect(transition.state.messages[1].content).toBe("First response");
  });

  it("sanitizes internal skill reads while preserving visible tool results", () => {
    let transition = startStreamingTurn(getDefaultState(), "hello");
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "tool_start",
      { tool: "read_file", input: "capability_system/units/skills/demo/SKILL.md", output: "" }
    );
    expect(transition.state.messages[1].toolCalls).toHaveLength(0);

    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "tool_end",
      { output: "hidden" }
    );

    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "tool_start",
      { tool: "web_search", input: "OpenAI latest", output: "" }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "tool_end",
      { output: "search done" }
    );

    expect(transition.state.messages[1].toolCalls).toHaveLength(1);
    expect(transition.state.messages[1].toolCalls[0].tool).toBe("web_search");
    expect(transition.state.messages[1].toolCalls[0].output).toBe("search done");
  });

  it("uses done content when the assistant body stayed empty", () => {
    const initial = startStreamingTurn(getDefaultState(), "hello");
    const transition = reduceStreamEvent(
      initial.state,
      initial.session,
      "done",
      { content: "final answer" }
    );
    expect(transition.state.messages[1].content).toBe("final answer");
    expect(transition.state.messages[1].stageStatus).toBe("完成");
  });

  it("updates assistant stage from runtime loop events", () => {
    const initial = startStreamingTurn(getDefaultState(), "hello");
    const transition = reduceStreamEvent(
      initial.state,
      initial.session,
      "runtime_loop_event",
      { event: { event_type: "context_snapshot_built" } }
    );
    expect(transition.state.messages[1].stageStatus).toBe("整理上下文");
  });

  it("ignores debug trace events without corrupting message state", () => {
    const initial = startStreamingTurn(getDefaultState(), "hello");
    const transition = reduceStreamEvent(
      initial.state,
      initial.session,
      "debug",
      { kind: "langsmith_trace", trace_id: "trace-123" }
    );
    expect(transition.state.messages).toHaveLength(2);
    expect(transition.state.messages[1].content).toBe("");
    expect(transition.state.messages[1].toolCalls).toHaveLength(0);
    expect(transition.state.messages[1].stageStatus).toBe("接收请求");
  });
});
