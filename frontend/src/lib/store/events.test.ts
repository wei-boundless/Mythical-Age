import type { TaskSelectionState } from "./types";
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

  it("binds task selection into the orchestration snapshot", () => {
    const taskSelection: TaskSelectionState = {
      selected_task_id: "task.writing.chapter_drafting",
      coordination_task_id: "coord.writing.chapter_pipeline",
      mode: "coordination",
      label: "长篇小说章节协作流水线"
    };
    const state = {
      ...getDefaultState(),
      taskSelection
    };
    const transition = startStreamingTurn(state, "请启动任务");
    expect(transition.state.orchestrationSnapshot?.events?.[0]?.event).toBe("task_selection_bound");
    expect(String(transition.state.orchestrationSnapshot?.events?.[0]?.summary ?? "")).toContain("coord.writing.chapter_pipeline");
  });

  it("records coordination runtime events into orchestration snapshot for live highlighting", () => {
    let transition = startStreamingTurn(getDefaultState(), "启动长篇协调");
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "coordination_flow_registered",
          payload: {
            coordination_flow: {
              current_stage_id: "novel_bible",
              next_task_ref: "task.writing.novel_bible_build",
              stages: [
                { stage_id: "project_scope", node_id: "project_scope", status: "completed", task_ref: "task.writing.longform_novel_project" },
                { stage_id: "novel_bible", node_id: "novel_bible", status: "running", task_ref: "task.writing.novel_bible_build" }
              ]
            }
          }
        }
      }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "agent_run_updated",
          payload: {
            agent_run: {
              agent_run_id: "agrun:test:novel-bible",
              agent_profile_id: "longform_plot_agent",
              agent_id: "agent:21",
              role: "participant",
              status: "running",
              coordination_run_ref: "coordrun:test",
              diagnostics: {
                node_id: "novel_bible"
              }
            }
          }
        }
      }
    );
    const snapshot = transition.state.orchestrationSnapshot;
    expect(snapshot).not.toBeNull();
    const serialized = JSON.stringify(snapshot);
    expect(serialized).toContain("coordination_flow");
    expect(serialized).toContain("agent_run_updated");
    expect(serialized).toContain("novel_bible");
    expect(serialized).toContain("longform_plot_agent");
    expect(serialized).toContain("task.writing.novel_bible_build");
  });

  it("preserves sequential coordination flow signals through volume planning handoff", () => {
    let transition = startStreamingTurn(getDefaultState(), "继续推进长篇任务");
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "coordination_flow_registered",
          payload: {
            coordination_flow: {
              current_stage_id: "novel_bible",
              stages: [
                { stage_id: "project_scope", node_id: "project_scope", status: "completed", task_ref: "task.writing.longform_novel_project" },
                { stage_id: "novel_bible", node_id: "novel_bible", status: "running", task_ref: "task.writing.novel_bible_build" },
                { stage_id: "volume_planning", node_id: "volume_planning", status: "pending", task_ref: "task.writing.volume_planning" }
              ]
            }
          }
        }
      }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "coordination_node_run_updated",
          payload: {
            coordination_node_run: {
              node_run_id: "coordnode:test:novel_bible",
              coordination_run_id: "coordrun:test",
              node_id: "novel_bible",
              role: "participant",
              assigned_agent_run_ref: "agrun:test:novel-bible",
              status: "running",
              diagnostics: {
                stage_id: "novel_bible",
                stage_status: "running"
              }
            }
          }
        }
      }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "agent_run_updated",
          payload: {
            agent_run: {
              agent_run_id: "agrun:test:novel-bible",
              agent_profile_id: "longform_plot_agent",
              agent_id: "agent:21",
              role: "participant",
              status: "running",
              coordination_run_ref: "coordrun:test",
              diagnostics: {
                node_id: "novel_bible"
              }
            }
          }
        }
      }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "coordination_flow_advanced",
          payload: {
            coordination_flow: {
              current_stage_id: "volume_planning",
              stages: [
                { stage_id: "project_scope", node_id: "project_scope", status: "completed", task_ref: "task.writing.longform_novel_project" },
                { stage_id: "novel_bible", node_id: "novel_bible", status: "completed", task_ref: "task.writing.novel_bible_build" },
                { stage_id: "volume_planning", node_id: "volume_planning", status: "running", task_ref: "task.writing.volume_planning" }
              ]
            }
          }
        }
      }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "coordination_node_run_updated",
          payload: {
            coordination_node_run: {
              node_run_id: "coordnode:test:volume_planning",
              coordination_run_id: "coordrun:test",
              node_id: "volume_planning",
              role: "participant",
              assigned_agent_run_ref: "agrun:test:volume-planning",
              status: "running",
              diagnostics: {
                stage_id: "volume_planning",
                stage_status: "running"
              }
            }
          }
        }
      }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "agent_run_updated",
          payload: {
            agent_run: {
              agent_run_id: "agrun:test:volume-planning",
              agent_profile_id: "longform_plot_agent",
              agent_id: "agent:22",
              role: "participant",
              status: "running",
              coordination_run_ref: "coordrun:test",
              diagnostics: {
                node_id: "volume_planning"
              }
            }
          }
        }
      }
    );
    transition = reduceStreamEvent(
      transition.state,
      transition.session,
      "runtime_loop_event",
      {
        event: {
          event_type: "handoff_envelope_created",
          payload: {
            handoff_envelope: {
              handoff_id: "handoff:coordrun:test:1",
              source_agent_run_ref: "agrun:test:novel-bible",
              target_agent_run_ref: "agrun:test:volume-planning",
              message_type: "structured_handoff",
              ack_state: "pending"
            }
          }
        }
      }
    );

    const snapshot = transition.state.orchestrationSnapshot;
    const serialized = JSON.stringify(snapshot);
    expect(serialized).toContain("volume_planning");
    expect(serialized).toContain("coordination_flow_advanced");
    expect(serialized).toContain("handoff_envelope_created");
    expect(serialized).toContain("agrun:test:volume-planning");
  });
});
