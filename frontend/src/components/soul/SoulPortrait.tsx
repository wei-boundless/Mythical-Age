"use client";

import Image from "next/image";

import type { SoulSummary } from "@/lib/souls";

export function SoulPortrait({
  soul,
  compact = false
}: {
  soul: SoulSummary;
  compact?: boolean;
}) {
  return (
    <div className={`soul-portrait ${compact ? "soul-portrait--compact" : ""}`}>
      <div className="soul-portrait__halo" />
      <Image
        alt={`${soul.name} 角色立绘`}
        className="soul-portrait__image"
        height={1448}
        priority={!compact}
        src={soul.portraitPath}
        width={1086}
      />
      {!compact ? (
        <div className="soul-portrait__label">
          <span className="soul-portrait__name">{soul.name}</span>
        </div>
      ) : null}
    </div>
  );
}
