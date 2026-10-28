"""FastAPI main application for Research Document Search Assistant."""
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from .database import init_db, USE_SQLITE
from .routers import documents

# Ensure data directory exists
Path("data").mkdir(exist_ok=True)

# Initialize database tables
init_db()

app = FastAPI(
    title="科研资料检索助手",
    description="Import, search and manage research documents using seekdb.",
    version="1.0.0",
)

# Mount static files
static_dir = Path(__file__).parent.parent / "static"
templates_dir = Path(__file__).parent.parent / "templates"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(templates_dir))

# Include routers
app.include_router(documents.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main page."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"db_mode": "SQLite (本地开发)" if USE_SQLITE else "seekdb (MySQL协议)"},
    )


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "database": "sqlite" if USE_SQLITE else "seekdb",
    }
