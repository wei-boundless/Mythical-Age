"use client";

import {
  BrainCircuit,
  HeartPulse,
  MessageSquare,
  Network,
  Settings2,
  Sparkles,
  Wrench,
  Workflow
} from "lucide-react";

import { useAppStore } from "@/lib/store";
import type { WorkspaceView } from "@/lib/store/types";

const railGroups = [
  {
    title: "Conversation",
    items: [
      {
        icon: MessageSquare,
        label: "会话",
        description: "继续当前对话与任务执行",
        view: "chat"
      }
    ]
  },
  {
    title: "Modules",
    items: [
      {
        icon: Workflow,
        label: "任务系统",
        description: "配置任务域、特定任务、任务装配与协调任务",
        view: "task-system"
      },
      {
        icon: Network,
        label: "编排系统",
        description: "管理 Agent 名册、runtime 与执行权限",
        view: "orchestration"
      },
      {
        icon: BrainCircuit,
        label: "记忆系统",
        description: "查询状态记忆、长期记忆和召回结果",
        view: "memory"
      },
      {
        icon: HeartPulse,
        label: "健康系统",
        description: "验证运行、问题处理、链路证据和技术报告",
        view: "health-system"
      },
      {
        icon: Wrench,
        label: "能力系统",
        description: "管理 skills、工具类型、能力端点和模型可见提示",
        view: "capability-system"
      },
      {
        icon: Sparkles,
        label: "灵魂系统",
        description: "管理 seed、身份锚点与风格切换机制",
        view: "playground"
      },
      {
        icon: Settings2,
        label: "系统配置",
        description: "管理模型、上下文、检索、文档解析和运行限制",
        view: "system-config"
      }
    ]
  }
] satisfies Array<{
  title: string;
  items: Array<{
    icon: typeof MessageSquare;
    label: string;
    description: string;
    view: WorkspaceView;
  }>;
}>;

export function RightRail() {
  const { activeWorkspaceView, setWorkspaceView } = useAppStore();

  return (
    <aside className="panel right-rail flex w-full shrink-0 flex-col gap-4 rounded-[34px] p-4 xl:w-[320px]">
      <div className="archive-section-head right-rail__head">
        <div className="archive-section-head__copy">
          <h2 className="archive-section-head__title">工作台</h2>
        </div>
      </div>

      <div className="right-rail__groups">
        {railGroups.map((group) => (
          <section className="archive-block archive-block--ornate right-rail__group p-4" key={group.title}>
            <p className="right-rail__group-title">{group.title}</p>
            <div className="right-rail__items">
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    aria-pressed={activeWorkspaceView === item.view}
                    className={`right-rail__item ${activeWorkspaceView === item.view ? "right-rail__item--active" : ""}`}
                    key={item.label}
                    onClick={() => setWorkspaceView(item.view)}
                    type="button"
                  >
                    <div className="right-rail__item-icon">
                      <Icon size={17} />
                    </div>
                    <div className="right-rail__item-copy">
                      <div className="right-rail__item-label">{item.label}</div>
                      <div className="right-rail__item-description">{item.description}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </aside>
  );
}

