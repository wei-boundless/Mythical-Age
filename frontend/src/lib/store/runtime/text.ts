export function runtimeText(value: unknown) {
  return String(value ?? "").trim();
}

export function errorDetailMessage(error: unknown) {
  const message = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  if (!message) {
    return "";
  }
  try {
    const parsed = JSON.parse(message) as { detail?: unknown; message?: unknown };
    return String(parsed.detail || parsed.message || message).trim();
  } catch {
    return message;
  }
}
