"use client";

export type ArtifactWorkspaceKind = "writing" | "code" | "research" | "data" | "general";

export type ArtifactWorkspaceCategory = {
  category_id: string;
  title: string;
  detail: string;
  keywords: string[];
};

export type ArtifactWorkspaceProfile = {
  kind: ArtifactWorkspaceKind;
  title: string;
  subtitle: string;
  categories: ArtifactWorkspaceCategory[];
};

const artifactWorkspaceProfiles: Record<ArtifactWorkspaceKind, ArtifactWorkspaceProfile> = {
  writing: {
    kind: "writing",
    title: "写作产物工作区",
    subtitle: "章节、设定、审稿意见和终稿围绕写作节点归档。",
    categories: [
      { category_id: "chapter", title: "章节稿", detail: "草稿、改稿和终稿", keywords: ["chapter", "draft", "final", "正文", "章节"] },
      { category_id: "world", title: "世界观", detail: "设定、人物、地点和规则", keywords: ["world", "character", "setting", "人物", "设定"] },
      { category_id: "review", title: "评审意见", detail: "审稿、修改建议和裁决", keywords: ["review", "revision", "feedback", "审稿", "修改"] },
    ],
  },
  code: {
    kind: "code",
    title: "代码产物工作区",
    subtitle: "补丁、diff、日志和报告围绕工程节点归档。",
    categories: [
      { category_id: "patch", title: "补丁与 Diff", detail: "文件变更、提交和补丁", keywords: ["diff", "patch", "commit", "change"] },
      { category_id: "report", title: "报告", detail: "测试、构建和诊断报告", keywords: ["test", "build", "report", "diagnostic", "log"] },
      { category_id: "file", title: "文件输出", detail: "生成文件和导出内容", keywords: ["file", "path", "output"] },
    ],
  },
  research: {
    kind: "research",
    title: "研究产物工作区",
    subtitle: "资料、证据、摘要和报告围绕研究节点归档。",
    categories: [
      { category_id: "source", title: "资料证据", detail: "来源、引用和证据链", keywords: ["source", "citation", "evidence", "reference"] },
      { category_id: "summary", title: "摘要", detail: "摘录、总结和比较", keywords: ["summary", "extract", "note"] },
      { category_id: "report", title: "研究报告", detail: "阶段结论和最终报告", keywords: ["report", "paper", "analysis"] },
    ],
  },
  data: {
    kind: "data",
    title: "数据产物工作区",
    subtitle: "表格、图表、指标和导出文件围绕数据节点归档。",
    categories: [
      { category_id: "table", title: "表格", detail: "数据集、CSV 和表格", keywords: ["table", "csv", "sheet", "dataset"] },
      { category_id: "chart", title: "图表", detail: "可视化和指标图", keywords: ["chart", "plot", "visual", "metric"] },
      { category_id: "export", title: "导出", detail: "结果文件和交付物", keywords: ["export", "output", "artifact"] },
    ],
  },
  general: {
    kind: "general",
    title: "产物工作区",
    subtitle: "节点输出、人工提交、工具结果和最终交付物。",
    categories: [
      { category_id: "node_output", title: "节点输出", detail: "Agent 和工具产物", keywords: ["node", "agent", "tool", "output"] },
      { category_id: "human", title: "人工提交", detail: "人工补充和确认内容", keywords: ["human", "manual", "submit"] },
      { category_id: "delivery", title: "交付物", detail: "最终产物和可发布结果", keywords: ["final", "delivery", "artifact"] },
    ],
  },
};

export function resolveArtifactWorkspaceProfile(input: {
  graphId?: string;
  title?: string;
  metadata?: Record<string, unknown>;
}) {
  const haystack = [
    input.graphId,
    input.title,
    input.metadata?.task_environment_kind,
    input.metadata?.domain_id,
    input.metadata?.template_id,
    input.metadata?.workspace_kind,
  ].map((value) => String(value ?? "").toLowerCase()).join(" ");
  if (/writing|novel|chapter|稿|写作|小说/.test(haystack)) return artifactWorkspaceProfiles.writing;
  if (/code|repo|diff|patch|test|build|代码|工程/.test(haystack)) return artifactWorkspaceProfiles.code;
  if (/research|source|citation|paper|研究|资料/.test(haystack)) return artifactWorkspaceProfiles.research;
  if (/data|dataset|chart|csv|table|数据|图表/.test(haystack)) return artifactWorkspaceProfiles.data;
  return artifactWorkspaceProfiles.general;
}

export function categoryForArtifact(
  artifact: Record<string, unknown>,
  profile: ArtifactWorkspaceProfile,
) {
  const haystack = [
    artifact.title,
    artifact.path,
    artifact.artifact_id,
    artifact.kind,
    artifact.status,
    artifact.summary,
    artifact.description,
  ].map((value) => String(value ?? "").toLowerCase()).join(" ");
  return profile.categories.find((category) => (
    category.keywords.some((keyword) => haystack.includes(keyword.toLowerCase()))
  )) ?? profile.categories[0];
}
