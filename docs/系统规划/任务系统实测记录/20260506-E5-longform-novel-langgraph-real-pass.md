# 20260506 E5 百万字长篇小说 LangGraph 真实实战记录

状态：通过

## 前置条件

- Agent 组：`group.writing.longform_novel_core`
- 正式任务链：项目立项 -> 设定总纲 -> 第一卷卷纲 -> 1-5章顺序批次规划 -> 1-5章顺序批次正文 -> 抽审 -> 连续性快审 -> 编纂清单
- 产物目录：`docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real`
- 生产粒度：每批 `5` 章，正文目标约 `10000` 字；后续长篇推进采用顺序小批次持续交付，而不是并行分卷或单次 20 章长输出。
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
      "chars": 2822,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_01_project_a1:taskinst:turn:lnlg_202605070509531eb01476_01_project_a1:1:longform_novel_project:9344b4a5",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "subtask_1"
        ],
        "node_count": 4,
        "edge_count": 6,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 3
      },
      "coordination_node_count": 4,
      "handoff_count": 6
    },
    {
      "phase_id": "02-bible",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/novel_bible.md",
      "chars": 12500,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_02_bible_a1:taskinst:turn:lnlg_202605070509531eb01476_02_bible_a1:1:novel_bible_build:03ed06e1",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "subtask_1"
        ],
        "node_count": 4,
        "edge_count": 6,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 3
      },
      "coordination_node_count": 4,
      "handoff_count": 6
    },
    {
      "phase_id": "03-volume",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/volumes/volume_01_plan.md",
      "chars": 9308,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_03_volume_a1:taskinst:turn:lnlg_202605070509531eb01476_03_volume_a1:1:volume_planning:029e2f31",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "subtask_1"
        ],
        "node_count": 4,
        "edge_count": 6,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 3
      },
      "coordination_node_count": 4,
      "handoff_count": 6
    },
    {
      "phase_id": "04-batch-plan",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/batches/batch_001_005_plan.md",
      "chars": 3341,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_04_batch_plan_a1:taskinst:turn:lnlg_202605070509531eb01476_04_batch_plan_a1:1:chapter_planning:4cc88445",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3",
          "agent_4"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "agent_4",
          "subtask_1"
        ],
        "node_count": 5,
        "edge_count": 8,
        "execution_edge_count": 4,
        "skipped_cycle_edge_count": 4
      },
      "coordination_node_count": 5,
      "handoff_count": 8
    },
    {
      "phase_id": "05-batch-draft",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/batches/batch_001_005_draft.md",
      "chars": 12459,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_05_batch_draft_a1:taskinst:turn:lnlg_202605070509531eb01476_05_batch_draft_a1:1:chapter_drafting:98972861",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3",
          "agent_4"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "agent_4",
          "subtask_1"
        ],
        "node_count": 5,
        "edge_count": 8,
        "execution_edge_count": 4,
        "skipped_cycle_edge_count": 4
      },
      "coordination_node_count": 5,
      "handoff_count": 8
    },
    {
      "phase_id": "06-batch-review",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/reviews/batch_001_005_review.md",
      "chars": 3151,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_06_batch_review_a1:taskinst:turn:lnlg_202605070509531eb01476_06_batch_review_a1:1:chapter_revision:d8bab2fa",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3",
          "agent_4"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "agent_4",
          "subtask_1"
        ],
        "node_count": 5,
        "edge_count": 8,
        "execution_edge_count": 4,
        "skipped_cycle_edge_count": 4
      },
      "coordination_node_count": 5,
      "handoff_count": 8
    },
    {
      "phase_id": "07-batch-continuity",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/audits/batch_001_005_continuity.md",
      "chars": 6707,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_07_batch_continuity_a1:taskinst:turn:lnlg_202605070509531eb01476_07_batch_continuity_a1:1:continuity_audit:e16c4aa5",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "subtask_1"
        ],
        "node_count": 4,
        "edge_count": 6,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 3
      },
      "coordination_node_count": 4,
      "handoff_count": 6
    },
    {
      "phase_id": "08-compilation",
      "artifact": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real/final_compilation.md",
      "chars": 4592,
      "tool_write_count": 1,
      "task_run_id": "taskrun:lnlg_202605070509531eb01476_08_compilation_a1:taskinst:turn:lnlg_202605070509531eb01476_08_compilation_a1:1:final_compilation:4607399c",
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
        "execution_mode": "planning_only",
        "runtime_execution_bound": false,
        "start_node_ids": [
          "coordinator"
        ],
        "terminal_node_ids": [
          "subtask_1",
          "agent_2",
          "agent_3"
        ],
        "visited_node_ids": [
          "coordinator",
          "agent_2",
          "agent_3",
          "subtask_1"
        ],
        "node_count": 4,
        "edge_count": 6,
        "execution_edge_count": 3,
        "skipped_cycle_edge_count": 3
      },
      "coordination_node_count": 4,
      "handoff_count": 6
    }
  ]
}
```

## 结论

通过。
