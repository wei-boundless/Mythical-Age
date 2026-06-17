"use client";

import type { HTMLAttributes, ReactNode } from "react";
import { createElement } from "react";

import { cn } from "./classNames";

type MetricCardProps = HTMLAttributes<HTMLElement> & {
  as?: "article" | "div" | "section";
  detail?: ReactNode;
  detailAs?: "em" | "p" | "small";
  label: ReactNode;
  toneClassName?: string;
  value: ReactNode;
};

export function MetricCard({
  as: Component = "article",
  className,
  detail,
  detailAs = "small",
  label,
  toneClassName,
  value,
  ...props
}: MetricCardProps) {
  return (
    <Component className={cn(className, toneClassName)} {...props}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail !== undefined && detail !== null ? createElement(detailAs, null, detail) : null}
    </Component>
  );
}
