"use client";

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type StatusBadgeTone = "neutral" | "ok" | "warn" | "danger";

type StatusBadgeProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: StatusBadgeTone;
};

export function StatusBadge({
  children,
  className,
  tone = "neutral",
  ...props
}: StatusBadgeProps) {
  return (
    <span className={cn("boundary-badge", `boundary-badge--${tone}`, className)} {...props}>
      {children}
    </span>
  );
}
