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
import type { AppStore, StoreState, WorkspaceView } from "@/lib/store/types";
import { buildEditableFiles } from "@/lib/store/utils";

type StoreContextValue = {
  runtime: WorkspaceRuntime;
  store: Store<StoreState>;
};

const StoreContext = createContext<StoreContextValue | null>(null);

const INITIAL_WORKSPACE_QUERY_VIEWS = new Set<WorkspaceView>([
  "chat",
  "memory",
  "test-system",
  "health-system",
  "capability-system",
  "mcp-system",
  "evidence",
  "task-system",
  "orchestration",
  "system-framework",
  "experiments",
  "playground",
  "system-config"
]);

function initialWorkspaceView() {
  if (typeof window === "undefined") {
    return getDefaultState().activeWorkspaceView;
  }
  const view = new URLSearchParams(window.location.search).get("view");
  return view && INITIAL_WORKSPACE_QUERY_VIEWS.has(view as WorkspaceView)
    ? view as WorkspaceView
    : getDefaultState().activeWorkspaceView;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => {
    const state = getDefaultState();
    return createStore({
      ...state,
      activeWorkspaceView: initialWorkspaceView(),
    });
  });
  const [runtime] = useState(() => new WorkspaceRuntime(store));

  useEffect(() => {
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
