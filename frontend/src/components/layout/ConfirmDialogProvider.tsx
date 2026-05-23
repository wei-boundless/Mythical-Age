"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, X } from "lucide-react";

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
        <div className="confirm-dialog-backdrop" role="presentation">
          <section aria-modal="true" className={`confirm-dialog confirm-dialog--${pending.tone}`} role="dialog">
            <header>
              <div className="confirm-dialog__icon"><AlertTriangle size={18} /></div>
              <div>
                <h2>{pending.title}</h2>
                <p>{pending.body}</p>
              </div>
              <button aria-label="关闭确认弹窗" onClick={() => close(false)} type="button">
                <X size={16} />
              </button>
            </header>
            <footer>
              <button onClick={() => close(false)} type="button">{pending.cancelLabel}</button>
              <button className="confirm-dialog__primary" onClick={() => close(true)} type="button">{pending.confirmLabel}</button>
            </footer>
          </section>
        </div>
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

