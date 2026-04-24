"use client";

import type { CSSProperties } from "react";

import type { SoulKey, SoulSummary } from "@/lib/souls";

type SoulSwitcherProps = {
  souls: SoulSummary[];
  activeSoulKey: SoulKey | null;
  onSwitch: (key: SoulKey) => Promise<void>;
};

export function SoulSwitcher({ souls, activeSoulKey, onSwitch }: SoulSwitcherProps) {
  return (
    <div className="soul-switcher" role="tablist" aria-label="切换处理风格">
      {souls.map((soul) => {
        const active = soul.key === activeSoulKey;
        return (
          <button
            aria-label={`切换为 ${soul.name}`}
            aria-pressed={active}
            className={`soul-dot ${active ? "soul-dot--active" : ""}`}
            key={soul.key}
            onClick={() => void onSwitch(soul.key)}
            title={soul.name}
            style={
              {
                "--orb-color": soul.color,
                "--orb-glow": soul.glow
              } as CSSProperties
            }
            type="button"
          />
        );
      })}
    </div>
  );
}
