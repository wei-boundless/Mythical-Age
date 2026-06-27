"use client";

import type { LayerNavGroup, AgentSystemLayer } from "./agentSystemAssemblyModel";

export function AgentSystemLayerNav({
  activeLayer,
  groups,
  onSelectLayer,
}: {
  activeLayer: AgentSystemLayer;
  groups: LayerNavGroup[];
  onSelectLayer: (layer: AgentSystemLayer) => void;
}) {
  return (
    <nav className="agent-system-assembly-nav" aria-label="Agent 管理配置页面">
      {groups.map((group) => (
        <section className="agent-system-assembly-nav__group" key={group.title}>
          <span>{group.title}</span>
          <div>
            {group.items.map(([value, label, meta]) => (
              <button
                className={activeLayer === value ? "agent-system-assembly-nav__item agent-system-assembly-nav__item--active" : "agent-system-assembly-nav__item"}
                key={value}
                onClick={() => onSelectLayer(value)}
                type="button"
              >
                <strong>{label}</strong>
                <small>{meta}</small>
              </button>
            ))}
          </div>
        </section>
      ))}
    </nav>
  );
}




