"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type ToggleProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-pressed" | "type"> & {
  activeClassName?: string;
  checked: boolean;
  children?: ReactNode;
  onCheckedChange?: (checked: boolean) => void;
  type?: "button" | "submit" | "reset";
};

export function Toggle({
  activeClassName,
  checked,
  children,
  className,
  onCheckedChange,
  onClick,
  type = "button",
  ...props
}: ToggleProps) {
  return (
    <button
      aria-pressed={checked}
      className={cn(className, checked && activeClassName)}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          onCheckedChange?.(!checked);
        }
      }}
      type={type}
      {...props}
    >
      {children}
    </button>
  );
}
