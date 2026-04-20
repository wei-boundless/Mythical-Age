"use client";

import { useSyncExternalStore } from "react";

import type { Store } from "./core";

export function useStoreValue<T, S>(store: Store<T>, selector: (state: T) => S): S {
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.getState()),
    () => selector(store.getState())
  );
}
