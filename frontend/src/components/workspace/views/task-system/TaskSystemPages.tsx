"use client";

import type { ReactNode } from "react";

export function TaskDomainManagementPage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--domain">{children}</section>;
}

export function TaskDefinitionPage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--task-definition">{children}</section>;
}

export function TaskGraphManagementPage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--task-graph">{children}</section>;
}

export function TaskContractManagementPage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--full task-system-object-page--contracts">{children}</section>;
}

export function TaskOrchestrationResourcePage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--full task-system-object-page--orchestration">{children}</section>;
}

export function TaskRuntimeManagementPage({ children }: { children: ReactNode }) {
  return <section className="task-system-object-page task-system-object-page--full task-system-object-page--runtime">{children}</section>;
}
