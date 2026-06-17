"use client";

import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type TabsProps = HTMLAttributes<HTMLElement> & {
  ariaLabel: string;
  children: ReactNode;
};

type TabButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  active?: boolean;
  children: ReactNode;
  type?: "button" | "submit" | "reset";
};

export function Tabs({
  ariaLabel,
  children,
  className,
  ...props
}: TabsProps) {
  return (
    <nav aria-label={ariaLabel} className={cn("center-workspace__tabs", className)} {...props}>
      {children}
    </nav>
  );
}

export function TabButton({
  active = false,
  children,
  className,
  type = "button",
  ...props
}: TabButtonProps) {
  return (
    <button
      className={cn("chat-page-tabs__item", active && "chat-page-tabs__item--active", className)}
      type={type}
      {...props}
    >
      {children}
    </button>
  );
}
