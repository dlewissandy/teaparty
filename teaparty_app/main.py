from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from teaparty_app.config import settings
from teaparty_app.db import init_db
from teaparty_app.routers import agent_tasks, agents, auth, conversations, engagements, jobs, organizations, system, tasks, tools, workgroups, workspace

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    app.include_router(auth.router)
    app.include_router(organizations.router)
    app.include_router(workgroups.router)
    app.include_router(conversations.router)
    app.include_router(agents.router)
    app.include_router(tools.router)
    app.include_router(tasks.router)
    app.include_router(engagements.router)
    app.include_router(jobs.router)
    app.include_router(agent_tasks.router)
    app.include_router(workspace.router)
    app.include_router(system.router)

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("teaparty_app.main:app", host="0.0.0.0", port=8000, reload=True)
