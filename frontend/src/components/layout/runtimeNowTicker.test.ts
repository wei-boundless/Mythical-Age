import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getRuntimeNowTickerSubscriberCount,
  subscribeRuntimeNowTicker,
} from "./runtimeNowTicker";

describe("runtime now ticker", () => {
  const clearIntervalSpy = vi.fn();
  const setIntervalSpy = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    clearIntervalSpy.mockClear();
    setIntervalSpy.mockClear();
    vi.stubGlobal("window", {
      clearInterval: clearIntervalSpy,
      setInterval: setIntervalSpy,
    });
    setIntervalSpy.mockImplementation((callback: () => void) => setInterval(callback, 1000));
    clearIntervalSpy.mockImplementation((timer: ReturnType<typeof setInterval>) => clearInterval(timer));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shares one timer across subscribers and stops it after the last unsubscribe", () => {
    const first = vi.fn();
    const second = vi.fn();

    const unsubscribeFirst = subscribeRuntimeNowTicker(first);
    const unsubscribeSecond = subscribeRuntimeNowTicker(second);

    expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    expect(getRuntimeNowTickerSubscriberCount()).toBe(2);

    vi.advanceTimersByTime(1000);

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);

    unsubscribeFirst();

    expect(clearIntervalSpy).not.toHaveBeenCalled();
    expect(getRuntimeNowTickerSubscriberCount()).toBe(1);

    unsubscribeSecond();

    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
    expect(getRuntimeNowTickerSubscriberCount()).toBe(0);
  });
});

