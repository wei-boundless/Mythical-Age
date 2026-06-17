"use client";

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type PanelElement = "article" | "aside" | "div" | "section";

type PanelProps = HTMLAttributes<HTMLElement> & {
  as?: PanelElement;
  children: ReactNode;
  variant?: "default" | "summary";
};

export function Panel({
  as: Component = "section",
  children,
  className,
  variant = "default",
  ...props
}: PanelProps) {
  return (
    <Component className={cn("boundary-card", variant === "summary" && "boundary-card--summary", className)} {...props}>
      {children}
    </Component>
  );
}
