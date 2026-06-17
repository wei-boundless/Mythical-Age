"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "type"> & {
  children: ReactNode;
  label: string;
  type?: "button" | "submit" | "reset";
};

export function IconButton({
  children,
  className,
  label,
  title,
  type = "button",
  ...props
}: IconButtonProps) {
  return (
    <button aria-label={label} className={cn(className)} title={title ?? label} type={type} {...props}>
      {children}
    </button>
  );
}
