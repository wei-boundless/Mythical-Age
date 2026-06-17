"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, X } from "lucide-react";

import { Button } from "@/ui/Button";
import { DialogBackdrop, DialogSurface } from "@/ui/Dialog";
import { IconButton } from "@/ui/IconButton";

type ConfirmDialogOptions = {
  title: string;
  body: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "warning" | "neutral";
};

type PendingConfirmation = Required<Omit<ConfirmDialogOptions, "tone">> & {
  tone: NonNullable<ConfirmDialogOptions["tone"]>;
  resolve: (confirmed: boolean) => void;
};

const ConfirmDialogContext = createContext<((options: ConfirmDialogOptions) => Promise<boolean>) | null>(null);

export function ConfirmDialogProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirmation | null>(null);

  const confirm = useCallback((options: ConfirmDialogOptions) => new Promise<boolean>((resolve) => {
    setPending({
      title: options.title,
      body: options.body,
      confirmLabel: options.confirmLabel ?? "确认",
      cancelLabel: options.cancelLabel ?? "取消",
      tone: options.tone ?? "danger",
      resolve,
    });
  }), []);

  const value = useMemo(() => confirm, [confirm]);

  function close(confirmed: boolean) {
    const current = pending;
    setPending(null);
    current?.resolve(confirmed);
  }

  return (
    <ConfirmDialogContext.Provider value={value}>
      {children}
      {pending ? (
        <DialogBackdrop>
          <DialogSurface tone={pending.tone}>
            <header>
              <div className="confirm-dialog__icon"><AlertTriangle size={18} /></div>
              <div>
                <h2>{pending.title}</h2>
                <p>{pending.body}</p>
              </div>
              <IconButton label="关闭确认弹窗" onClick={() => close(false)}>
                <X size={16} />
              </IconButton>
            </header>
            <footer>
              <Button chrome="dialog" onClick={() => close(false)}>{pending.cancelLabel}</Button>
              <Button chrome="dialog" onClick={() => close(true)} variant="primary">{pending.confirmLabel}</Button>
            </footer>
          </DialogSurface>
        </DialogBackdrop>
      ) : null}
    </ConfirmDialogContext.Provider>
  );
}

export function useConfirmDialog() {
  const confirm = useContext(ConfirmDialogContext);
  if (!confirm) {
    throw new Error("useConfirmDialog must be used inside ConfirmDialogProvider");
  }
  return confirm;
}

