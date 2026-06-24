import { builtInWritingGraphTemplate } from "./builtInWritingGraphTemplate";
import type { GraphTemplateRecord } from "./graphTemplateTypes";

export const builtInGraphTemplates: GraphTemplateRecord[] = [
  builtInWritingGraphTemplate,
];

export function findBuiltInGraphTemplate(templateId: string) {
  return builtInGraphTemplates.find((template) => template.template_id === templateId) ?? null;
}
