"use client";

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type NoticeProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  icon?: ReactNode;
  tone?: "neutral" | "error";
};

export function Notice({
  children,
  className,
  icon,
  tone = "neutral",
  ...props
}: NoticeProps) {
  return (
    <div className={cn("boundary-notice", tone === "error" && "boundary-notice--error", className)} {...props}>
      {icon}
      {children}
    </div>
  );
}
