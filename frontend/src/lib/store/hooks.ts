"use client";

import { useRef, useSyncExternalStore } from "react";

import type { Store } from "./core";

export function useStoreValue<T, S>(
  store: Store<T>,
  selector: (state: T) => S,
  isEqual: (left: S, right: S) => boolean = Object.is,
): S {
  const snapshotRef = useRef<{ value: S } | null>(null);
  const getSelectedSnapshot = () => {
    const next = selector(store.getState());
    const previous = snapshotRef.current;
    if (previous && isEqual(previous.value, next)) {
      return previous.value;
    }
    snapshotRef.current = { value: next };
    return next;
  };
  return useSyncExternalStore(
    store.subscribe,
    getSelectedSnapshot,
    getSelectedSnapshot,
  );
}

export function shallowEqual<T extends Record<string, unknown>>(left: T, right: T) {
  if (Object.is(left, right)) {
    return true;
  }
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) {
    return false;
  }
  return leftKeys.every((key) => Object.prototype.hasOwnProperty.call(right, key) && Object.is(left[key], right[key]));
}
