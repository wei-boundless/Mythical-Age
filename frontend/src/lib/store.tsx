"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from "react";

import { createStore, getDefaultState, type Store } from "@/lib/store/core";
import { useStoreValue } from "@/lib/store/hooks";
import { WorkspaceRuntime } from "@/lib/store/runtime";
import type { AppStore, StoreActions, StoreState } from "@/lib/store/types";
import { buildEditableFiles } from "@/lib/store/utils";

type StoreContextValue = {
  runtime: WorkspaceRuntime;
  store: Store<StoreState>;
};

const StoreContext = createContext<StoreContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => createStore(getDefaultState()));
  const [runtime] = useState(() => new WorkspaceRuntime(store));

  useEffect(() => {
    let cancelled = false;
    void runtime.initialize()
      .then(() => {
        if (cancelled) return;
        runtime.startRunMonitor();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      runtime.dispose();
    };
  }, [runtime]);

  const value = useMemo(() => ({ runtime, store }), [runtime, store]);
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useAppStore(): AppStore {
  const value = useContext(StoreContext);
  if (!value) {
    throw new Error("useAppStore must be used inside AppProvider");
  }

  const state = useStoreValue(value.store, (snapshot) => snapshot);
  return {
    ...state,
    editableFiles: buildEditableFiles(state.skills),
    ...value.runtime.actions
  };
}

export function useAppStoreSelector<S>(
  selector: (state: StoreState) => S,
  isEqual?: (left: S, right: S) => boolean,
): S {
  const value = useContext(StoreContext);
  if (!value) {
    throw new Error("useAppStoreSelector must be used inside AppProvider");
  }
  return useStoreValue(value.store, selector, isEqual);
}

export function useAppStoreActions(): StoreActions {
  const value = useContext(StoreContext);
  if (!value) {
    throw new Error("useAppStoreActions must be used inside AppProvider");
  }
  return value.runtime.actions;
}
