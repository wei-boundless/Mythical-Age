from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "start_writing_stack.ps1"


def test_start_writing_stack_reuses_healthy_backend_by_default() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$ForceBackendRestart" in text
    assert "if ($SkipBackendRestart -and $ForceBackendRestart)" in text
    assert "$backendHealthy = Test-BackendHealth -Url $HealthUrl" in text
    assert "$backendListeners = @(Get-BackendListeners -BackendPort $BindPort)" in text
    restart_condition = "if ($ForceBackendRestart -or ((-not $backendHealthy) -and $backendListeners.Count -eq 0))"
    assert restart_condition in text
    restart_block = text.split(restart_condition, 1)[1]
    restart_block = restart_block.split("$result = [ordered]@", 1)[0]
    assert "Stop-BackendProcesses" in restart_block
    assert "Start-BackendProcess" in restart_block
    assert "restarted = $backendRestarted" in text
    assert "Refusing to restart an existing backend without -ForceBackendRestart" in text
