"use client";

import { Bot, Eraser, FileText, GripHorizontal, MessageSquare, Minimize2, PanelRightOpen, Play, ShieldCheck } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  createHealthAgentConversationSession,
  createHealthManagementCommand,
  sendHealthAgentConversationMessage,
  type HealthAgentConversationMessage,
  type HealthAgentConversationSession,
  type HealthAgentRun,
  type HealthIssue
} from "@/lib/api";

type DockMode = "idle" | "sending" | "delegating" | "blocked" | "failed";

function targetLabel(issue: HealthIssue | null, run: HealthAgentRun | null) {
  if (issue) {
    return "已绑定问题";
  }
  if (run) {
    return "已绑定运行";
  }
  return "未绑定";
}

export function HealthAgentDock({
  selectedIssue,
  selectedRun,
  running,
  onExplainRun,
  onOpenReport
}: {
  selectedIssue: HealthIssue | null;
  selectedRun: HealthAgentRun | null;
  running: boolean;
  onExplainRun: () => void;
  onOpenReport: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ x: 24, y: 120 });
  const [ready, setReady] = useState(false);
  const [mounted, setMounted] = useState(false);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);
  const suppressClickRef = useRef(false);
  const [session, setSession] = useState<HealthAgentConversationSession | null>(null);
  const [mode, setMode] = useState<DockMode>("idle");
  const [messages, setMessages] = useState<HealthAgentConversationMessage[]>([
    {
      message_id: "local:intro",
      session_id: "local",
      role: "assistant",
      content: "可以把当前问题或运行交给我分析。我只读取已绑定的健康证据，输出问题报告草案。",
      created_at: Date.now() / 1000
    }
  ]);
  const [draft, setDraft] = useState("");
  const boundLabel = useMemo(() => targetLabel(selectedIssue, selectedRun), [selectedIssue, selectedRun]);
  const activeIssueRef = selectedIssue?.issue_id || "";
  const activeRunRef = selectedRun?.run_id || "";

  function getBoxSize(isOpen = open) {
    return {
      width: isOpen ? Math.min(430, window.innerWidth - 16) : 196,
      height: isOpen ? Math.min(620, window.innerHeight - 16) : 56
    };
  }

  function clampPosition(next: { x: number; y: number }, isOpen = open) {
    const { width, height } = getBoxSize(isOpen);
    return {
      x: Math.max(8, Math.min(window.innerWidth - width - 8, next.x)),
      y: Math.max(8, Math.min(window.innerHeight - height - 8, next.y))
    };
  }

  useEffect(() => {
    setMounted(true);
    try {
      const saved = window.localStorage.getItem("health-agent-dock-position");
      if (saved) {
        const parsed = JSON.parse(saved) as { x?: number; y?: number };
        if (Number.isFinite(parsed.x) && Number.isFinite(parsed.y)) {
          setPosition(clampPosition({ x: Number(parsed.x), y: Number(parsed.y) }, false));
          setReady(true);
          return;
        }
      }
    } catch {
      // Ignore malformed local state and fall back to the default workspace position.
    }
    setPosition(clampPosition({ x: Math.max(24, window.innerWidth - 560), y: 124 }, false));
    setReady(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!ready) return;
    setPosition((current) => clampPosition(current, open));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ready]);

  useEffect(() => {
    if (!ready) return;
    try {
      window.localStorage.setItem("health-agent-dock-position", JSON.stringify(position));
    } catch {
      // Non-critical; dragging should still work when storage is blocked.
    }
  }, [position, ready]);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    async function ensureSession() {
      try {
        const response = await createHealthAgentConversationSession({
          active_issue_ref: activeIssueRef,
          active_run_ref: activeRunRef
        });
        if (!cancelled) {
          setSession(response.session);
          if (response.messages.length) {
            setMessages(response.messages);
          }
          setMode("idle");
        }
      } catch {
        if (!cancelled) {
          setMode("failed");
          setMessages((prev) => [
            ...prev,
            {
              message_id: `local:session-failed:${Date.now()}`,
              session_id: "local",
              role: "assistant",
              content: "健康管家会话创建失败。原生健康操作台不受影响，你仍然可以直接操作健康系统。",
              created_at: Date.now() / 1000
            }
          ]);
        }
      }
    }
    void ensureSession();
    return () => {
      cancelled = true;
    };
  }, [activeIssueRef, activeRunRef, open]);

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      const drag = dragRef.current;
      if (!drag || event.pointerId !== drag.pointerId) {
        return;
      }
      const deltaX = event.clientX - drag.startX;
      const deltaY = event.clientY - drag.startY;
      if (Math.abs(deltaX) > 4 || Math.abs(deltaY) > 4) {
        drag.moved = true;
      }
      const nextX = drag.originX + event.clientX - drag.startX;
      const nextY = drag.originY + event.clientY - drag.startY;
      setPosition(clampPosition({ x: nextX, y: nextY }));
    }

    function handlePointerUp(event: PointerEvent) {
      const drag = dragRef.current;
      if (drag?.pointerId === event.pointerId) {
        suppressClickRef.current = drag.moved;
        dragRef.current = null;
        if (!open && !drag.moved) {
          setOpen(true);
        }
        window.setTimeout(() => {
          suppressClickRef.current = false;
        }, 0);
      }
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    function handleResize() {
      setPosition((current) => clampPosition(current));
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function beginDrag(event: ReactPointerEvent) {
    if (open && (event.target as HTMLElement).closest("button, input")) {
      return;
    }
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: position.x,
      originY: position.y,
      moved: false
    };
  }

  async function submitDraft() {
    const value = draft.trim();
    if (!value) {
      return;
    }
    setMode("sending");
    const localUser: HealthAgentConversationMessage = {
      message_id: `local:user:${Date.now()}`,
      session_id: session?.session_id || "local",
      role: "user",
      content: value,
      created_at: Date.now() / 1000
    };
    setMessages((prev) => [
      ...prev,
      localUser
    ]);
    setDraft("");
    if (!session) {
      setMode("failed");
      return;
    }
    try {
      const response = await sendHealthAgentConversationMessage(session.session_id, {
        role: "user",
        content: value
      });
      setMessages((prev) => {
        const next = prev.map((item) => (item.message_id === localUser.message_id ? response.message : item));
        if (response.assistant_message) {
          next.push(response.assistant_message);
        }
        return next;
      });
      setMode("idle");
    } catch {
      setMode("failed");
    }
  }

  async function delegateCommand(commandType: "analyze_trace" | "draft_case" | "verify_fix") {
    const targetRef = activeIssueRef || activeRunRef;
    if (!targetRef || !session) {
      setMode("blocked");
      setMessages((prev) => [
        ...prev,
        {
          message_id: `local:block:${Date.now()}`,
          session_id: session?.session_id || "local",
          role: "assistant",
          content: !targetRef ? "请先绑定一个健康问题或运行，再让我代操。" : "健康管家会话还没建立，稍等一下再试。",
          created_at: Date.now() / 1000
        }
      ]);
      return;
    }
    setMode("delegating");
    try {
      const response = await createHealthManagementCommand({
        command_type: commandType,
        initiator_type: "agent",
        initiator_ref: session.agent_id,
        source: "health_agent_dock",
        conversation_session_ref: session.session_id,
        target_scope: activeIssueRef ? "health_issue" : "health_agent_run",
        target_ref: targetRef,
        health_action: commandType === "draft_case" ? "case_draft" : commandType === "verify_fix" ? "fix_verification" : "issue_triage",
        payload: {
          active_issue_ref: activeIssueRef,
          active_run_ref: activeRunRef
        }
      });
      const content = response.receipt.accepted
        ? `已提交代操命令并收到回执：${response.receipt.status}。报告：${response.receipt.report_ref || "待生成"}。`
        : `代操被门禁拒绝：${response.receipt.blocked_reasons.join(" / ") || response.receipt.status}。`;
      setMessages((prev) => [
        ...prev,
        {
          message_id: `local:receipt:${response.receipt.receipt_id}`,
          session_id: session.session_id,
          role: "assistant",
          content,
          command_ref: response.command.command_id,
          receipt_ref: response.receipt.receipt_id,
          report_ref: response.receipt.report_ref,
          created_at: Date.now() / 1000
        }
      ]);
      setMode(response.receipt.accepted ? "idle" : "blocked");
    } catch {
      setMode("failed");
      setMessages((prev) => [
        ...prev,
        {
          message_id: `local:delegate-failed:${Date.now()}`,
          session_id: session.session_id,
          role: "assistant",
          content: "代操命令提交失败。健康系统原生操作台仍可直接使用。",
          created_at: Date.now() / 1000
        }
      ]);
    }
  }

  if (!mounted) {
    return null;
  }

  const dock = !open ? (
      <div
        className="health-agent-launcher"
        onPointerDown={beginDrag}
        style={{ left: position.x, opacity: ready ? 1 : 0, top: position.y }}
      >
        <button
          onClick={() => {
            if (!suppressClickRef.current) {
              setOpen(true);
            }
          }}
          type="button"
        >
          <Bot size={18} />
          <span>健康管家</span>
        </button>
        <GripHorizontal size={15} />
      </div>
    ) : (
    <aside className="health-agent-dock" style={{ left: position.x, opacity: ready ? 1 : 0, top: position.y }}>
      <header onPointerDown={beginDrag}>
        <div>
          <span>玄女健康管家</span>
          <strong>{running || mode === "delegating" ? "正在分析" : selectedIssue || selectedRun ? "已绑定上下文" : "空闲"}</strong>
          <em>{boundLabel}</em>
        </div>
        <div className="health-agent-dock__window-controls">
          <GripHorizontal size={15} />
          <button aria-label="折叠健康管家" onClick={() => setOpen(false)} type="button">
            <Minimize2 size={16} />
          </button>
        </div>
      </header>

      <div className="health-agent-dock__scope">
        <ShieldCheck size={15} />
        <span>只读已绑定证据，只生成问题报告草案；不改源码、不执行命令、不写长期记忆。</span>
      </div>

      <div className="health-agent-dock__messages">
        {messages.map((message, index) => (
          <article className={`health-agent-message health-agent-message--${message.role}`} key={message.message_id || `${message.role}-${index}`}>
            {message.content}
          </article>
        ))}
      </div>

      <div className="health-agent-dock__actions">
        <button disabled={!selectedIssue || running || mode === "delegating"} onClick={() => void delegateCommand("analyze_trace")} type="button">
          <Play size={14} />
          分析当前问题
        </button>
        <button disabled={!selectedIssue || running || mode === "delegating"} onClick={() => void delegateCommand("draft_case")} type="button">
          <FileText size={14} />
          复现草案
        </button>
        <button disabled={!selectedRun} onClick={onExplainRun} type="button">
          <PanelRightOpen size={14} />
          查看链路分析
        </button>
        <button disabled={!selectedRun && !selectedIssue} onClick={onOpenReport} type="button">
          <FileText size={14} />
          问题报告
        </button>
        <button onClick={() => setMessages([])} type="button">
          <Eraser size={14} />
          清空
        </button>
      </div>

      <label className="health-agent-dock__input">
        <MessageSquare size={15} />
        <input
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              void submitDraft();
            }
          }}
          placeholder="描述要检查的问题"
          value={draft}
        />
      </label>
    </aside>
  );

  return createPortal(dock, document.body);
}
