import type { GraphInstanceWorkspaceExtension, GraphTemplateRecord } from "../templates/graphTemplateTypes";
import { builtInGraphTemplates } from "../templates/builtInGraphTemplates";

export const defaultWorkspaceExtensions: GraphInstanceWorkspaceExtension[] = [
  {
    extension_id: "builtin.default.file_desk",
    displayName: "文件工作台",
    appliesToTemplateCategory: ["writing", "review", "research", "automation", "custom"],
    componentKey: "default_file_desk",
  },
];

export function graphWorkspaceExtensionsForTemplate(template: GraphTemplateRecord | null | undefined) {
  const extensions = new Map<string, GraphInstanceWorkspaceExtension>();
  for (const extension of defaultWorkspaceExtensions) extensions.set(extension.extension_id, extension);
  for (const extension of template?.workspace_extensions ?? []) extensions.set(extension.extension_id, extension);
  return Array.from(extensions.values());
}

export function allGraphWorkspaceExtensions() {
  const extensions = new Map<string, GraphInstanceWorkspaceExtension>();
  for (const extension of defaultWorkspaceExtensions) extensions.set(extension.extension_id, extension);
  for (const template of builtInGraphTemplates) {
    for (const extension of template.workspace_extensions ?? []) {
      extensions.set(extension.extension_id, extension);
    }
  }
  return Array.from(extensions.values());
}
