import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

(globalThis as typeof globalThis & { React: typeof React }).React = React;

const setActiveTaskEnvironment = vi.fn();
const setWorkspaceView = vi.fn();

vi.mock("@/components/chat/ChatPanel", () => ({
  ChatPanel: () => React.createElement("section", { "aria-label": "mock chat panel" }, "chat panel"),
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => ({
    centerWorkspaceTarget: null,
    clearCenterWorkspaceTarget: vi.fn(),
    conversationActiveEnvironment: {
      environment_label: "通用工作区",
      task_environment_id: "env.general.workspace",
    },
    currentSessionId: "session-test",
    inspectorDirty: false,
    sessionEditorContexts: {},
    setActiveTaskEnvironment,
    setSessionEditorPageState: vi.fn(),
    setWorkspaceView,
    taskEnvironmentCatalog: {
      environments: [
        {
          management_scope: "builtin_template",
          record: { enabled: true, environment_id: "env.coding.vibe_workspace", title: "Vibe 编码工作区" },
        },
        {
          management_scope: "builtin_template",
          record: { enabled: true, environment_id: "env.general.workspace", title: "通用工作区" },
        },
      ],
    },
    taskEnvironmentCatalogError: "",
    taskEnvironmentCatalogLoading: false,
    taskGraphMonitorBinding: null,
  }),
}));

import { CenterWorkspaceView } from "./CenterWorkspaceView";

describe("CenterWorkspaceView", () => {
  it("keeps the task environment switcher visible beside the chat base layer", () => {
    const html = renderToStaticMarkup(React.createElement(CenterWorkspaceView));

    expect(html).toContain("中心层级切换");
    expect(html).toContain("会话底层");
    expect(html).toContain("图任务层");
    expect(html).toContain("center-workspace__body");
    expect(html).toContain("切换当前会话任务环境");
    expect(html).toContain("Vibe 编码工作区");
    expect(html).toContain("通用工作区");
    expect(html).toContain("center-workspace__environment-switcher");
  });
});
