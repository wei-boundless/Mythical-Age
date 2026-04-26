from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from api.deps import require_runtime

router = APIRouter()

ACTIVE_SEED_PATH = "soul/agent_core/ACTIVE_SEED.md"
CORE_PATH = "soul/agent_core/CORE.md"
AGENT_PROFILE_PATH = "soul/agent.md"
SEED_CATALOG_PATH = "soul/agent_core/SEED_CATALOG.md"
SOUL_PORTRAIT_MAX_BYTES = 8 * 1024 * 1024

SEED_PATHS: dict[str, str] = {
    "hebo": "soul/agent_core/seeds/hebo.md",
    "siyue": "soul/agent_core/seeds/siyue.md",
    "zhurong": "soul/agent_core/seeds/zhurong.md",
    "xuannv": "soul/agent_core/seeds/xuannv.md",
}

SOUL_NAMES: dict[str, str] = {
    "hebo": "河伯",
    "siyue": "四岳",
    "zhurong": "祝融",
    "xuannv": "玄女",
}

EDITABLE_SOUL_PATHS = {
    ACTIVE_SEED_PATH,
    CORE_PATH,
    AGENT_PROFILE_PATH,
    SEED_CATALOG_PATH,
    *SEED_PATHS.values(),
}


class SoulSwitchRequest(BaseModel):
    key: str = Field(..., min_length=1)
    source: str = Field(default="frontend")


class SoulFileSaveRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str
    reason: str = Field(default="frontend_edit")


def _project_root_from_backend(base_dir: Path) -> Path:
    return base_dir.resolve().parent


def _portrait_path(base_dir: Path, key: str) -> Path:
    if key not in SEED_PATHS:
        raise HTTPException(status_code=404, detail="Unknown soul seed")
    souls_dir = (_project_root_from_backend(base_dir) / "frontend" / "public" / "souls").resolve()
    path = (souls_dir / f"{key}.png").resolve()
    if souls_dir not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid portrait path")
    return path


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk")
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _resolve_soul_path(base_dir: Path, path: str) -> Path:
    normalized = _normalize_path(path)
    if normalized not in EDITABLE_SOUL_PATHS:
        raise HTTPException(status_code=400, detail="Path is not a managed soul file")
    candidate = (base_dir / normalized).resolve()
    root = base_dir.resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    return candidate


def _extract_name(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        for left, right in (("“", "”"), ('"', '"')):
            if left in stripped and right in stripped:
                value = stripped.split(left, 1)[1].split(right, 1)[0].strip()
                if value:
                    return value
    return fallback


def _seed_key_from_content(base_dir: Path, active_content: str) -> str:
    normalized_active = active_content.strip()
    for key, path in SEED_PATHS.items():
        if _read_text(base_dir / path).strip() == normalized_active:
            return key
    for key, name in SOUL_NAMES.items():
        if name in active_content:
            return key
    return "hebo"


def _file_payload(base_dir: Path, path: str, *, label: str, role: str, model_visible: bool, order: int | None) -> dict[str, Any]:
    file_path = base_dir / path
    content = _read_text(file_path)
    updated_at = file_path.stat().st_mtime if file_path.exists() else None
    return {
        "path": path,
        "label": label,
        "role": role,
        "model_visible": model_visible,
        "injection_order": order,
        "content": content,
        "chars": len(content),
        "updated_at": updated_at,
    }


def _seed_payload(base_dir: Path, key: str, active_key: str) -> dict[str, Any]:
    path = SEED_PATHS[key]
    content = _read_text(base_dir / path)
    portrait_path = _portrait_path(base_dir, key)
    portrait_updated_at = portrait_path.stat().st_mtime if portrait_path.exists() else None
    return {
        **_file_payload(
            base_dir,
            path,
            label=SOUL_NAMES[key],
            role="候选灵魂契约",
            model_visible=key == active_key,
            order=10 if key == active_key else None,
        ),
        "key": key,
        "name": _extract_name(content, SOUL_NAMES[key]),
        "active": key == active_key,
        "portrait_path": f"/souls/{key}.png",
        "portrait_updated_at": portrait_updated_at,
    }


def build_soul_catalog(base_dir: Path) -> dict[str, Any]:
    active_content = _read_text(base_dir / ACTIVE_SEED_PATH)
    active_key = _seed_key_from_content(base_dir, active_content)
    seeds = [_seed_payload(base_dir, key, active_key) for key in SEED_PATHS]
    active_seed = next((seed for seed in seeds if seed["key"] == active_key), seeds[0])
    static_files = [
        _file_payload(
            base_dir,
            ACTIVE_SEED_PATH,
            label="当前灵魂契约",
            role="当前真正进入模型的灵魂设定",
            model_visible=True,
            order=10,
        ),
        _file_payload(
            base_dir,
            CORE_PATH,
            label="通用静态准则",
            role="所有灵魂共享的事实、执行和输出底线",
            model_visible=True,
            order=20,
        ),
        _file_payload(
            base_dir,
            AGENT_PROFILE_PATH,
            label="长期项目偏好",
            role="用户或项目长期稳定生效的偏好与口径",
            model_visible=True,
            order=30,
        ),
        _file_payload(
            base_dir,
            SEED_CATALOG_PATH,
            label="候选灵魂目录",
            role="只给人看的候选灵魂说明，不直接进入模型",
            model_visible=False,
            order=None,
        ),
    ]
    return {
        "active_soul_key": active_key,
        "active_soul_name": active_seed["name"],
        "injection_chain": [
            {"order": 10, "label": "当前灵魂契约", "path": ACTIVE_SEED_PATH},
            {"order": 20, "label": "通用静态准则", "path": CORE_PATH},
            {"order": 30, "label": "长期项目偏好", "path": AGENT_PROFILE_PATH},
        ],
        "static_files": static_files,
        "seeds": seeds,
    }


@router.get("/soul/catalog")
async def soul_catalog() -> dict[str, Any]:
    runtime = require_runtime()
    return build_soul_catalog(runtime.base_dir)


@router.post("/soul/switch")
async def switch_soul(payload: SoulSwitchRequest) -> dict[str, Any]:
    runtime = require_runtime()
    key = payload.key.strip()
    if key not in SEED_PATHS:
        raise HTTPException(status_code=404, detail="Unknown soul seed")
    source_path = runtime.base_dir / SEED_PATHS[key]
    content = _read_text(source_path)
    if not content.strip():
        raise HTTPException(status_code=404, detail="Soul seed is empty or missing")
    _write_text(runtime.base_dir / ACTIVE_SEED_PATH, content)
    runtime.refresh_indexes_for_path(ACTIVE_SEED_PATH)
    return build_soul_catalog(runtime.base_dir)


@router.put("/soul/files")
async def save_soul_file(payload: SoulFileSaveRequest) -> dict[str, Any]:
    runtime = require_runtime()
    normalized = _normalize_path(payload.path)
    file_path = _resolve_soul_path(runtime.base_dir, normalized)
    _write_text(file_path, payload.content)
    runtime.refresh_indexes_for_path(normalized)
    return build_soul_catalog(runtime.base_dir)


@router.post("/soul/portraits/{key}")
async def upload_soul_portrait(key: str, file: UploadFile = File(...)) -> dict[str, Any]:
    runtime = require_runtime()
    normalized_key = key.strip().lower()
    if normalized_key not in SEED_PATHS:
        raise HTTPException(status_code=404, detail="Unknown soul seed")
    if file.content_type not in {"image/png", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="请上传 PNG 立绘")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="立绘文件为空")
    if len(content) > SOUL_PORTRAIT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="立绘文件不能超过 8MB")
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="请上传有效的 PNG 立绘")

    portrait_path = _portrait_path(runtime.base_dir, normalized_key)
    portrait_path.parent.mkdir(parents=True, exist_ok=True)
    portrait_path.write_bytes(content)
    return build_soul_catalog(runtime.base_dir)
