# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：把后端打成单个 Windows 可执行文件。

产物是 `mythical-backend.exe`，由 Electron 主进程在安装目录下启动。它不含
docling / rapidocr / llama-index / qdrant / faiss 等重量级可选依赖——这些模块在后端
中都是函数内延迟导入，缺失时只影响对应的可选能力，主链路（Harness、图系统、运行时、
记忆、权限、能力目录）完整可用。
"""

from pathlib import Path

repo_root = Path(SPECPATH).resolve().parent
backend_root = repo_root / "backend"

# 后端多数包的 __init__ 用模块级 __getattr__ 做延迟再导出，静态分析看不到真实子模块；
# 其中一部分的 collect_submodules 也返回空。这里直接按源码目录枚举，不依赖包扫描。
_collect_roots = [
    "agent_system",
    "api",
    "artifact_system",
    "bootstrap",
    "capability_system",
    "code_environment",
    "context_system",
    "core",
    "evidence",
    "file_management",
    "graph_system",
    "harness",
    "health_system",
    "integrations",
    "knowledge_system",
    "memory_system",
    "modality_index",
    "observability",
    "permissions",
    "project_network_system",
    "project_network_tasks",
    "project_workspaces",
    "prompt_composition",
    "prompt_library",
    "runtime",
    "runtime_objects",
    "sessions",
    "task_system",
]

_source_modules: list[str] = []
for _root in _collect_roots:
    _base = backend_root / _root
    if not _base.is_dir():
        continue
    _source_modules.append(_root)
    for _file in _base.rglob("*.py"):
        _parts = _file.relative_to(backend_root).with_suffix("").parts
        if "__pycache__" in _parts:
            continue
        if _parts[-1] == "__init__":
            _parts = _parts[:-1]
        _source_modules.append(".".join(_parts))

datas = [
    (str(backend_root / "prompt_library" / "prompt_assets"), "prompt_library/prompt_assets"),
    (str(backend_root / "capability_system" / "skills"), "capability_system/skills"),
    (str(backend_root / "capability_system" / "tools" / "registries"), "capability_system/tools/registries"),
    (str(repo_root / "desktop" / "defaults"), "desktop_defaults"),
    (str(repo_root / "extensions" / "vscode"), "extensions/vscode"),
]

hiddenimports = [
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "app",
    "desktop_entry",
]

hiddenimports.extend(_source_modules)

excludes = [
    "docling",
    "rapidocr",
    "llama_index",
    "qdrant_client",
    "faiss",
    "torch",
    "transformers",
    "matplotlib",
    "pytest",
    "tkinter",
    "PyQt5",
    "PySide2",
]

a = Analysis(
    [str(backend_root / "desktop_entry.py")],
    pathex=[str(backend_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mythical-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
