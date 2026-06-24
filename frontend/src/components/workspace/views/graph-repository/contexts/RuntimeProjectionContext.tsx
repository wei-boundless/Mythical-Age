"use client";

import { Activity, MessageSquare, RadioTower, SplitSquareHorizontal } from "lucide-react";
import type { GraphTaskInstanceSummary } from "@/lib/api";

export function RuntimeProjectionContext({
  instancesCount,
  selectedInstance,
}: {
  instancesCount: number;
  selectedInstance: GraphTaskInstanceSummary | null;
}) {
  return (
    <section className="graph-os-runtime-context" aria-label="运行投影上下文">
      <div className="graph-os-runtime-hero">
        <RadioTower size={26} />
        <div>
          <span>Runtime Projection</span>
          <strong>多 Agent 实时投影</strong>
          <p>这里承载图运行、节点会话、工具调用、产物引用和人工边决策的观察窗口。它不会切换主会话。</p>
        </div>
      </div>
      <div className="graph-os-runtime-grid">
        <article>
          <Activity size={17} />
          <span>当前实例</span>
          <strong>{selectedInstance?.title || selectedInstance?.graph_task_instance_id || "未选择"}</strong>
          <p>{selectedInstance?.active_graph_run_id || "暂无活跃运行"}</p>
        </article>
        <article>
          <MessageSquare size={17} />
          <span>实例数量</span>
          <strong>{instancesCount}</strong>
          <p>节点会话从实例工作台中打开投影。</p>
        </article>
        <article>
          <SplitSquareHorizontal size={17} />
          <span>承载方式</span>
          <strong>中心区 / 画布插件 / 独立页</strong>
          <p>后续共享同一套 ProjectionSurfaceTarget。</p>
        </article>
      </div>
      <div className="graph-os-policy-card graph-os-policy-card--wide">
        <RadioTower size={16} />
        <span>首阶段保留结构入口，不在组件里硬拼 SSE。实时帧应由统一运行监控事件总线提供，投影窗口只订阅自己的目标。</span>
      </div>
    </section>
  );
}
