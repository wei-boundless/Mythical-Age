from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from prompting import build_static_prompt


def test_static_prompt_does_not_embed_global_skill_or_tool_catalog() -> None:
    prompt = build_static_prompt(BACKEND_DIR, rag_mode=False)

    assert "SKILLS_SNAPSHOT" not in prompt
    assert "当前可用能力摘要" not in prompt
    assert "Available local capabilities" not in prompt
    assert "get_weather" not in prompt
    assert "get_gold_price" not in prompt


def test_static_prompt_includes_user_visible_receipt_protocol() -> None:
    prompt = build_static_prompt(BACKEND_DIR, rag_mode=False)

    assert "用户可见回执协议" in prompt
    assert "做了什么、影响范围是什么" in prompt
    assert "taskrun_id" in prompt
    assert "只能进入 debug、diagnostics、运行监控详情" in prompt


