"use client";

import {
  Boxes,
  BrainCircuit,
  Bot,
  FlaskConical,
  MessageSquare,
  Network,
  Sparkles,
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
        label: "系统框架",
        description: "总览模块架构、依赖关系与工作流程",
        view: "system-framework"
      },
      {
        icon: Network,
        label: "编排系统",
        description: "负责请求调度、路由决策与执行链编排",
        view: "experiments"
      },
      {
        icon: BrainCircuit,
        label: "记忆系统",
        description: "查询状态记忆、长期记忆和召回结果",
        view: "memory"
      },
      {
        icon: FlaskConical,
        label: "测试系统",
        description: "运行回归、长场景与可视化 debug 实验",
        view: "test-system"
      },
      {
        icon: Boxes,
        label: "操作系统",
        description: "管理 tools、skills 与可调用操作能力",
        view: "capabilities"
      },
      {
        icon: Bot,
        label: "agent系统",
        description: "管理 worker、RAG 子系统和通信协议",
        view: "evidence"
      },
      {
        icon: Sparkles,
        label: "灵魂系统",
        description: "管理 seed、身份锚点与风格切换机制",
        view: "playground"
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
