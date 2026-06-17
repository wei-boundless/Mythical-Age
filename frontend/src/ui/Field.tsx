"use client";

import type { LabelHTMLAttributes, ReactNode } from "react";

import { cn } from "./classNames";

type FieldProps = LabelHTMLAttributes<HTMLLabelElement> & {
  children: ReactNode;
  label: string;
  wide?: boolean;
};

export function Field({
  children,
  className,
  label,
  wide = false,
  ...props
}: FieldProps) {
  return (
    <label className={cn("boundary-field", wide && "boundary-field--wide", className)} {...props}>
      <span>{label}</span>
      {children}
    </label>
  );
}
