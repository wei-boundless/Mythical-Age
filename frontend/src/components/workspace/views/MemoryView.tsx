"use client";

import { Activity, Database, FileText, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { getSessionHistory, loadFile, type SessionHistory } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type MemoryResult = {
  id: string;
  scope: "状态记忆" | "长期记忆";
  title: string;
  preview: string;
  source: string;
};

function compactText(value: string, limit = 220) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit)}...`;
}

export function MemoryView() {
  const { currentSessionId, messages, tokenStats, loadInspectorFile } = useAppStore();
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<SessionHistory | null>(null);
  const [durableMemory, setDurableMemory] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadMemory() {
      setError("");
      try {
        const [nextHistory, durable] = await Promise.all([
          currentSessionId ? getSessionHistory(currentSessionId) : Promise.resolve(null),
          loadFile("durable_memory/MEMORY.md").catch(() => ({ path: "durable_memory/MEMORY.md", content: "" }))
        ]);
        if (cancelled) {
          return;
        }
        setHistory(nextHistory);
        setDurableMemory(durable.content);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "记忆读取失败");
        }
      }
    }
    void loadMemory();
    return () => {
      cancelled = true;
    };
  }, [currentSessionId]);

  const statePreview =
    history?.compressed_context
    || messages.slice(-4).map((message) => `${message.role}: ${message.content}`).join("\n")
    || "当前会话还没有形成可展示的状态记忆。";

  const baseResults: MemoryResult[] = [
    {
      id: "session-state",
      scope: "状态记忆",
      title: "当前会话状态",
      preview: compactText(statePreview),
      source: currentSessionId ? `sessions/${currentSessionId}` : "sessions/current"
    },
    {
      id: "durable-memory",
      scope: "长期记忆",
      title: "长期记忆总览",
      preview: compactText(durableMemory || "长期记忆文件暂时为空。"),
      source: "durable_memory/MEMORY.md"
    }
  ];

  const normalizedQuery = query.trim().toLowerCase();
  const results = normalizedQuery
    ? baseResults.filter((item) =>
        `${item.scope} ${item.title} ${item.preview} ${item.source}`.toLowerCase().includes(normalizedQuery)
      )
    : baseResults;

  return (
    <div className="workspace-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Memory System</p>
          <h2 className="workspace-view__title">记忆系统</h2>
        </div>
        <div className="workspace-view__actions">
          <button
            className="action-button action-button--muted"
            onClick={() => void loadInspectorFile("durable_memory/MEMORY.md")}
            type="button"
          >
            <FileText size={16} />
            打开长期记忆
          </button>
        </div>
      </header>

      <div className="workspace-search">
        <Search size={17} />
        <input
          aria-label="查询记忆"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="查询状态记忆或长期记忆"
          value={query}
        />
      </div>

      <div className="workspace-metrics-grid">
        <div className="workspace-stat">
          <Activity size={18} />
          <span>状态记忆</span>
          <strong>{messages.length} 条会话消息</strong>
        </div>
        <div className="workspace-stat">
          <Database size={18} />
          <span>长期记忆</span>
          <strong>{durableMemory ? `${durableMemory.length} 字符` : "未读取到内容"}</strong>
        </div>
        <div className="workspace-stat">
          <FileText size={18} />
          <span>上下文压力</span>
          <strong>{tokenStats ? tokenStats.history_pressure_level : "暂无数据"}</strong>
        </div>
      </div>

      {error ? <div className="workspace-alert">{error}</div> : null}

      <div className="workspace-list">
        {results.map((item) => (
          <article className="workspace-record" key={item.id}>
            <div className="workspace-record__meta">
              <span>{item.scope}</span>
              <span>{item.source}</span>
            </div>
            <h3>{item.title}</h3>
            <p>{item.preview}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
