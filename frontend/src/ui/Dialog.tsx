"use client";

import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type DialogBackdropProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

type DialogSurfaceProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  tone?: "danger" | "warning" | "neutral";
};

export function DialogBackdrop({ children, className, ...props }: DialogBackdropProps) {
  return (
    <div className={cn("confirm-dialog-backdrop", className)} role="presentation" {...props}>
      {children}
    </div>
  );
}

export function DialogSurface({
  children,
  className,
  tone = "neutral",
  ...props
}: DialogSurfaceProps) {
  return (
    <section
      aria-modal="true"
      className={cn("confirm-dialog", `confirm-dialog--${tone}`, className)}
      role="dialog"
      {...props}
    >
      {children}
    </section>
  );
}
