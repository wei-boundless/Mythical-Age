"use client";

import type { ReactNode } from "react";

export function TaskContractManagementPage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--full task-system-object-page--contracts">{children}</section>;
}

export function TaskNodeConfigurationPage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--full task-system-object-page--nodes">{children}</section>;
}
