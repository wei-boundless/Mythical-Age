import { builtInGraphTemplates, findBuiltInGraphTemplate } from "../templates/builtInGraphTemplates";
import type { GraphTemplateRecord } from "../templates/graphTemplateTypes";

const USER_TEMPLATE_STORAGE_KEY = "graphRepository.userTemplates.v1";

export function listBuiltInGraphTemplates() {
  return builtInGraphTemplates;
}

export function readUserGraphTemplates(): GraphTemplateRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(USER_TEMPLATE_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isGraphTemplateRecord) : [];
  } catch {
    return [];
  }
}

export function writeUserGraphTemplates(templates: GraphTemplateRecord[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_TEMPLATE_STORAGE_KEY, JSON.stringify(templates.filter(isGraphTemplateRecord)));
}

export function upsertUserGraphTemplate(template: GraphTemplateRecord) {
  const current = readUserGraphTemplates();
  const next = [
    template,
    ...current.filter((item) => item.template_id !== template.template_id),
  ];
  writeUserGraphTemplates(next);
  return next;
}

export function deleteUserGraphTemplate(templateId: string) {
  const next = readUserGraphTemplates().filter((item) => item.template_id !== templateId);
  writeUserGraphTemplates(next);
  return next;
}

export function listGraphTemplates() {
  return [
    ...listBuiltInGraphTemplates(),
    ...readUserGraphTemplates(),
  ];
}

export function findGraphTemplate(templateId: string) {
  return findBuiltInGraphTemplate(templateId)
    ?? readUserGraphTemplates().find((template) => template.template_id === templateId)
    ?? null;
}

function isGraphTemplateRecord(value: unknown): value is GraphTemplateRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Partial<GraphTemplateRecord>;
  return Boolean(record.template_id && record.title && record.graph_seed);
}
