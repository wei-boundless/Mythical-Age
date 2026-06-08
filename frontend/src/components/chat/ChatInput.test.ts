import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatInput } from "./ChatInput";

function renderChatInput(
  props: Partial<React.ComponentProps<typeof ChatInput>> = {},
) {
  return renderToStaticMarkup(
    React.createElement(ChatInput, {
      chatThinkingMode: "normal",
      disabled: false,
      imageAssetConfig: null,
      modelProviderConfig: null,
      onSelectChatModel: () => undefined,
      onSelectPermissionMode: () => undefined,
      onSelectStreamDisplayEnabled: () => undefined,
      onSelectThinkingMode: () => undefined,
      onSend: async () => undefined,
      onStop: () => undefined,
      permissionMode: "default",
      selectedChatModelId: "system-default",
      chatStreamDisplayEnabled: true,
      streaming: false,
      supportedPermissionModes: ["default"],
      taskPrimaryAction: null,
      ...props,
    }),
  );
}

describe("ChatInput", () => {
  it("does not expose a continuation button when the composer is empty", () => {
    const html = renderChatInput();

    expect(html).toContain("aria-label=\"发送\"");
    expect(html).not.toContain("继续当前任务");
    expect(html).not.toContain("chat-send-button--resume");
  });

  it("keeps interruption as the only task-level primary action", () => {
    const html = renderChatInput({
      taskPrimaryAction: {
        kind: "interrupt",
        onAction: () => undefined,
      },
    });

    expect(html).toContain("aria-label=\"中断当前任务\"");
    expect(html).not.toContain("继续当前任务");
    expect(html).not.toContain("chat-send-button--resume");
  });

  it("renders a stream display toggle", () => {
    const html = renderChatInput({ chatStreamDisplayEnabled: false });

    expect(html).toContain("aria-label=\"开启流式显示\"");
    expect(html).toContain("aria-pressed=\"false\"");
    expect(html).toContain("流式");
  });

  it("locks the stream display toggle to the next turn while streaming", () => {
    const html = renderChatInput({ streaming: true });

    expect(html).toContain("aria-label=\"关闭流式显示\"");
    expect(html).toContain("title=\"本轮运行中，下一轮可切换流式显示\"");
    expect(html).toContain("aria-label=\"停止本轮生成\"");
  });
});
