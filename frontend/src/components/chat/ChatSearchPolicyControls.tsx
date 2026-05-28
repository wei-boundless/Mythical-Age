"use client";

import { Database, FolderLock, Globe2 } from "lucide-react";

import type { SearchPolicySource, SearchPolicyState } from "@/lib/store/types";

const SEARCH_POLICY_OPTIONS: Array<{
  id: SearchPolicySource;
  label: string;
  title: string;
}> = [
  { id: "rag", label: "知识库", title: "启用知识库" },
  { id: "local_files", label: "本地", title: "启用本地权限" },
  { id: "web", label: "联网", title: "启用联网权限" }
];

export function ChatSearchPolicyControls({
  onToggleSearchPolicy,
  searchPolicy,
}: {
  onToggleSearchPolicy: (source: SearchPolicySource) => void;
  searchPolicy: SearchPolicyState;
}) {
  return (
    <div className="chat-control-cluster chat-control-cluster--scope chat-control-cluster--topbar">
      <span className="chat-control-cluster__name">权限</span>
      <div className="chat-search-policy chat-search-policy--compact" aria-label="本轮能力权限">
        {SEARCH_POLICY_OPTIONS.map((option) => {
          const enabled = searchPolicy[option.id];
          return (
            <button
              aria-pressed={enabled}
              className={enabled ? "chat-search-policy__item chat-search-policy__item--active" : "chat-search-policy__item"}
              key={option.id}
              onClick={() => onToggleSearchPolicy(option.id)}
              title={option.title}
              type="button"
            >
              {searchPolicyIcon(option.id)}
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function searchPolicyIcon(source: SearchPolicySource) {
  if (source === "rag") return <Database size={12} />;
  if (source === "local_files") return <FolderLock size={12} />;
  return <Globe2 size={12} />;
}
