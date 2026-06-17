"use client";

import { AppProvider } from "@/lib/store";
import { ConfirmDialogProvider } from "@/components/layout/ConfirmDialogProvider";
import { WorkspaceRouter } from "@/framework/WorkspaceRouter";

export default function Page() {
  return (
    <AppProvider>
      <ConfirmDialogProvider>
        <WorkspaceRouter />
      </ConfirmDialogProvider>
    </AppProvider>
  );
}
