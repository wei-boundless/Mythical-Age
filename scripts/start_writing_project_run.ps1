param(
    [string]$BaseUrl = "http://127.0.0.1:8003/api",
    [string]$GraphId = "graph.writing.modular_novel.master",
    [string]$TaskId = "task.writing.modular_novel.master",
    [string]$SessionId = "",
    [string]$WorkspaceView = "task_environment",
    [string]$TaskEnvironmentId = "env.creation.writing",
    [string]$ProjectId = "project.creation.writing.honghuang",
    [string]$ProjectTitle = "洪荒时代",
    [string]$ProjectBriefFile = "output/novel_artifacts/modular_novel/runs/project-honghuang-times-memoryscope-20260523-001/project_brief.md",
    [int]$TargetGroupCount = 2,
    [int]$UnitsPerGroup = 100,
    [int]$TargetMeasureUnits = 700000,
    [int]$UnitTargetMeasure = 3500,
    [int]$UnitsPerBatch = 10,
    [string]$ArtifactRoot = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ([string]::IsNullOrWhiteSpace($SessionId)) {
    $SessionId = "writing-modular-novel-honghuang-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
}

$BriefPath = Join-Path $RepoRoot $ProjectBriefFile
if (-not (Test-Path $BriefPath)) {
    throw "Project brief file not found: $BriefPath"
}

$ProjectBrief = (Get-Content -Raw -Path $BriefPath -Encoding UTF8).Trim()
if ([string]::IsNullOrWhiteSpace($ProjectBrief)) {
    throw "Project brief file is empty: $BriefPath"
}

if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) {
    $ProjectSlug = [Regex]::Replace($ProjectId, '[^0-9A-Za-z\u4e00-\u9fff]+', '-').Trim('-').ToLower()
    $SessionSlug = [Regex]::Replace($SessionId, '[^0-9A-Za-z\u4e00-\u9fff]+', '-').Trim('-').ToLower()
    $ArtifactRoot = "output/novel_artifacts/modular_novel/runs/$ProjectSlug/$SessionSlug"
}

$SessionScope = @{
    workspace_view = $WorkspaceView
    task_environment_id = $TaskEnvironmentId
    project_id = $ProjectId
}

$SessionResolvePayload = @{
    workspace_view = $WorkspaceView
    project_id = $ProjectId
    intent = if ([string]::IsNullOrWhiteSpace($SessionId)) { "new_conversation" } else { "new_conversation" }
    title = "$ProjectTitle 写作图任务"
    preferred_session_id = ""
    create_if_missing = $true
    startup_parameters = @{
        graph_id = $GraphId
        task_id = $TaskId
        source = "scripts.start_writing_project_run"
    }
}

if (-not [string]::IsNullOrWhiteSpace($SessionId) -and $SessionId.StartsWith("session-")) {
    $SessionResolvePayload.intent = "continue_conversation"
    $SessionResolvePayload.preferred_session_id = $SessionId
}

$ResolvedSession = Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/task-environments/$TaskEnvironmentId/sessions/resolve" `
    -ContentType "application/json; charset=utf-8" `
    -Body ($SessionResolvePayload | ConvertTo-Json -Depth 8)

$ResolvedSessionId = [string]$ResolvedSession.session.id
if ([string]::IsNullOrWhiteSpace($ResolvedSessionId)) {
    throw "Task environment session resolver did not return a session id."
}
$SessionId = $ResolvedSessionId

$Payload = @{
    session_id = $SessionId
    task_id = $TaskId
    session_scope = $SessionScope
    include_trace = $true
    dispatch_ready = $true
    run_mode = "dispatch_only"
    initial_inputs = @{
        project_id = $ProjectId
        project_title = $ProjectTitle
        title = $ProjectTitle
        project_brief = $ProjectBrief
        target_group_count = $TargetGroupCount
        units_per_group = $UnitsPerGroup
        target_unit_count = ($TargetGroupCount * $UnitsPerGroup)
        target_measure_units = $TargetMeasureUnits
        target_length = [string]$TargetMeasureUnits
        unit_target_measure = $UnitTargetMeasure
        units_per_batch = $UnitsPerBatch
        batch_target_measure = ($UnitsPerBatch * $UnitTargetMeasure)
        group_target_measure = ($UnitsPerGroup * $UnitTargetMeasure)
        completed_groups = 0
        group_current_measure = 0
        total_current_measure = 0
        volume_index = 1
        chapter_index = 1
        unit_index = 1
        metric_label = "words"
        requested_batch = "每轮连续创作 $UnitsPerBatch 个章节单位，每个单位约 $UnitTargetMeasure 字；审核和记忆提交按同一批次处理。"
        artifact_root = $ArtifactRoot
        human_gate_mode = "auto_continue"
        run_mode = "project_self_running"
        source = "scripts.start_writing_project_run"
    }
}

$Response = Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/orchestration/harness/task-graphs/$GraphId/start" `
    -ContentType "application/json; charset=utf-8" `
    -Body ($Payload | ConvertTo-Json -Depth 8)

$Result = [pscustomobject]@{
    session_id = $SessionId
    session_scope = $SessionScope
    session_created = [bool]$ResolvedSession.created
    graph_id = $GraphId
    task_id = $TaskId
    task_run_id = [string]$Response.task_run_id
    graph_run_id = [string]$Response.graph_run_id
    graph_harness_config_id = [string]$Response.graph_harness_config_id
    node_work_order_count = @($Response.node_work_orders).Count
    first_node_id = if (@($Response.node_work_orders).Count -gt 0) { [string]$Response.node_work_orders[0].node_id } else { "" }
    artifact_root = $ArtifactRoot
    graph_status = [string]$Response.graph_loop_state.status
    source = "scripts.start_writing_project_run"
}

Write-Output ($Result | ConvertTo-Json -Depth 4)
