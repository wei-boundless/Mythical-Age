"use client";

import { Boxes, Hammer, Network, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { loadFile } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type ToolRegistryItem = {
  name?: string;
  module?: string;
  capability_tags?: string[];
  supported_modalities?: string[];
  safe_for_auto_route?: boolean;
  is_read_only?: boolean;
};

function parseTools(content: string): ToolRegistryItem[] {
  try {
    const payload = JSON.parse(content) as { tools?: ToolRegistryItem[] };
    return Array.isArray(payload.tools) ? payload.tools : [];
  } catch {
    return [];
  }
}

export function CapabilitiesView() {
  const { skills, loadInspectorFile } = useAppStore();
  const [query, setQuery] = useState("");
  const [tools, setTools] = useState<ToolRegistryItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function loadTools() {
      const file = await loadFile("TOOLS_REGISTRY.json").catch(() => ({ content: "" }));
      if (!cancelled) {
        setTools(parseTools(file.content));
      }
    }
    void loadTools();
    return () => {
      cancelled = true;
    };
  }, []);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleSkills = normalizedQuery
    ? skills.filter((skill) =>
        `${skill.name} ${skill.title} ${skill.description}`.toLowerCase().includes(normalizedQuery)
      )
    : skills;
  const visibleTools = normalizedQuery
    ? tools.filter((tool) =>
        `${tool.name ?? ""} ${tool.module ?? ""} ${(tool.capability_tags ?? []).join(" ")}`.toLowerCase().includes(normalizedQuery)
      )
    : tools;

  return (
    <div className="workspace-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Operation System</p>
          <h2 className="workspace-view__title">操作系统</h2>
        </div>
        <div className="workspace-view__actions">
          <div className="tag-chip">{skills.length} Skills</div>
          <div className="tag-chip">{tools.length} Tools</div>
        </div>
      </header>

      <div className="workspace-search">
        <Search size={17} />
        <input
          aria-label="查询能力"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="查询 tool、skill 或操作能力标签"
          value={query}
        />
      </div>

      <div className="capability-columns">
        <section className="workspace-section">
          <div className="workspace-section__head">
            <Boxes size={18} />
            <h3>Skills</h3>
          </div>
          <div className="workspace-list">
            {visibleSkills.map((skill) => (
              <article className="workspace-record" key={skill.name}>
                <div className="workspace-record__meta">
                  <span>{skill.name}</span>
                  <span>{skill.path}</span>
                </div>
                <h3>{skill.title || skill.name}</h3>
                <p>{skill.description}</p>
                <button
                  className="action-button action-button--muted workspace-record__button"
                  onClick={() => void loadInspectorFile(skill.path)}
                  type="button"
                >
                  打开定义
                </button>
              </article>
            ))}
          </div>
        </section>

        <section className="workspace-section">
          <div className="workspace-section__head">
            <Hammer size={18} />
            <h3>Tools</h3>
          </div>
          <div className="workspace-list">
            {visibleTools.map((tool) => (
              <article className="workspace-record" key={tool.name ?? tool.module}>
                <div className="workspace-record__meta">
                  <span>{tool.safe_for_auto_route ? "auto-route" : "manual"}</span>
                  <span>{tool.is_read_only ? "read-only" : "write-capable"}</span>
                </div>
                <h3>{tool.name}</h3>
                <p>{tool.module}</p>
                <div className="workspace-chip-row">
                  {(tool.capability_tags ?? []).slice(0, 5).map((tag) => (
                    <span className="workspace-mini-chip" key={tag}>{tag}</span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="workspace-section workspace-section--compact">
        <div className="workspace-section__head">
          <Network size={18} />
          <h3>操作边界</h3>
        </div>
        <div className="framework-grid framework-grid--agents">
          {[
            "TOOLS_REGISTRY.json",
            "SKILLS_REGISTRY.json",
            "backend/tools",
            "backend/skills"
          ].map((path) => (
            <article className="framework-node" key={path}>
              <div className="framework-node__kind">operation runtime</div>
              <h4>{path.split("/").slice(-1)[0]}</h4>
              <span>{path}</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
