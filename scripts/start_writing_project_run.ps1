param(
    [string]$BaseUrl = "http://127.0.0.1:8004/api",
    [string]$GraphId = "graph.writing.simple_novel",
    [string]$TaskId = "task.writing.simple_novel.formal_million_word_run",
    [string]$SessionId = "",
    [string]$ProjectId = "project:honghuang-times",
    [string]$ProjectTitle = "洪荒时代",
    [string]$ProjectBriefFile = "output/novel_artifacts/simple_novel/project_brief.md",
    [int]$TargetWords = 1000000,
    [int]$ChapterTargetWords = 2000,
    [int]$ChaptersPerRound = 10,
    [string]$ArtifactRoot = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if ([string]::IsNullOrWhiteSpace($SessionId)) {
    $SessionId = "writing-simple-novel-honghuang-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
}

$BriefPath = Join-Path $RepoRoot $ProjectBriefFile
if (-not (Test-Path $BriefPath)) {
    $fallbackBrief = Get-ChildItem `
        -Path (Join-Path $RepoRoot "output/novel_artifacts/simple_novel/runs") `
        -Recurse `
        -File `
        -Filter "project_brief.md" `
        -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -ne $fallbackBrief) {
        $BriefPath = $fallbackBrief.FullName
    } else {
        throw "Project brief file not found: $BriefPath"
    }
}

$ProjectBrief = (Get-Content -Raw -Path $BriefPath -Encoding UTF8).Trim()
if ([string]::IsNullOrWhiteSpace($ProjectBrief)) {
    throw "Project brief file is empty: $BriefPath"
}

if ([string]::IsNullOrWhiteSpace($ArtifactRoot)) {
    $ArtifactRoot = "output/novel_artifacts/simple_novel/runs/$SessionId"
}

$Payload = @{
    session_id = $SessionId
    task_id = $TaskId
    require_published = $true
    include_trace = $true
    execute_initial_stage = $true
    initial_inputs = @{
        project_id = $ProjectId
        project_title = $ProjectTitle
        title = $ProjectTitle
        project_brief = $ProjectBrief
        target_words = $TargetWords
        target_length = [string]$TargetWords
        chapter_target_words = $ChapterTargetWords
        chapters_per_round = $ChaptersPerRound
        chapter_batch_size = $ChaptersPerRound
        requested_batch = "每轮连续创作 $ChaptersPerRound 章，每章约 $ChapterTargetWords 字；审核和记忆提交按同一批次处理。"
        artifact_root = $ArtifactRoot
        human_gate_mode = "auto_continue"
        run_mode = "project_self_running"
        source = "scripts.start_writing_project_run"
    }
}

$Response = Invoke-RestMethod `
    -Method Post `
    -Uri "$BaseUrl/orchestration/runtime-loop/task-graphs/$GraphId/start" `
    -ContentType "application/json; charset=utf-8" `
    -Body ($Payload | ConvertTo-Json -Depth 8)

$Result = [pscustomobject]@{
    session_id = $SessionId
    graph_id = $GraphId
    task_id = $TaskId
    task_run_id = [string]$Response.task_run_id
    coordination_run_id = [string]$Response.coordination_run_id
    artifact_root = $ArtifactRoot
    initial_stage_execution_background = [bool]$Response.initial_stage_execution_background
    source = "scripts.start_writing_project_run"
}

Write-Output ($Result | ConvertTo-Json -Depth 4)
