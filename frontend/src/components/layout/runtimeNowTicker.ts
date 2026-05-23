"use client";

import { useEffect, useState } from "react";

type RuntimeNowListener = (nowSeconds: number) => void;

const listeners = new Set<RuntimeNowListener>();
let timer: number | null = null;
let currentNowSeconds = Date.now() / 1000;

function startRuntimeNowTicker() {
  if (timer !== null || typeof window === "undefined") {
    return;
  }
  timer = window.setInterval(() => {
    currentNowSeconds = Date.now() / 1000;
    for (const listener of listeners) {
      listener(currentNowSeconds);
    }
  }, 1000);
}

function stopRuntimeNowTicker() {
  if (timer === null || typeof window === "undefined") {
    return;
  }
  window.clearInterval(timer);
  timer = null;
}

export function getRuntimeNowSeconds() {
  return currentNowSeconds;
}

export function getRuntimeNowTickerSubscriberCount() {
  return listeners.size;
}

export function subscribeRuntimeNowTicker(listener: RuntimeNowListener) {
  listeners.add(listener);
  startRuntimeNowTicker();
  return () => {
    listeners.delete(listener);
    if (!listeners.size) {
      stopRuntimeNowTicker();
    }
  };
}

export function useRuntimeNowTicker(active: boolean) {
  const [nowSeconds, setNowSeconds] = useState(() => getRuntimeNowSeconds());

  useEffect(() => {
    if (!active) {
      return undefined;
    }
    return subscribeRuntimeNowTicker(setNowSeconds);
  }, [active]);

  return nowSeconds;
}
