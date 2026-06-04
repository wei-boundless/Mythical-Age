from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime.sandbox_artifacts import publish_or_resolve_artifact_ref


def test_image_asset_src_resolves_to_project_storage_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox"
    image = project_root / "storage" / "generated" / "images" / "hero.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\nhero")

    resolved = publish_or_resolve_artifact_ref(
        {"src": "/api/image-assets/files/hero.png", "kind": "image"},
        project_root=project_root,
        sandbox_root=sandbox_root,
        artifact_root="storage/generated/images",
        publish_roots=("storage/generated/images",),
    )

    assert resolved == image.resolve()
