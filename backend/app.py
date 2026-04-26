from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.chat import router as chat_router
from api.config_api import router as config_router
from api.experiments import router as experiments_router
from api.files import router as files_router
from api.memory import router as memory_router
from api.orchestration import router as orchestration_router
from api.sessions import router as sessions_router
from api.tasks import router as tasks_router
from api.tokens import router as tokens_router
from bootstrap import runtime_lifespan
from runtime.session_store import InvalidSessionId
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
app.include_router(memory_router, prefix="/api", tags=["memory"])
app.include_router(tokens_router, prefix="/api", tags=["tokens"])
app.include_router(config_router, prefix="/api", tags=["config"])
app.include_router(tasks_router, prefix="/api", tags=["tasks"])
app.include_router(experiments_router, prefix="/api", tags=["experiments"])
app.include_router(orchestration_router, prefix="/api", tags=["orchestration"])


@app.exception_handler(InvalidSessionId)
async def invalid_session_id_handler(_: Request, __: InvalidSessionId) -> JSONResponse:
    return JSONResponse({"detail": "Invalid session_id"}, status_code=400)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
