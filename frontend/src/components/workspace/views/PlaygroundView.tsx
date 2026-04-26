"use client";

import { FileText, ShieldCheck, Sparkles } from "lucide-react";

import { useAppStore } from "@/lib/store";

const soulBoundaries = [
  "seed 负责身份锚点、语言风格、工作习惯、语言组织方式和特定约束。",
  "CORE 负责智能体工作的固有准则，跟在当前 seed prompt 后面生效。",
  "前端切换 seed 后，下一轮会话应读取新的 ACTIVE_SEED.md。",
  "同一轮模型只应看到当前激活的一份 seed，不默认存在多个灵魂。"
];

export function PlaygroundView() {
  const { activeSoulKey, soulOptions, loadInspectorFile } = useAppStore();
  const activeSoul = soulOptions.find((soul) => soul.key === activeSoulKey);
  const configPaths = [
    "soul/agent_core/ACTIVE_SEED.md",
    "soul/agent_core/CORE.md",
    "soul/agent_core/SEED_CATALOG.md",
    activeSoul?.path
  ].filter(Boolean) as string[];

  return (
    <div className="workspace-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Soul System</p>
          <h2 className="workspace-view__title">灵魂系统</h2>
        </div>
        <div className="tag-chip">{activeSoul?.name ?? "未加载"}</div>
      </header>

      <section className="workspace-section workspace-section--hero">
        <div className="workspace-section__head">
          <Sparkles size={18} />
          <h3>当前 seed</h3>
        </div>
        <p className="workspace-copy">
          灵魂系统负责管理 seed 模板、ACTIVE_SEED 切换、前端风格映射，以及 seed prompt 与 CORE prompt 的边界关系。
        </p>
        <div className="workspace-chip-row">
          {soulOptions.map((soul) => (
            <span className="workspace-mini-chip" key={soul.key}>
              {soul.name}
            </span>
          ))}
        </div>
      </section>

      <section className="workspace-section workspace-section--compact">
        <div className="workspace-section__head">
          <ShieldCheck size={18} />
          <h3>边界定义</h3>
        </div>
        <div className="flow-list">
          {soulBoundaries.map((boundary, index) => (
            <div className="flow-row" key={boundary}>
              <div className="flow-row__index">{index + 1}</div>
              <p>{boundary}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="workspace-section workspace-section--compact">
        <div className="workspace-section__head">
          <FileText size={18} />
          <h3>配置入口</h3>
        </div>
        <div className="workspace-chip-grid">
          {configPaths.map((path) => (
            <button
              className="workspace-chip-card"
              key={path}
              onClick={() => void loadInspectorFile(path)}
              type="button"
            >
              {path}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
