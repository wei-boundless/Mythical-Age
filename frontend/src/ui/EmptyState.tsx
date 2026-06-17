"use client";

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type EmptyStateProps = HTMLAttributes<HTMLElement> & {
  as?: "div" | "section";
  children?: ReactNode;
  icon?: ReactNode;
  title: ReactNode;
};

export function EmptyState({
  as: Component = "div",
  children,
  className,
  icon,
  title,
  ...props
}: EmptyStateProps) {
  return (
    <Component className={cn(className)} {...props}>
      {icon}
      <strong>{title}</strong>
      {children}
    </Component>
  );
}
