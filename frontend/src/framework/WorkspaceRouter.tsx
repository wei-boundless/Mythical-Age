"use client";

import { useEffect, useState } from "react";

import { useAppStore } from "@/lib/store";

import { WorkspaceRegistry } from "./WorkspaceRegistry";
import {
  isWorkspaceQueryView,
  isWorkspaceView,
} from "./workspaceViews";
import { applyWorkbenchAppearance } from "./workbenchThemes";

export function WorkspaceRouter() {
  const {
    activeWorkspaceView,
    setWorkspaceView,
    conversationActiveEnvironment,
  } = useAppStore();
  const [locationSearch, setLocationSearch] = useState("");

  useEffect(() => {
    applyWorkbenchAppearance();
  }, []);

  useEffect(() => {
    function syncLocationSearch() {
      setLocationSearch(window.location.search);
    }
    syncLocationSearch();
    window.addEventListener("popstate", syncLocationSearch);
    window.addEventListener("focus", syncLocationSearch);
    const timer = window.setInterval(syncLocationSearch, 500);
    return () => {
      window.removeEventListener("popstate", syncLocationSearch);
      window.removeEventListener("focus", syncLocationSearch);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const currentSearch = typeof window === "undefined" ? locationSearch : window.location.search;
    const view = new URLSearchParams(currentSearch).get("view");
    if (isWorkspaceQueryView(view) && activeWorkspaceView !== view) {
      setWorkspaceView(view);
    }
  }, [activeWorkspaceView, locationSearch, setWorkspaceView]);

  useEffect(() => {
    if (!isWorkspaceView(activeWorkspaceView)) {
      setWorkspaceView("chat");
    }
  }, [activeWorkspaceView, setWorkspaceView]);

  const centerTaskEnvironmentId = String(conversationActiveEnvironment?.task_environment_id || "env.general.workspace");

  return (
    <>
      <WorkspaceRegistry centerTaskEnvironmentId={centerTaskEnvironmentId} view={activeWorkspaceView} />
    </>
  );
}
