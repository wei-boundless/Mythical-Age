"""桌面分发包的后端进程入口。

源码模式下后端以 `uvicorn app:app` 从 `backend/` 目录启动，数据根由 `core.project_layout`
沿 `Path(__file__)` 解析到仓库根目录。打包成单个可执行文件后，模块的 `__file__` 指向
解包出来的只读临时目录，源码布局不再成立。

本入口在导入应用之前固定数据根：

- `APP_STORAGE_ROOT`  指向用户目录下的 storage（会话、记忆、任务、运行时状态都落在这里）
- `APP_EXTERNAL_DATA_ROOT` 指向同级的 external data（索引、文档缓存、知识库）
- 首次启动时，若用户目录还没有运行时配置，从随包携带的默认配置播种一份

只做选址，不改变任何业务语义；其余启动逻辑仍由 `app:app` 与 `bootstrap.lifespan` 掌控。
"""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import sys
from pathlib import Path


def _bundled_root() -> Path:
    """随包携带的只读资源根目录（PyInstaller 的临时解包目录）。"""

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    return Path(__file__).resolve().parents[1]


def _user_data_root() -> Path:
    """用户数据根目录，跨升级保留。"""

    override = os.getenv("MYTHICAL_AGE_DATA_DIR", "").strip()
    if override:
        root = Path(override).expanduser()
        return root.resolve() if root.is_absolute() else (Path.cwd() / root).resolve()

    appdata = os.getenv("APPDATA", "").strip()
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return (base / "MythicalAge").resolve()


def _seed_runtime_config(bundled: Path, storage_root: Path) -> None:
    target = storage_root / "runtime_config" / "config.json"
    if target.exists():
        return
    source = bundled / "desktop_defaults" / "runtime_config.json"
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(source.read_text(encoding="utf-8"))
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_knowledge_sources(bundled: Path, external_root: Path) -> None:
    """把随包附带的提示词与知识资源放进外部数据目录，供检索与 MCP 读取。"""

    sources = bundled / "desktop_seed"
    if not sources.exists():
        return
    for entry in sources.iterdir():
        target = external_root / entry.name
        if target.exists():
            continue
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)


def _migrate_legacy_storage(legacy_root: Path, storage_root: Path) -> None:
    """Merge the pre-data-root storage directory without overwriting current data."""

    legacy = legacy_root.resolve()
    target = storage_root.resolve()
    if legacy == target or not legacy.exists() or not legacy.is_dir():
        return
    for source in sorted(legacy.rglob("*")):
        if source.is_dir():
            continue
        relative = source.relative_to(legacy)
        destination = target / relative
        if destination.exists():
            try:
                if destination.read_bytes() == source.read_bytes():
                    source.unlink()
            except OSError:
                continue
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(destination))
        except OSError:
            continue
    for directory in sorted((item for item in legacy.rglob("*") if item.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        legacy.rmdir()
    except OSError:
        pass


def prepare_environment() -> None:
    bundled = _bundled_root()
    data_root = _user_data_root()
    storage_root = data_root / "storage"
    external_root = data_root / "external"

    storage_root.mkdir(parents=True, exist_ok=True)
    external_root.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_storage(data_root.parent / "storage", storage_root)

    for name in (
        "APP_STORAGE_ROOT",
        "APP_EXTERNAL_DATA_ROOT",
    ):
        if not os.getenv(name, "").strip():
            os.environ[name] = str(storage_root if name == "APP_STORAGE_ROOT" else external_root)

    for name in ("APP_INDEXES_ROOT", "APP_DOCUMENT_CACHE_ROOT", "APP_KNOWLEDGE_ROOT", "APP_MODALITY_ARTIFACTS_ROOT"):
        os.environ.pop(name, None)

    _seed_runtime_config(bundled, storage_root)
    _seed_knowledge_sources(bundled, external_root)

    bundled_path = str(bundled)
    if bundled_path not in sys.path:
        sys.path.insert(0, bundled_path)


def main() -> None:
    prepare_environment()

    import uvicorn

    host = os.getenv("MYTHICAL_AGE_BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("MYTHICAL_AGE_BACKEND_PORT", "8003").strip() or "8003")

    from run_uvicorn import _install_windows_selector_loop_policy, _windows_safe_loop_factory

    _install_windows_selector_loop_policy()
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        loop=_windows_safe_loop_factory,
        log_level=os.getenv("MYTHICAL_AGE_BACKEND_LOG_LEVEL", "info").strip() or "info",
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
