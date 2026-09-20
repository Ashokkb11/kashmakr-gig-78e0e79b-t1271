# backend/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os, time, json

app = FastAPI(title="KashMakr gig_78e0e79b - T1271 Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = Path(__file__).parent.parent / "frontend"

@app.get("/health")
@app.head("/health")
def health() -> dict:
    return {"status": "ok", "gig_id": "gig_78e0e79b - T1271", "timestamp": time.time()}

@app.get("/api/info")
def info() -> dict:
    return {
        "gig_id": "gig_78e0e79b - T1271",
        "modules": [],
        "media_assets": [],
        "runtime": "Python 3.12 (Render Cloud)"
    }

@app.post("/api/run")
@app.get("/api/run")
async def run_service(request: Request) -> dict:
    try: body = await request.json()
    except Exception: body = {}
    return {
        "status": "success",
        "gig_id": "gig_78e0e79b - T1271",
        "action": "executed",
        "modules_loaded": 0,
        "timestamp": time.time()
    }

if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def index() -> HTMLResponse:
    idx_path = frontend_dir / "index.html"
    if idx_path.exists():
        return HTMLResponse(content=idx_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>KashMakr gig_78e0e79b - T1271 Service Live</h1>")
