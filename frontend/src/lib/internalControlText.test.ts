import { describe, expect, it } from "vitest";

import { isInternalActiveWorkControlText, isInternalControlProtocolText } from "./internalControlText";

describe("internal control text boundary", () => {
  it("does not hide canonical prose that discusses active work control terms", () => {
    const prose = [
      "控制系统中 active_work_control 负责处理 continue_active_work、ask_user 等控制信号。",
      "这段内容是在解释 agent 控制周期，不是运行时协议对象。",
    ].join("\n");

    expect(isInternalActiveWorkControlText(prose)).toBe(false);
    expect(isInternalControlProtocolText(prose)).toBe(false);
  });

  it("hides raw active work control protocol objects", () => {
    const rawAction = '{"authority":"harness.loop.model_action_request","action_type":"active_work_control","active_work_control":{"action":"continue_active_work"}}';

    expect(isInternalActiveWorkControlText(rawAction)).toBe(true);
    expect(isInternalControlProtocolText(rawAction)).toBe(true);
  });

  it("keeps explanatory prose even when it mentions model routing terms", () => {
    const narration = "好，用户说“继续”，指向当前活跃工作。用 answer_then_continue_active_work 简短确认后继续推进。";

    expect(isInternalActiveWorkControlText(narration)).toBe(false);
    expect(isInternalControlProtocolText(narration)).toBe(false);
  });

  it("hides a whole leaked internal action contract prompt", () => {
    const prompt = [
      "系统运行控制观察如下。它不是最终回复，而是交给你的收口信号。",
      "{\"required_action_protocol\":{\"authority\":\"harness.loop.model_action_request\",\"allowed_action_types\":[\"respond\",\"ask_user\",\"block\"]}}",
      "你现在是本轮收口负责人。你不能再调用工具，也不能在 JSON 外输出正文。",
      "你只能输出一个 JSON action，authority 必须是 harness.loop.model_action_request，action_type 只能是 respond、ask_user 或 block。",
    ].join("\n");

    expect(isInternalControlProtocolText(prompt)).toBe(true);
  });

  it("hides legacy deterministic closeout prose that was written by runtime fallback", () => {
    const closeout = [
      "本轮没有拿到可继续执行的有效下一步，我已停止继续动作，避免重复执行或误执行。",
      "已完成：已有 2 个工具结果成功返回。",
      "未完成：后续验证或收口动作没有继续执行，因为本轮可用工具步数已经用完。",
      "下一步：你可以直接说“继续”，我会从已确认事实继续，并优先核对上一步产物或失败点。",
    ].join("\n");

    expect(isInternalControlProtocolText(closeout)).toBe(true);
  });
});
