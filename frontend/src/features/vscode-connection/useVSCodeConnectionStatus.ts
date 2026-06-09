"use client";

import { useCallback, useEffect, useState } from "react";

import { getVSCodeConnectionStatus, openSessionProjectInVSCode } from "./api";
import type { OpenSessionProjectInVSCodeResponse, VSCodeConnectionStatus } from "./types";

const POLL_INTERVAL_MS = 5000;
const RECONNECT_POLL_INTERVAL_MS = 1500;
const RECONNECT_TIMEOUT_MS = 22000;

export function useVSCodeConnectionStatus(sessionId: string | null | undefined) {
  const [status, setStatus] = useState<VSCodeConnectionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const targetSessionId = String(sessionId || "").trim();
    if (!targetSessionId) {
      setStatus(null);
      setError("");
      return;
    }
    setLoading(true);
    try {
      const next = await getVSCodeConnectionStatus(targetSessionId);
      setStatus(next);
      setError("");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const open = useCallback(async (): Promise<OpenSessionProjectInVSCodeResponse | null> => {
    const targetSessionId = String(sessionId || "").trim();
    if (!targetSessionId) {
      return null;
    }
    setOpening(true);
    try {
      const result = await openSessionProjectInVSCode(targetSessionId);
      if (result.connection_status) {
        setStatus(result.connection_status);
      }
      setError("");
      await waitForFreshStatus(targetSessionId, setStatus);
      return result;
    } catch (requestError) {
      setError(errorMessage(requestError));
      return null;
    } finally {
      setOpening(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    if (!sessionId) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, sessionId]);

  return {
    status,
    loading,
    opening,
    error,
    refresh,
    open,
  };
}

function errorMessage(value: unknown) {
  if (value instanceof Error) {
    return value.message;
  }
  return String(value || "VS Code connection request failed");
}

async function waitForFreshStatus(
  sessionId: string,
  setStatus: (status: VSCodeConnectionStatus) => void,
): Promise<VSCodeConnectionStatus | null> {
  const deadline = Date.now() + RECONNECT_TIMEOUT_MS;
  let latest: VSCodeConnectionStatus | null = null;
  while (Date.now() < deadline) {
    await delay(RECONNECT_POLL_INTERVAL_MS);
    const next = await getVSCodeConnectionStatus(sessionId);
    latest = next;
    setStatus(next);
    if (next.connected && !next.stale) {
      return next;
    }
  }
  return latest;
}

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}
