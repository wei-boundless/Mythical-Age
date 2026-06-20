"use client";

import type { LayerNavGroup, OrchestrationLayer } from "./orchestrationAssemblyModel";

export function OrchestrationLayerNav({
  activeLayer,
  groups,
  onSelectLayer,
}: {
  activeLayer: OrchestrationLayer;
  groups: LayerNavGroup[];
  onSelectLayer: (layer: OrchestrationLayer) => void;
}) {
  return (
    <nav className="orchestration-assembly-nav" aria-label="Agent 管理配置页面">
      {groups.map((group) => (
        <section className="orchestration-assembly-nav__group" key={group.title}>
          <span>{group.title}</span>
          <div>
            {group.items.map(([value, label, meta]) => (
              <button
                className={activeLayer === value ? "orchestration-assembly-nav__item orchestration-assembly-nav__item--active" : "orchestration-assembly-nav__item"}
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
