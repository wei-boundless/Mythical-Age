"use client";

import {
  Boxes,
  FileSearch,
  FlaskConical,
  LibraryBig,
  ScrollText,
  SlidersHorizontal
} from "lucide-react";

const railGroups = [
  {
    title: "Workspace",
    items: [
      {
        icon: LibraryBig,
        label: "会话档案",
        description: "汇总会话、摘要与阶段记录",
        state: "已接主界面"
      },
      {
        icon: FileSearch,
        label: "证据检索",
        description: "RAG、PDF 与结构化数据入口",
        state: "待接二级页"
      }
    ]
  },
  {
    title: "Control",
    items: [
      {
        icon: SlidersHorizontal,
        label: "运行参数",
        description: "模型、路由与上下文策略",
        state: "待接设置面板"
      },
      {
        icon: ScrollText,
        label: "实验记录",
        description: "测试复盘、链路追踪与报告",
        state: "待接报告页"
      }
    ]
  },
  {
    title: "Extensions",
    items: [
      {
        icon: Boxes,
        label: "能力模块",
        description: "技能、工具与子系统扩展入口",
        state: "预留"
      },
      {
        icon: FlaskConical,
        label: "试验场",
        description: "灰度能力、草案功能与调试页",
        state: "预留"
      }
    ]
  }
] as const;

export function RightRail() {
  return (
    <aside className="panel right-rail flex w-full shrink-0 flex-col gap-4 rounded-[34px] p-4 xl:w-[320px]">
      <div className="archive-section-head right-rail__head">
        <div className="archive-section-head__copy">
          <p className="archive-section-head__eyebrow">Navigation</p>
          <h2 className="archive-section-head__title">功能导航</h2>
        </div>
        <div className="tag-chip right-rail__tag">预览</div>
      </div>

      <div className="right-rail__intro">
        当前先作为右侧功能入口栏，后续可以逐步接入设置、报告、证据与扩展模块。
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
                    aria-disabled="true"
                    className="right-rail__item"
                    key={item.label}
                    type="button"
                  >
                    <div className="right-rail__item-icon">
                      <Icon size={17} />
                    </div>
                    <div className="right-rail__item-copy">
                      <div className="right-rail__item-label">{item.label}</div>
                      <div className="right-rail__item-description">{item.description}</div>
                      <div className="right-rail__item-state">{item.state}</div>
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
