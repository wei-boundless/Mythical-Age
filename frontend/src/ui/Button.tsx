"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

export type ButtonChrome = "plain" | "boundary" | "action" | "dialog";
export type ButtonVariant = "default" | "ghost" | "primary" | "danger" | "muted";

type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  chrome?: ButtonChrome;
  children: ReactNode;
  type?: "button" | "submit" | "reset";
  variant?: ButtonVariant;
};

function buttonChromeClassName(chrome: ButtonChrome, variant: ButtonVariant) {
  if (chrome === "boundary") {
    if (variant === "default") return "boundary-button";
    return cn("boundary-button", `boundary-button--${variant}`);
  }
  if (chrome === "action") {
    if (variant === "default") return "action-button";
    return cn("action-button", `action-button--${variant}`);
  }
  if (chrome === "dialog" && variant === "primary") {
    return "confirm-dialog__primary";
  }
  return "";
}

export function Button({
  chrome = "plain",
  children,
  className,
  type = "button",
  variant = "default",
  ...props
}: ButtonProps) {
  return (
    <button className={cn(buttonChromeClassName(chrome, variant), className)} type={type} {...props}>
      {children}
    </button>
  );
}
