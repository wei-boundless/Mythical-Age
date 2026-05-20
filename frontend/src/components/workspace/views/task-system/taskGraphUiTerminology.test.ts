import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const FORBIDDEN_TERMS = [
  "re" + "ceipt",
  "回" + "执",
  "required_" + "re" + "ceipt_status",
  "review_" + "re" + "ceipt",
  "current_clock_" + "re" + "ceipt",
  "by_" + "re" + "ceipt",
];

const TASK_GRAPH_UI_FILES = [
  "src/components/workspace/views/task-system/TaskGraphStudioShell.tsx",
  "src/components/workspace/views/task-system/TaskGraphLayerNav.tsx",
  "src/components/workspace/views/task-system/TaskGraphTopologyPage.tsx",
  "src/components/workspace/views/task-system/TaskGraphTimelinePage.tsx",
  "src/components/workspace/views/task-system/TaskGraphMemoryArtifactPage.tsx",
  "src/components/workspace/views/task-system/TaskGraphRiskGovernancePage.tsx",
  "src/components/workspace/views/task-system/TaskGraphResponsibilityPage.tsx",
  "src/components/workspace/views/task-system/TaskGraphContractQualityPage.tsx",
  "src/components/workspace/views/task-system/TaskGraphExecutionPackagePanel.tsx",
  "src/components/workspace/views/task-system/taskGraphCognitionView.ts",
  "src/components/workspace/views/task-system/taskGraphMemoryMatrix.ts",
];

describe("TaskGraph UI terminology", () => {
  it("does not expose unclear legacy confirmation wording in core editor files", () => {
    const hits = TASK_GRAPH_UI_FILES.flatMap((file) => {
      const absolute = path.join(process.cwd(), file);
      const content = readFileSync(absolute, "utf8");
      return FORBIDDEN_TERMS
        .filter((term) => content.includes(term))
        .map((term) => `${file}: ${term}`);
    });

    expect(hits).toEqual([]);
  });
});
