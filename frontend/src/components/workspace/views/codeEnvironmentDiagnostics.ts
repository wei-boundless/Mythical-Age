function compactDiagnosticValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.map((item) => compactDiagnosticValue(item)).filter(Boolean).join(" / ");
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const message = compactDiagnosticValue(record.message ?? record.detail ?? record.error ?? record.reason);
    const code = compactDiagnosticValue(record.code ?? record.type);
    const path = compactDiagnosticValue(record.path);
    const label = [code, message].filter(Boolean).join("：") || JSON.stringify(record);
    return path ? `${label}（${path}）` : label;
  }
  return String(value).trim();
}

export function codeEnvironmentDiagnosticsText(diagnostics: unknown[]): string {
  return diagnostics.map((item) => compactDiagnosticValue(item)).filter(Boolean).join("；");
}
