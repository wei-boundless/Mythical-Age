"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
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

import {
  getCodeEnvironment,
  getCodeEnvironmentGitStatus,
  type CodeEnvironmentGitStatus,
  type CodeEnvironmentStatus,
} from "@/lib/api";

import { codeEnvironmentDiagnosticsText } from "./codeEnvironmentDiagnostics";

const CODING_TASK_ENVIRONMENT_ID = "env.coding.vibe_workspace";
const FLOAT_EDGE_GAP = 12;
const FLOAT_DRAG_THRESHOLD = 4;

type FloatingPosition = {
  left: number;
  top: number;
};

type DragState = {
  source: "mouse" | "pointer";
  pointerId: number;
  startX: number;
  startY: number;
  startLeft: number;
  startTop: number;
  moved: boolean;
};

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
  const [position, setPosition] = useState<FloatingPosition | null>(null);
  const [dragging, setDragging] = useState(false);
  const floatRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const suppressClickRef = useRef(false);
  const branchLabel = gitStatus?.branch || "未读取";
  const changedCount = gitChangedCount(gitStatus);
  const additions = gitStatus?.diff_stat?.additions ?? 0;
  const deletions = gitStatus?.diff_stat?.deletions ?? 0;
  const hasDiffStat = Boolean(gitStatus?.diff_stat);
  const ghAvailable = Boolean(gitStatus?.gh_available);
  const alignLeft = Boolean(position && position.left < 320);
  const openDown = Boolean(position && position.top < 300);
  const floatClassName = [
    open ? "development-git-float development-git-float--open" : "development-git-float",
    dragging ? "development-git-float--dragging" : "",
    alignLeft ? "development-git-float--align-left" : "",
    openDown ? "development-git-float--open-down" : "",
  ].filter(Boolean).join(" ");
  const positionStyle = position
    ? {
        left: `${position.left}px`,
        top: `${position.top}px`,
        right: "auto",
        bottom: "auto",
      }
    : undefined;

  const clampPosition = useCallback((left: number, top: number): FloatingPosition => {
    if (typeof window === "undefined") return { left, top };
    const rect = floatRef.current?.getBoundingClientRect();
    const width = rect?.width || 220;
    const height = rect?.height || 34;
    const maxLeft = Math.max(FLOAT_EDGE_GAP, window.innerWidth - width - FLOAT_EDGE_GAP);
    const maxTop = Math.max(FLOAT_EDGE_GAP, window.innerHeight - height - FLOAT_EDGE_GAP);
    return {
      left: Math.min(Math.max(FLOAT_EDGE_GAP, left), maxLeft),
      top: Math.min(Math.max(FLOAT_EDGE_GAP, top), maxTop),
    };
  }, []);

  useEffect(() => {
    setOpen(false);
  }, [scopeKey]);

  useEffect(() => {
    if (!position || typeof window === "undefined") return undefined;
    const handleResize = () => {
      setPosition((current) => current ? clampPosition(current.left, current.top) : current);
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [clampPosition, position]);

  const moveDrag = useCallback((clientX: number, clientY: number) => {
    const dragState = dragStateRef.current;
    if (!dragState) return;
    const deltaX = clientX - dragState.startX;
    const deltaY = clientY - dragState.startY;
    if (!dragState.moved && Math.hypot(deltaX, deltaY) < FLOAT_DRAG_THRESHOLD) return;
    dragState.moved = true;
    suppressClickRef.current = true;
    setDragging(true);
    setPosition(clampPosition(dragState.startLeft + deltaX, dragState.startTop + deltaY));
  }, [clampPosition]);

  const finishDrag = useCallback(() => {
    dragStateRef.current = null;
    setDragging(false);
  }, []);

  const handleDocumentMouseMove = useCallback((event: MouseEvent) => {
    if (dragStateRef.current?.source !== "mouse") return;
    moveDrag(event.clientX, event.clientY);
  }, [moveDrag]);

  const handleDocumentMouseUp = useCallback(() => {
    if (dragStateRef.current?.source !== "mouse") return;
    window.removeEventListener("mousemove", handleDocumentMouseMove);
    window.removeEventListener("mouseup", handleDocumentMouseUp);
    finishDrag();
  }, [finishDrag, handleDocumentMouseMove]);

  useEffect(() => {
    return () => {
      window.removeEventListener("mousemove", handleDocumentMouseMove);
      window.removeEventListener("mouseup", handleDocumentMouseUp);
    };
  }, [handleDocumentMouseMove, handleDocumentMouseUp]);

  function startDrag(source: DragState["source"], pointerId: number, clientX: number, clientY: number) {
    if (dragStateRef.current) return false;
    const rect = floatRef.current?.getBoundingClientRect();
    if (!rect) return false;
    dragStateRef.current = {
      source,
      pointerId,
      startX: clientX,
      startY: clientY,
      startLeft: rect.left,
      startTop: rect.top,
      moved: false,
    };
    return true;
  }

  function handlePointerDragStart(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    if (!startDrag("pointer", event.pointerId, event.clientX, event.clientY)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerDragMove(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.source !== "pointer" || dragState.pointerId !== event.pointerId) return;
    moveDrag(event.clientX, event.clientY);
  }

  function handlePointerDragEnd(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.source !== "pointer" || dragState.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    finishDrag();
  }

  function handleMouseDragStart(event: ReactMouseEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    if (!startDrag("mouse", -1, event.clientX, event.clientY)) return;
    window.addEventListener("mousemove", handleDocumentMouseMove);
    window.addEventListener("mouseup", handleDocumentMouseUp);
  }

  function handleTriggerClick() {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    const nextOpen = !open;
    setOpen(nextOpen);
    if (nextOpen) onRefresh();
  }

  return (
    <div className={floatClassName} ref={floatRef} style={positionStyle}>
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
        aria-label={open ? "收起 Git 浮窗，可拖动" : "打开 Git 浮窗，可拖动"}
        className={changedCount ? "development-git-trigger development-git-trigger--dirty" : "development-git-trigger"}
        onClick={handleTriggerClick}
        onMouseDown={handleMouseDragStart}
        onPointerCancel={handlePointerDragEnd}
        onPointerDown={handlePointerDragStart}
        onPointerMove={handlePointerDragMove}
        onPointerUp={handlePointerDragEnd}
        type="button"
      >
        <GitBranch size={16} />
        <span>{branchLabel}</span>
        <strong>{changedCount}</strong>
      </button>
    </div>
  );
}

export function CodeEnvironmentView() {
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

  const diagnosticsError = codeEnvironmentDiagnosticsText(environment?.pi.diagnostics ?? [], { minLevel: "warning" });
  const visibleError = error || diagnosticsError;

  return (
    <>
      <div className="development-status-slot">
        {visibleError ? (
          <div className="development-alert development-alert--inline">
            <AlertTriangle size={15} />
            <span>{visibleError}</span>
          </div>
        ) : null}
      </div>
      <DevelopmentGitFloatingPanel
        gitStatus={gitStatus}
        loading={loading}
        onRefresh={() => void loadEnvironment()}
        scopeKey={CODING_TASK_ENVIRONMENT_ID}
      />
    </>
  );
}
