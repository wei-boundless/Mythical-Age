from __future__ import annotations

import subprocess
from pathlib import Path

from ..repository import content_hash, utc_now_iso
from ..skeleton_models import SkeletonFactRecord
from ..skeleton_refs import REPO_STABLE_REF, skeleton_fact_id


EXTRACTOR_ID = "file_management.project_structure.skeleton.git_snapshot"
EXTRACTOR_VERSION = "v1"


def extract_git_snapshot_facts(*, project_root: str | Path, build_id: str, generation: int) -> tuple[SkeletonFactRecord, ...]:
    root = Path(project_root).resolve()
    head = _git(root, "rev-parse", "--verify", "HEAD")
    branch = _git(root, "branch", "--show-current")
    facts: list[SkeletonFactRecord] = []
    if head:
        facts.append(
            _fact(
                build_id=build_id,
                generation=generation,
                predicate="git_head",
                object_literal=head,
                qualifiers={"branch": branch},
            )
        )
    return tuple(facts)


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=str(root),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _fact(
    *,
    build_id: str,
    generation: int,
    predicate: str,
    object_literal: str,
    qualifiers: dict[str, object] | None = None,
) -> SkeletonFactRecord:
    payload = dict(qualifiers or {})
    digest = content_hash({"subject": REPO_STABLE_REF, "predicate": predicate, "literal": object_literal, "q": payload})
    return SkeletonFactRecord(
        fact_id=skeleton_fact_id(build_id, generation, "git_snapshot", REPO_STABLE_REF, predicate, "", object_literal, payload),
        build_id=build_id,
        generation=generation,
        source_kind="git_snapshot",
        subject_ref=REPO_STABLE_REF,
        predicate=predicate,
        object_literal=object_literal,
        qualifiers=payload,
        source_snapshot_ref=digest,
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        content_hash=digest,
        confidence="exact",
        created_at=utc_now_iso(),
    )
