from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from maintenance.longform_novel_real_acceptance import _contains_required_term


def test_longform_real_acceptance_accepts_scene_beats_as_batch_plan_alias() -> None:
    content = "# 批次规划\n\n## 场景节拍\n- 第001章\n- 第005章\n"

    assert _contains_required_term(
        content,
        normalized=content.replace(",", ""),
        term="章节节拍",
    )
