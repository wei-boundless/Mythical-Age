"use client";

import { ConfirmDialogProvider } from "@/components/layout/ConfirmDialogProvider";
import { WritingProjectShellPage } from "@/components/workspace/views/task-graph-foreground/WritingProjectShellPage";
import { AppProvider } from "@/lib/store";

export default function WritingProjectPage() {
  return (
    <AppProvider>
      <ConfirmDialogProvider>
        <WritingProjectShellPage />
      </ConfirmDialogProvider>
    </AppProvider>
  );
}
