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
      onSelectThinkingMode: () => undefined,
      onSend: async () => undefined,
      onStop: () => undefined,
      permissionMode: "default",
      selectedChatModelId: "system-default",
      streaming: false,
      supportedPermissionModes: ["default"],
      ...props,
    }),
  );
}

describe("ChatInput", () => {
  it("does not expose a continuation button when the composer is empty", () => {
    const html = renderChatInput();

    expect(html).toContain("aria-label=\"发送\"");
    expect(html).not.toContain("继续当前任务");
    expect(html).not.toContain("暂停当前任务");
    expect(html).not.toContain("停止当前任务");
    expect(html).not.toContain("chat-send-button--resume");
  });

  it("renders model and thinking mode as separate controls", () => {
    const html = renderChatInput({
      chatThinkingMode: "thinking",
      modelProviderConfig: {
        provider: "deepseek",
        model: "deepseek-v4-flash",
        base_url: "https://api.deepseek.com",
        api_key_configured: true,
        fallback_provider: "",
        fallback_model: "",
        fallback_base_url: "",
        fallback_api_key_configured: false,
        supported_providers: {
          deepseek: {
            provider: "deepseek",
            default_model: "deepseek-v4-flash",
            default_base_url: "https://api.deepseek.com",
            model_presets: ["deepseek-v4-pro"],
            capability_tags: ["reasoning"],
          },
        },
        authority: "test",
      },
    });

    expect(html).toContain("aria-label=\"选择本轮模型\"");
    expect(html).toContain("aria-label=\"选择思考模式\"");
    expect(html).toContain("deepseek-v4-flash");
    expect(html).toContain("Thinking");
    expect(html).not.toContain("deepseek-v4-flash · Thinking");
    expect(html).not.toContain("aria-label=\"开启流式显示\"");
    expect(html).not.toContain("aria-label=\"关闭流式显示\"");
  });

  it("renders an image input for uploads and pasted image handoff", () => {
    const html = renderChatInput();

    expect(html).toContain("aria-label=\"上传图片\"");
    expect(html).toContain("aria-label=\"选择图片\"");
    expect(html).toContain("accept=\".png,.jpg,.jpeg,.webp,.bmp,.tiff,.tif");
    expect(html).toContain("type=\"file\"");
  });

  it("uses the primary action as stop while streaming without showing a stream toggle", () => {
    const html = renderChatInput({ streaming: true });

    expect(html).not.toContain("流式");
    expect(html).toContain("aria-label=\"停止本轮生成\"");
  });
});
