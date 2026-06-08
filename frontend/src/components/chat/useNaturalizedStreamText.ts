import { useEffect, useRef, useState } from "react";

export type NaturalizedStreamSlice = {
  text: string;
  delayMs: number;
};

const FAST_DELAY_MS = 10;
const NORMAL_DELAY_MS = 24;
const SOFT_PAUSE_MS = 58;
const HARD_PAUSE_MS = 112;
const LINE_PAUSE_MS = 72;

const SOFT_PUNCTUATION = new Set([",", ";", ":", "\uFF0C", "\u3001", "\uFF1B", "\uFF1A"]);
const HARD_PUNCTUATION = new Set([".", "!", "?", "\u3002", "\uFF01", "\uFF1F", "\u2026"]);

export function useNaturalizedStreamText(targetText: string, enabled: boolean) {
  const [displayText, setDisplayText] = useState(targetText);
  const targetTextRef = useRef(targetText);

  useEffect(() => {
    targetTextRef.current = targetText;
    if (!enabled || prefersReducedMotion()) {
      setDisplayText(targetText);
      return;
    }

    setDisplayText((current) => {
      if (!targetText.startsWith(current)) {
        return targetText;
      }
      return current;
    });
  }, [enabled, targetText]);

  useEffect(() => {
    if (!enabled || prefersReducedMotion()) {
      return;
    }
    let nextAt = 0;
    const timer = window.setInterval(() => {
      if (Date.now() < nextAt) {
        return;
      }
      setDisplayText((current) => {
        const latestTargetText = targetTextRef.current;
        if (current === latestTargetText) {
          return current;
        }
        if (!latestTargetText.startsWith(current)) {
          return latestTargetText;
        }
        const next = takeNaturalizedStreamSlice(current, latestTargetText);
        if (!next.text) {
          return current;
        }
        nextAt = Date.now() + next.delayMs;
        return `${current}${next.text}`;
      });
    }, FAST_DELAY_MS);
    return () => window.clearInterval(timer);
  }, [enabled]);

  return enabled ? displayText : targetText;
}

export function createNaturalizedStreamProjector(initialText = "") {
  let displayText = initialText;
  let targetText = initialText;
  let nextAt = 0;
  return {
    setTarget(nextTargetText: string) {
      targetText = nextTargetText;
      if (!targetText.startsWith(displayText)) {
        displayText = targetText;
        nextAt = 0;
      }
    },
    tick(now: number) {
      if (displayText === targetText || now < nextAt) {
        return displayText;
      }
      const next = takeNaturalizedStreamSlice(displayText, targetText);
      if (!next.text) {
        return displayText;
      }
      displayText = `${displayText}${next.text}`;
      nextAt = now + next.delayMs;
      return displayText;
    },
    text() {
      return displayText;
    },
  };
}

export function takeNaturalizedStreamSlice(displayedText: string, targetText: string): NaturalizedStreamSlice {
  if (!targetText.startsWith(displayedText)) {
    return { text: targetText, delayMs: FAST_DELAY_MS };
  }
  const pending = targetText.slice(displayedText.length);
  if (!pending) {
    return { text: "", delayMs: 0 };
  }
  const backlog = pending.length;
  if (isMarkdownCodeFenceOpen(displayedText)) {
    return {
      text: takeUntilNewlineOrLimit(pending, 96),
      delayMs: adjustedDelay(FAST_DELAY_MS, backlog),
    };
  }
  if (isAtLineStart(displayedText) && pending.startsWith("|")) {
    return {
      text: takeUntilNewlineOrLimit(pending, 140),
      delayMs: adjustedDelay(FAST_DELAY_MS, backlog),
    };
  }
  const atomic = atomicRun(pending);
  if (atomic) {
    return {
      text: atomic,
      delayMs: adjustedDelay(FAST_DELAY_MS, backlog),
    };
  }
  const whitespace = pending.match(/^\s+/)?.[0] ?? "";
  if (whitespace) {
    return {
      text: whitespace,
      delayMs: whitespace.includes("\n") ? adjustedDelay(LINE_PAUSE_MS, backlog) : adjustedDelay(FAST_DELAY_MS, backlog),
    };
  }
  const punctuationBoundary = punctuationSliceBoundary(pending);
  if (punctuationBoundary > 0) {
    const text = pending.slice(0, punctuationBoundary);
    return {
      text,
      delayMs: adjustedDelay(delayForSlice(text), backlog),
    };
  }
  if (startsWithCjk(pending)) {
    const text = takeCjkPhrase(pending);
    return {
      text,
      delayMs: adjustedDelay(delayForSlice(text), backlog),
    };
  }
  const text = takeWordPhrase(pending);
  return {
    text,
    delayMs: adjustedDelay(delayForSlice(text), backlog),
  };
}

function prefersReducedMotion() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function adjustedDelay(baseDelayMs: number, backlog: number) {
  if (backlog > 420) return Math.min(baseDelayMs, 8);
  if (backlog > 220) return Math.min(baseDelayMs, 12);
  if (backlog > 120) return Math.min(baseDelayMs, 16);
  return baseDelayMs;
}

function delayForSlice(text: string) {
  const last = [...text].at(-1) ?? "";
  if (HARD_PUNCTUATION.has(last)) return HARD_PAUSE_MS;
  if (SOFT_PUNCTUATION.has(last)) return SOFT_PAUSE_MS;
  if (text.includes("\n")) return LINE_PAUSE_MS;
  return NORMAL_DELAY_MS;
}

function punctuationSliceBoundary(text: string) {
  const limit = Math.min(text.length, 34);
  for (let index = 0; index < limit; index += 1) {
    const char = text[index];
    if (SOFT_PUNCTUATION.has(char) || HARD_PUNCTUATION.has(char)) {
      return index + 1;
    }
  }
  return 0;
}

function startsWithCjk(text: string) {
  return /^[\u3400-\u9FFF\uF900-\uFAFF]/.test(text);
}

function takeCjkPhrase(text: string) {
  let index = 0;
  for (const char of text) {
    if (index > 0 && /\s/.test(char)) break;
    if (index > 0 && (SOFT_PUNCTUATION.has(char) || HARD_PUNCTUATION.has(char))) {
      index += char.length;
      break;
    }
    index += char.length;
    if (index >= 5) break;
  }
  return text.slice(0, Math.max(index, 1));
}

function takeWordPhrase(text: string) {
  let index = 0;
  let wordCount = 0;
  while (index < text.length && wordCount < 4 && index < 42) {
    const remaining = text.slice(index);
    const word = remaining.match(/^[^\s]+/)?.[0] ?? "";
    if (!word) break;
    index += word.length;
    wordCount += 1;
    if (containsPunctuation(word)) break;
    const space = text.slice(index).match(/^\s+/)?.[0] ?? "";
    if (!space) break;
    index += space.length;
    if (space.includes("\n")) break;
  }
  return text.slice(0, Math.max(index, 1));
}

function containsPunctuation(text: string) {
  return [...text].some((char) => SOFT_PUNCTUATION.has(char) || HARD_PUNCTUATION.has(char));
}

function atomicRun(text: string) {
  const match = text.match(/^(?:https?:\/\/\S+|[A-Za-z]:[\\/]\S+|\.{0,2}[\\/]\S+|[\w.-]+\/[\w./-]*[\w-])/);
  return match?.[0] ?? "";
}

function takeUntilNewlineOrLimit(text: string, limit: number) {
  const newlineIndex = text.indexOf("\n");
  if (newlineIndex >= 0 && newlineIndex < limit) {
    return text.slice(0, newlineIndex + 1);
  }
  return text.slice(0, Math.min(text.length, limit));
}

function isAtLineStart(text: string) {
  return !text || text.endsWith("\n");
}

function isMarkdownCodeFenceOpen(text: string) {
  const fences = text.match(/```/g);
  return Boolean(fences && fences.length % 2 === 1);
}
