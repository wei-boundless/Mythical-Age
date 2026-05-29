$ErrorActionPreference = 'Stop'
try {
  $body = '{
  "graph_harness_config_id": "ghcfg:graph_writing_modular_novel_master:9f92fa4011de3dec",
  "max_node_steps": 6,
  "max_dispatch_requests": 1,
  "max_runtime_seconds": 0,
  "max_loop_iterations": 4,
  "max_node_executions": 1,
  "max_dispatches": 1
}'
  $response = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8003/api/orchestration/harness/graph-runs/grun:graph_writing_modular_novel_master:1780098442476/run-until-idle' -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 1800
  $response | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath 'D:\AI应用\langchain-agent\storage\tasks\writing_graph_protocol_retest_scope_run_until_idle_1_latest.json' -Encoding UTF8
} catch {
  ($_ | Out-String) | Set-Content -LiteralPath 'D:\AI应用\langchain-agent\storage\tasks\writing_graph_protocol_retest_scope_run_until_idle_1_stderr.txt' -Encoding UTF8
  exit 1
}
