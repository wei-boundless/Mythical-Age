"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  GitBranch,
  GitCommitHorizontal,
  Github,
  Globe2,
  HardDrive,
  Settings,
  SquarePlus,
} from "lucide-react";

import { CenterWorkspaceView } from "@/components/workspace/views/center/CenterWorkspaceView";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import {
  getCodeEnvironment,
  getCodeEnvironmentGitStatus,
  type CodeEnvironmentGitStatus,
  type CodeEnvironmentStatus,
} from "@/lib/api";

const DEVELOPMENT_TASK_ENVIRONMENT_ID = "env.development.sandbox";

function hostConfig() {
  const config = globalThis.__MYTHICAL_AGENT_HOST__ || (typeof window !== "undefined" ? window.mythicalAgentHost?.getConfig() : undefined);
  return {
    mode: config?.hostMode === "desktop" ? "desktop" : "web",
    localRuntimeAvailable: Boolean(config?.localRuntimeAvailable),
    codeEnvironmentHostAvailable: Boolean(config?.codeEnvironmentHostAvailable),
  } as const;
}

function gitChangedCount(gitStatus: CodeEnvironmentGitStatus | null) {
  if (!gitStatus?.available) return 0;
  const changedCount = gitStatus.changed_count;
  return typeof changedCount === "number" && Number.isFinite(changedCount) ? changedCount : gitStatus.items.length;
}

function formatGitNumber(value: unknown) {
  const numberValue = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return numberValue.toLocaleString("en-US");
}

function gitChangesLabel(gitStatus: CodeEnvironmentGitStatus | null) {
  if (!gitStatus) return "未读取";
  if (!gitStatus.available) return gitStatus.error || "Git 不可用";
  const count = gitChangedCount(gitStatus);
  return count ? `${count} changes` : "Clean";
}

function DevelopmentGitFloatingPanel({
  gitStatus,
  loading,
  onRefresh,
  scopeKey,
}: {
  gitStatus: CodeEnvironmentGitStatus | null;
  loading: boolean;
  onRefresh: () => void;
  scopeKey: string;
}) {
  const [open, setOpen] = useState(false);
  const branchLabel = gitStatus?.branch || "未读取";
  const changedCount = gitChangedCount(gitStatus);
  const additions = gitStatus?.diff_stat?.additions ?? 0;
  const deletions = gitStatus?.diff_stat?.deletions ?? 0;
  const hasDiffStat = Boolean(gitStatus?.diff_stat);
  const ghAvailable = Boolean(gitStatus?.gh_available);

  useEffect(() => {
    setOpen(false);
  }, [scopeKey]);

  return (
    <div className={open ? "development-git-float development-git-float--open" : "development-git-float"}>
      {open ? (
        <section className="development-git-popover" aria-label="开发环境状态浮窗">
          <header className="development-git-popover__head">
            <span>Environment</span>
            <button aria-label="刷新环境状态" disabled={loading} onClick={onRefresh} title="刷新环境状态" type="button">
              <Settings size={15} />
            </button>
          </header>

          <div className="development-git-popover__body">
            <div className="development-environment-menu">
              <button className="development-environment-menu__row development-environment-menu__row--active" type="button">
                <SquarePlus size={15} />
                <span>Changes</span>
                <strong aria-label={gitChangesLabel(gitStatus)}>
                  {hasDiffStat ? (
                    <>
                      <span className="development-environment-menu__added">+{formatGitNumber(additions)}</span>
                      <span className="development-environment-menu__deleted">-{formatGitNumber(deletions)}</span>
                    </>
                  ) : (
                    <span>{gitChangesLabel(gitStatus)}</span>
                  )}
                </strong>
              </button>
              <button className="development-environment-menu__row" type="button">
                <HardDrive size={15} />
                <span>Local</span>
              </button>
              <button className="development-environment-menu__row" type="button">
                <GitBranch size={15} />
                <span>{branchLabel}</span>
              </button>
              <button className="development-environment-menu__row" type="button">
                <GitCommitHorizontal size={15} />
                <span>Commit</span>
              </button>
              <button className="development-environment-menu__row development-environment-menu__row--disabled" disabled type="button">
                <Github size={15} />
                <span>{ghAvailable ? "GitHub CLI available" : "GitHub CLI unavailable"}</span>
              </button>
            </div>

            <div className="development-environment-menu__divider" />

            <div className="development-environment-menu">
              <div className="development-environment-menu__section">Sources</div>
              <button className="development-environment-menu__row" type="button">
                <Globe2 size={15} />
                <span>Web search</span>
              </button>
            </div>
          </div>
        </section>
      ) : null}

      <button
        aria-expanded={open}
        aria-label={open ? "收起 Git 浮窗" : "打开 Git 浮窗"}
        className={changedCount ? "development-git-trigger development-git-trigger--dirty" : "development-git-trigger"}
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <GitBranch size={16} />
        <span>{branchLabel}</span>
        <strong>{changedCount}</strong>
      </button>
    </div>
  );
}

export function CodeEnvironmentView({ embedded = false }: { embedded?: boolean }) {
  const [environment, setEnvironment] = useState<CodeEnvironmentStatus | null>(null);
  const [gitStatus, setGitStatus] = useState<CodeEnvironmentGitStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const host = useMemo(() => hostConfig(), []);

  const loadEnvironment = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextEnvironment, nextGitStatus] = await Promise.all([
        getCodeEnvironment(host),
        getCodeEnvironmentGitStatus(),
      ]);
      setEnvironment(nextEnvironment);
      setGitStatus(nextGitStatus);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }, [host]);

  useEffect(() => {
    void loadEnvironment();
  }, [loadEnvironment]);

  const diagnostics = environment?.pi.diagnostics ?? [];
  const diagnosticsError = diagnostics.length ? diagnostics.join("；") : "";
  const visibleError = error || diagnosticsError;

  return (
    <WorkbenchShell
      className={embedded ? "development-environment-shell development-environment-shell--embedded" : "development-environment-shell"}
      hideMainToolbar
      rightPanelLabel="辅助栏"
    >
      <section className="workbench-view-host development-center-host" aria-label="开发任务工作台">
        <div className={visibleError ? "development-layer-body development-layer-body--with-alert" : "development-layer-body"}>
          {visibleError ? (
            <div className="development-alert development-alert--inline">
              <AlertTriangle size={15} />
              <span>{visibleError}</span>
            </div>
          ) : null}
          <CenterWorkspaceView taskEnvironmentId={DEVELOPMENT_TASK_ENVIRONMENT_ID} />
        </div>

        <DevelopmentGitFloatingPanel
          gitStatus={gitStatus}
          loading={loading}
          onRefresh={() => void loadEnvironment()}
          scopeKey={DEVELOPMENT_TASK_ENVIRONMENT_ID}
        />
      </section>
    </WorkbenchShell>
  );
}
