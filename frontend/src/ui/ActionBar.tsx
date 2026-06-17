"use client";

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type ActionBarProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function ActionBar({ children, className, ...props }: ActionBarProps) {
  return (
    <div className={cn(className)} {...props}>
      {children}
    </div>
  );
}
