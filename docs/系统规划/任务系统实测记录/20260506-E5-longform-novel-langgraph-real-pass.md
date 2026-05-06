# 20260506 E5 百万字长篇小说 LangGraph 真实实战记录

状态：通过

## 前置条件

- Agent 组：`group.writing.longform_novel_core`
- 正式任务链：项目立项 -> 设定总纲 -> 第一卷卷纲 -> 001-020章批次规划 -> 001-020章批次正文 -> 抽审 -> 连续性快审 -> 编纂清单
- 产物目录：`docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real`
- 真实性规则：`prebaked_payload=false`，必须由正式 runtime 调用模型和 `write_file` 工具产生产物。
- 协调任务规则：每一阶段必须进入 LangGraph 协调 runner，并在 trace 中留下 `CoordinationRun / CoordinationNodeRun / AgentHandoffEnvelope / CoordinationMergeResult`。

## 验收结果

```json
{
  "status": "pass",
  "prebaked_payload": false,
  "agent_group_id": "group.writing.longform_novel_core",
  "artifact_root": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real",
  "phase_count": 8,
  "checks": [
    {
      "phase_id": "01-project",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/project_spec.md",
      "chars": 2821,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605060953240ac2fdce_01_project_a1:taskinst:turn:lnlg_202605060953240ac2fdce_01_project_a1:1:longform_novel_project:86f326f4",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "world_seed",
          "character_seed",
          "plot_seed"
        ],
        "terminal_node_ids": [
          "editor_gate"
        ],
        "node_count": 4,
        "edge_count": 3,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 4,
      "handoff_count": 3
    },
    {
      "phase_id": "02-bible",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/novel_bible.md",
      "chars": 8273,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605060953240ac2fdce_02_bible_a1:taskinst:turn:lnlg_202605060953240ac2fdce_02_bible_a1:1:novel_bible_build:1823f236",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "world_bible",
          "character_bible",
          "plot_bible"
        ],
        "terminal_node_ids": [
          "editor_merge"
        ],
        "node_count": 4,
        "edge_count": 3,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 4,
      "handoff_count": 3
    },
    {
      "phase_id": "03-volume",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/volumes/volume_01_plan.md",
      "chars": 9798,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605060953240ac2fdce_03_volume_a1:taskinst:turn:lnlg_202605060953240ac2fdce_03_volume_a1:1:volume_planning:1e996cb8",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "character_arc"
        ],
        "terminal_node_ids": [
          "editor_acceptance"
        ],
        "node_count": 4,
        "edge_count": 3,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 4,
      "handoff_count": 3
    },
    {
      "phase_id": "04-batch-plan",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/batches/batch_001_020_plan.md",
      "chars": 10782,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605060953240ac2fdce_04_batch_plan_a1:taskinst:turn:lnlg_202605060953240ac2fdce_04_batch_plan_a1:1:chapter_planning:298d23bc",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "batch_plan"
        ],
        "terminal_node_ids": [
          "editor_acceptance"
        ],
        "node_count": 6,
        "edge_count": 6,
        "execution_edge_count": 6,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 6,
      "handoff_count": 6
    },
    {
      "phase_id": "05-batch-draft",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/batches/batch_001_020_draft.md",
      "chars": 11361,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605060953240ac2fdce_05_batch_draft_a1:taskinst:turn:lnlg_202605060953240ac2fdce_05_batch_draft_a1:1:chapter_drafting:121dcc2c",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "batch_plan"
        ],
        "terminal_node_ids": [
          "editor_acceptance"
        ],
        "node_count": 6,
        "edge_count": 6,
        "execution_edge_count": 6,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 6,
      "handoff_count": 6
    },
    {
      "phase_id": "06-batch-review",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/reviews/batch_001_020_review.md",
      "chars": 4427,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_2026050610263318b6c014_06_batch_review_a1:taskinst:turn:lnlg_2026050610263318b6c014_06_batch_review_a1:1:chapter_revision:11204c1b",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "batch_plan"
        ],
        "terminal_node_ids": [
          "editor_acceptance"
        ],
        "node_count": 6,
        "edge_count": 6,
        "execution_edge_count": 6,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 6,
      "handoff_count": 6
    },
    {
      "phase_id": "07-batch-continuity",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/audits/batch_001_020_continuity.md",
      "chars": 7669,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_2026050610263318b6c014_07_batch_continuity_a1:taskinst:turn:lnlg_2026050610263318b6c014_07_batch_continuity_a1:1:continuity_audit:ed70a7ab",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "world_consistency",
          "timeline_audit",
          "style_risk"
        ],
        "terminal_node_ids": [
          "editor_audit_merge"
        ],
        "node_count": 4,
        "edge_count": 3,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 4,
      "handoff_count": 3
    },
    {
      "phase_id": "08-compilation",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/final_compilation.md",
      "chars": 5456,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_2026050610263318b6c014_08_compilation_a1:taskinst:turn:lnlg_2026050610263318b6c014_08_compilation_a1:1:final_compilation:882dabcd",
      "attempt": 1,
      "effective_loop_limits": {
        "max_turns": 24,
        "max_model_calls": 24,
        "max_runtime_seconds": null,
        "max_events": 1200,
        "authority": "orchestration.runtime_loop_limits"
      },
      "coordination_engine": "langgraph",
      "langgraph_diagnostics": {
        "compiled": true,
        "start_node_ids": [
          "chapter_bundle"
        ],
        "terminal_node_ids": [
          "editor_final_merge"
        ],
        "node_count": 4,
        "edge_count": 4,
        "execution_edge_count": 4,
        "skipped_cycle_edge_count": 0
      },
      "coordination_node_count": 4,
      "handoff_count": 4
    }
  ]
}
```

## 结论

通过。
