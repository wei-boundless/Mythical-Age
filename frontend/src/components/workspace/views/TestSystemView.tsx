"use client";

import { Activity, Bug, FlaskConical, GitBranch, Play, ScrollText } from "lucide-react";

const testProfiles = [
  {
    name: "smoke",
    title: "冒烟测试",
    description: "验证会话接口、SSE 流式回传和前端事件 reducer。",
    command: "python -m harness.run --profile smoke",
    risk: "低风险"
  },
  {
    name: "stable",
    title: "稳定门禁",
    description: "在 smoke 基础上追加 core regression gate。",
    command: "python -m harness.run --profile stable",
    risk: "中风险"
  },
  {
    name: "long",
    title: "长场景测试",
    description: "运行真实用户 60 轮长链场景，检查状态漂移和 follow-up。",
    command: "python -m harness.run --profile long",
    risk: "高耗时"
  }
];

const debugLinks = [
  "run_result.json 汇总每个场景的通过状态、耗时和执行命令。",
  "issues.json 记录失败项、严重程度、artifact 路径和 trace 链接。",
  "trace.jsonl 后续会映射到系统框架图节点与连线。",
  "report.md 用于人工复盘，也可以作为前端报告视图的数据源。"
];

export function TestSystemView() {
  return (
    <div className="workspace-view">
      <header className="workspace-view__header">
        <div>
          <p className="workspace-view__eyebrow">Test System</p>
          <h2 className="workspace-view__title">测试系统</h2>
        </div>
        <div className="tag-chip">实验控制台</div>
      </header>

      <div className="workspace-metrics-grid">
        <div className="workspace-stat">
          <FlaskConical size={18} />
          <span>测试入口</span>
          <strong>harness.run</strong>
        </div>
        <div className="workspace-stat">
          <Activity size={18} />
          <span>运行产物</span>
          <strong>run_result / issues / trace</strong>
        </div>
        <div className="workspace-stat">
          <Bug size={18} />
          <span>debug 目标</span>
          <strong>映射到系统框图</strong>
        </div>
      </div>

      <section className="workspace-section">
        <div className="workspace-section__head">
          <Play size={18} />
          <h3>可接入测试方案</h3>
        </div>
        <div className="framework-grid">
          {testProfiles.map((profile) => (
            <article className="framework-node" key={profile.name}>
              <div className="framework-node__kind">{profile.risk}</div>
              <h4>{profile.title}</h4>
              <p>{profile.description}</p>
              <span>{profile.command}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="workspace-section">
        <div className="workspace-section__head">
          <GitBranch size={18} />
          <h3>前端测试链路</h3>
        </div>
        <div className="visual-flow-grid">
          <div className="visual-flow">
            <div className="visual-flow__label">运行</div>
            <div className="visual-flow__steps">
              <div className="visual-flow__step">
                <span>选择 profile</span>
                <i />
              </div>
              <div className="visual-flow__step">
                <span>创建 run_id</span>
                <i />
              </div>
              <div className="visual-flow__step">
                <span>后台执行 harness</span>
                <i />
              </div>
              <div className="visual-flow__step">
                <span>写入测试产物</span>
              </div>
            </div>
          </div>
          <div className="visual-flow">
            <div className="visual-flow__label">debug</div>
            <div className="visual-flow__steps">
              <div className="visual-flow__step">
                <span>读取 issues</span>
                <i />
              </div>
              <div className="visual-flow__step">
                <span>绑定 graph refs</span>
                <i />
              </div>
              <div className="visual-flow__step">
                <span>高亮节点连线</span>
                <i />
              </div>
              <div className="visual-flow__step">
                <span>查看 trace 细节</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="workspace-section">
        <div className="workspace-section__head">
          <ScrollText size={18} />
          <h3>产物说明</h3>
        </div>
        <div className="flow-list">
          {debugLinks.map((item, index) => (
            <div className="flow-row" key={item}>
              <div className="flow-row__index">{index + 1}</div>
              <p>{item}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
