import { describe, expect, it } from "vitest";

import {
  cleanPublicTimelineText,
  isPublicTimelineControlItem,
  normalizePublicTimelineItems,
  publicTimelineExplicitOrderValue,
  sanitizePublicTimelineText,
} from "@/lib/projection/timeline";

describe("public timeline presentation helpers", () => {
  it("cleans spacing without hiding real file or artifact text", () => {
    expect(cleanPublicTimelineText("  A\t\tB\r\nC  ")).toBe("A B\nC");
    expect(sanitizePublicTimelineText("D:\\AI应用\\langchain-agent\\runtime_state\\tool-results\\result.txt"))
      .toBe("D:\\AI应用\\langchain-agent\\runtime_state\\tool-results\\result.txt");
  });

  it("suppresses generic machine status text", () => {
    expect(sanitizePublicTimelineText("正在思考")).toBe("");
    expect(sanitizePublicTimelineText("status: waiting_for_tool")).toBe("");
    expect(sanitizePublicTimelineText("已确认公开投影入口")).toBe("已确认公开投影入口");
  });

  it("recognizes control-only projection items", () => {
    expect(isPublicTimelineControlItem({
      item_id: "control:ask",
      kind: "status_update",
      slot: "control",
      surface: "control",
      title: "等待补充信息",
    })).toBe(true);
    expect(isPublicTimelineControlItem({
      item_id: "tool:read",
      kind: "work_action",
      slot: "tool",
      surface: "tool_window",
      title: "读取文件",
    })).toBe(false);
  });

  it("normalizes item order by backend sequence and removes body/control noise", () => {
    const items = normalizePublicTimelineItems([
      {
        item_id: "body:1",
        kind: "assistant_text",
        slot: "body",
        surface: "assistant_body",
        source_authority: "model",
        text: "正文交给 ChatMessage 渲染。",
        state: "running",
        sequence: 1,
      },
      {
        item_id: "event:3",
        kind: "status_update",
        slot: "timeline",
        surface: "timeline",
        title: "第三步",
        state: "waiting",
        sequence: 3,
      },
      {
        item_id: "event:2",
        kind: "work_action",
        slot: "tool",
        surface: "tool_window",
        action_kind: "read",
        title: "第二步",
        subject_label: "docs/a.md",
        state: "done",
        sequence: 2,
      },
      {
        item_id: "status:generic",
        kind: "status_update",
        slot: "status",
        surface: "status_bar",
        title: "正在处理",
        state: "running",
        sequence: 4,
      },
    ]);

    expect(items.map((item) => item.item_id)).toEqual(["event:2", "event:3"]);
  });

  it("keeps earliest order while merging semantic tool updates", () => {
    const items = normalizePublicTimelineItems([
      {
        item_id: "tool:read:start",
        kind: "work_action",
        slot: "tool",
        surface: "tool_window",
        action_kind: "read",
        title: "正在读取上下文",
        subject_label: "docs/a.md",
        state: "running",
        sequence: 4,
        source_event_id: "event:start",
      },
      {
        item_id: "tool:read:done",
        kind: "work_action",
        slot: "tool",
        surface: "tool_window",
        action_kind: "read",
        title: "已读取上下文",
        subject_label: "docs/a.md",
        state: "done",
        sequence: 9,
        source_event_id: "event:done",
      },
    ]);

    expect(items).toEqual([
      expect.objectContaining({
        item_id: "tool:read:done",
        title: "已读取上下文",
        state: "done",
        sequence: 4,
        source_event_id: "event:start",
        updated_event_offset: 9,
        updated_source_event_id: "event:done",
      }),
    ]);
  });

  it("computes explicit order from event offset before created time", () => {
    expect(publicTimelineExplicitOrderValue({
      kind: "status_update",
      title: "ordered",
      event_offset: 7,
      created_at: 123,
    })).toBe(7 + 123 / 1_000_000_000);
  });
});
