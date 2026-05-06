# 20260506 E5 百万字长篇小说 LangGraph 真实实战记录

状态：失败

## 前置条件

- Agent 组：`group.writing.longform_novel_core`
- 正式任务链：项目立项 -> 设定总纲 -> 第一卷卷纲 -> 001-020章批次规划 -> 001-020章批次正文 -> 抽审 -> 连续性快审 -> 编纂清单
- 产物目录：`docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real`
- 真实性规则：`prebaked_payload=false`，必须由正式 runtime 调用模型和 `write_file` 工具产生产物。
- 协调任务规则：每一阶段必须进入 LangGraph 协调 runner，并在 trace 中留下 `CoordinationRun / CoordinationNodeRun / AgentHandoffEnvelope / CoordinationMergeResult`。

## 验收结果

```json
{
  "status": "fail",
  "prebaked_payload": false,
  "error": "Invalid session_id",
  "artifact_root": "docs/系统规划/任务系统实测记录/artifacts/20260506/E5-longform-novel-langgraph-real",
  "completed_phase_count": 6,
  "run_token": "20260506-092422-2e813faa"
}
```

## 结论

失败。
