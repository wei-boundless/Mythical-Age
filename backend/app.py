from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.chat import router as chat_router
from api.config_api import router as config_router
from api.files import router as files_router
from api.file_changes import router as file_changes_router
from api.health_system import router as health_system_router
from api.graph_task_instances import router as graph_task_instances_router
from api.image_assets import router as image_assets_router
from api.memory import router as memory_router
from api.mcp_system import router as mcp_system_router
from api.orchestration import router as orchestration_router
from api.orchestration_catalog import router as orchestration_catalog_router
from api.orchestration_harness import router as orchestration_harness_router
from api.project_workspaces import router as project_workspaces_router
from api.runtime_facts import router as runtime_facts_router
from api.runtime_logs import router as runtime_logs_router
from api.runtime_monitor import router as runtime_monitor_router
from api.runtime_trace import router as runtime_trace_router
from api.capability_system import router as capability_system_router
from api.sessions import router as sessions_router
from api.task_system import router as task_system_router
from api.tokens import router as tokens_router
from api.code_environment import router as code_environment_router
from api.vscode import router as vscode_router
from api.workbench import router as workbench_router
from bootstrap.lifespan import runtime_lifespan
from sessions import InvalidSessionId, SessionPayloadCorrupt, SessionStorageError
from runtime_encoding import configure_process_utf8

configure_process_utf8()


app = FastAPI(
    title="Mini-OpenClaw API",
    version="0.1.0",
    lifespan=runtime_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(sessions_router, prefix="/api", tags=["sessions"])
app.include_router(files_router, prefix="/api", tags=["files"])
app.include_router(file_changes_router, prefix="/api", tags=["file-changes"])
app.include_router(memory_router, prefix="/api", tags=["memory"])
app.include_router(mcp_system_router, prefix="/api", tags=["mcp-system"])
app.include_router(tokens_router, prefix="/api", tags=["tokens"])
app.include_router(config_router, prefix="/api", tags=["config"])
app.include_router(task_system_router, prefix="/api", tags=["tasks"])
app.include_router(health_system_router, prefix="/api", tags=["health-system"])
app.include_router(orchestration_catalog_router, prefix="/api", tags=["orchestration-catalog"])
app.include_router(orchestration_router, prefix="/api", tags=["orchestration"])
app.include_router(orchestration_harness_router, prefix="/api", tags=["orchestration-harness"])
app.include_router(graph_task_instances_router, prefix="/api", tags=["graph-task-instances"])
app.include_router(project_workspaces_router, prefix="/api", tags=["project-workspaces"])
app.include_router(runtime_monitor_router, prefix="/api", tags=["runtime-monitor"])
app.include_router(runtime_logs_router, prefix="/api", tags=["runtime-logs"])
app.include_router(runtime_trace_router, prefix="/api", tags=["runtime-trace"])
app.include_router(runtime_facts_router, prefix="/api", tags=["runtime-facts"])
app.include_router(capability_system_router, prefix="/api", tags=["capability-system"])
app.include_router(image_assets_router, prefix="/api", tags=["image-assets"])
app.include_router(code_environment_router, prefix="/api", tags=["code-environment"])
app.include_router(vscode_router, prefix="/api", tags=["vscode"])
app.include_router(workbench_router, prefix="/api", tags=["workbench"])


@app.exception_handler(InvalidSessionId)
async def invalid_session_id_handler(_: Request, __: InvalidSessionId) -> JSONResponse:
    return JSONResponse({"detail": "Invalid session_id"}, status_code=400)


@app.exception_handler(SessionPayloadCorrupt)
async def corrupt_session_payload_handler(_: Request, exc: SessionPayloadCorrupt) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(SessionStorageError)
async def session_storage_error_handler(_: Request, exc: SessionStorageError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


