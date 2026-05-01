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
