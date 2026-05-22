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

const URL_WORKSPACE_VIEWS = new Set<WorkspaceView>([
  "chat",
  "playground",
  "task-system",
  "capability-system",
  "system-framework"
]);

function initialWorkspaceViewFromLocation(): WorkspaceView | null {
  if (typeof window === "undefined") return null;
  const view = new URLSearchParams(window.location.search).get("view");
  return view && URL_WORKSPACE_VIEWS.has(view as WorkspaceView) ? view as WorkspaceView : null;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => {
    const state = getDefaultState();
    const initialWorkspaceView = initialWorkspaceViewFromLocation();
    if (initialWorkspaceView) {
      state.activeWorkspaceView = initialWorkspaceView;
    }
    return createStore(state);
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
