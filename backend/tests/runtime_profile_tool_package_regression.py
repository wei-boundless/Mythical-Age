from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.orchestration_catalog import AgentRuntimeProfileRequest
from agent_system.profiles.runtime_profile_registry import _profile_from_dict


def test_runtime_profile_resolves_tool_package_operations() -> None:
    profile = _profile_from_dict(
        {
            "agent_profile_id": "test_profile",
            "agent_id": "agent:test",
            "allowed_tool_packages": [
                {"package_id": "pkg.git.read"},
                {"package_id": "pkg.git.write", "exclude_operations": ["op.git_restore"]},
            ],
            "extra_allowed_operations": ["op.model_response", "op.read_file"],
            "blocked_operations": ["op.git_push", "op.git_restore"],
        }
    )
    assert "op.model_response" in profile.allowed_operations
    assert "op.git_status" in profile.allowed_operations
    assert "op.git_commit" in profile.allowed_operations
    assert "op.read_file" in profile.allowed_operations
    assert "op.git_restore" not in profile.allowed_operations
    assert "op.git_push" not in profile.allowed_operations
    payload = profile.to_dict()
    assert payload["allowed_tool_packages"][0]["package_id"] == "pkg.git.read"
    assert payload["final_allowed_operations"] == payload["allowed_operations"]


def test_runtime_profile_ignores_allowed_operations_payload_as_source() -> None:
    profile = _profile_from_dict(
        {
            "agent_profile_id": "test_profile",
            "agent_id": "agent:test",
            "allowed_tool_packages": [{"package_id": "pkg.filesystem.read"}],
            "allowed_operations": ["op.write_file"],
            "blocked_operations": [],
        }
    )

    assert "op.read_file" in profile.allowed_operations
    assert "op.write_file" not in profile.allowed_operations


def test_runtime_profile_request_rejects_allowed_operations_payload() -> None:
    with pytest.raises(ValidationError):
        AgentRuntimeProfileRequest.model_validate(
            {
                "agent_profile_id": "test_profile",
                "allowed_tool_packages": [{"package_id": "pkg.filesystem.read"}],
                "extra_allowed_operations": ["op.model_response"],
                "allowed_operations": ["op.write_file"],
            }
        )

