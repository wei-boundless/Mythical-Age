"use client";

import { Boxes, ExternalLink, Workflow } from "lucide-react";

import type { RunMonitorSignal } from "@/lib/run-monitor/types";

type RunProjectLaneProps = {
  projects: RunMonitorSignal[];
  onOpen: (signalId: string) => void;
};

function projectStatus(signal: RunMonitorSignal) {
  if (signal.state === "active") return "运行中";
  if (signal.state === "waiting") return "等待推进";
  if (signal.state === "stale") return "需诊断";
  if (signal.state === "failed") return "失败";
  if (signal.state === "completed") return "完成";
  return "已同步";
}

export function RunProjectLane({ projects, onOpen }: RunProjectLaneProps) {
  if (!projects.length) return null;
  return (
    <section className="run-monitor-projects" aria-label="项目运行">
      <header className="run-monitor-lane__head">
        <span>项目</span>
        <em>{projects.length} 个图任务</em>
      </header>
      <div className="run-monitor-projects__list">
        {projects.slice(0, 4).map((project) => (
          <button
            className={`run-monitor-project run-monitor-project--${project.state}`}
            key={project.signal_id}
            onClick={() => onOpen(project.signal_id)}
            type="button"
          >
            <span className="run-monitor-project__mark"><Workflow size={15} /></span>
            <span className="run-monitor-project__main">
              <strong>{project.title}</strong>
              <small>{project.line}</small>
            </span>
            <span className="run-monitor-project__meta">
              <Boxes size={13} />
              <strong>{projectStatus(project)}</strong>
              <small>{project.detail}</small>
            </span>
            <ExternalLink className="run-monitor-project__open" size={13} />
          </button>
        ))}
      </div>
    </section>
  );
}
