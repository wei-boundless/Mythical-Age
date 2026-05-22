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
import type { AppStore, StoreState } from "@/lib/store/types";
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
    runtime.startGlobalRuntimeMonitor();
    void runtime.initialize();
    return () => {
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
