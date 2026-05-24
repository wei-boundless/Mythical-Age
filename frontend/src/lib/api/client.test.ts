import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest, getApiBase } from "./client";
import { streamChat } from "../api";

describe("api client base URL", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the fixed backend API in a plain browser session", () => {
    vi.stubGlobal("window", {});

    expect(getApiBase()).toBe("http://127.0.0.1:8003/api");
  });

  it("uses the host-injected API base when Electron provides one", () => {
    vi.stubGlobal("window", {
      mythicalAgentHost: {
        getConfig: () => ({ apiBase: "http://127.0.0.1:8003/api/" }),
      },
    });

    expect(getApiBase()).toBe("http://127.0.0.1:8003/api");
  });
});

describe("apiRequest", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("normalizes request timeouts instead of surfacing a raw AbortError", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    })));

    const pending = expect(apiRequest("/sessions", { method: "POST", body: "{}" })).rejects.toMatchObject({
      name: "RequestTimeoutError",
      message: "Request timed out after 5000ms: /sessions",
    });
    await vi.advanceTimersByTimeAsync(5000);

    await pending;
  });
});

describe("streamChat", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("finishes as soon as a terminal SSE event arrives", async () => {
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const chunks = [
      new TextEncoder().encode('event: content_delta\ndata: {"content":"你好"}\n\n'),
      new TextEncoder().encode('event: done\ndata: {"content":"你好"}\n\n'),
    ];
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: chunks[0], done: false })
        .mockResolvedValueOnce({ value: chunks[1], done: false })
        .mockImplementation(() => new Promise(() => undefined)),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const result = await streamChat(
      { message: "你好", session_id: "session:fixed" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    expect(result).toEqual({ terminalEvent: "done" });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(reader.read).toHaveBeenCalledTimes(2);
    expect(events.map((item) => item.event)).toEqual(["content_delta", "done"]);
  });

  it("parses CRLF-delimited SSE terminal events", async () => {
    vi.stubGlobal("window", {});
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({
          value: new TextEncoder().encode('event: done\r\ndata: {"content":"ok"}\r\n\r\n'),
          done: true,
        }),
      cancel: vi.fn(),
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const result = await streamChat(
      { message: "hi", session_id: "session:crlf" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );

    expect(result).toEqual({ terminalEvent: "done" });
    expect(reader.cancel).not.toHaveBeenCalled();
    expect(events).toEqual([{ event: "done", data: { content: "ok" } }]);
  });

  it("synthesizes done after a stable output boundary when backend keeps running", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const chunks = [
      new TextEncoder().encode(
        'event: output_boundary\ndata: {"output":{"visible_text":"你好，我是四岳。","selected_channel":"answer_candidate","selected_source":"model_response"}}\n\n'
      ),
    ];
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: chunks[0], done: false })
        .mockImplementation(() => new Promise(() => undefined)),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:stable" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    await vi.advanceTimersByTimeAsync(8000);
    const result = await pending;

    expect(result).toEqual({
      terminalEvent: "done",
      synthesized: true,
      syntheticReason: "stable_answer",
    });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events.map((item) => item.event)).toEqual(["output_boundary", "done"]);
    expect(events.at(-1)?.data).toMatchObject({
      content: "你好，我是四岳。",
      synthesized: true,
      terminal_reason: "frontend_stable_answer",
    });
  });

  it("releases the stream when no visible answer arrives before the frontend timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const reader = {
      read: vi.fn().mockImplementation(() => new Promise(() => undefined)),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:no-visible" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    await vi.advanceTimersByTimeAsync(90000);
    const result = await pending;

    expect(result).toEqual({
      terminalEvent: "error",
      synthesized: true,
      syntheticReason: "no_visible_answer",
    });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: "error",
      data: {
        terminal_reason: "frontend_no_visible_answer_timeout",
        synthesized: true,
      },
    });
    expect(String(events[0].data.error)).toContain("已释放输入区");
  });

  it("releases the stream when visible deltas arrive but the backend never closes", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", {});
    const cancel = vi.fn(async () => undefined);
    const chunks = [
      new TextEncoder().encode('event: content_delta\ndata: {"content":"你好"}\n\n'),
    ];
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: chunks[0], done: false })
        .mockImplementation(() => new Promise(() => undefined)),
      cancel,
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      body: { getReader: () => reader },
    })));
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];

    const pending = streamChat(
      { message: "你好", session_id: "session:visible-idle" },
      { onEvent: (event, data) => events.push({ event, data }) },
    );
    await vi.advanceTimersByTimeAsync(45000);
    const result = await pending;

    expect(result).toEqual({
      terminalEvent: "error",
      synthesized: true,
      syntheticReason: "no_visible_answer",
    });
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(events.map((item) => item.event)).toEqual(["content_delta", "error"]);
    expect(events.at(-1)?.data).toMatchObject({
      terminal_reason: "frontend_visible_answer_idle_timeout",
      synthesized: true,
    });
  });
});
