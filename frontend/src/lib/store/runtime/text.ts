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
    const detail = parsed.detail;
    if (detail && typeof detail === "object") {
      const detailMessage = (detail as { message?: unknown; detail?: unknown; code?: unknown }).message
        || (detail as { detail?: unknown }).detail
        || (detail as { code?: unknown }).code;
      if (detailMessage) {
        return String(detailMessage).trim();
      }
    }
    return String(detail || parsed.message || message).trim();
  } catch {
    return message;
  }
}
