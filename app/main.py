import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

app = FastAPI(title="Yosuki Motion Graphics Pipeline")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
app.mount("/generated", StaticFiles(directory=ROOT / "generated"), name="generated")


def _mount_output_dir():
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    dest = cfg.get("output_destination", {})
    local_path = dest.get("local_path", "./output")
    p = Path(local_path) if Path(local_path).is_absolute() else (ROOT / local_path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


_output_dir = _mount_output_dir()
app.mount("/output", StaticFiles(directory=_output_dir), name="output")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")

CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data"
UPLOADS_PATH = ROOT / "uploads"
UPLOADS_PATH.mkdir(exist_ok=True)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# ── Progress event bus (simple in-memory queue per run) ──────────────────────
_progress_queues: dict[str, asyncio.Queue] = {}


def get_queue(run_id: str) -> asyncio.Queue:
    if run_id not in _progress_queues:
        _progress_queues[run_id] = asyncio.Queue()
    return _progress_queues[run_id]


async def push_event(run_id: str, msg: str):
    q = get_queue(run_id)
    await q.put(msg)


async def sse_generator(run_id: str) -> AsyncGenerator[str, None]:
    q = get_queue(run_id)
    while True:
        try:
            msg = await asyncio.wait_for(q.get(), timeout=30)
            if msg == "__done__":
                yield "data: __done__\n\n"
                break
            yield f"data: {msg}\n\n"
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    cfg = load_config()
    brief_uploaded = (DATA_PATH / "campaign_brief.json").exists()
    asset_manifest = (DATA_PATH / "asset_manifest.json").exists()
    copy_ready = (DATA_PATH / "copy_manifest.json").exists()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "config": cfg,
        "brief_uploaded": brief_uploaded,
        "asset_manifest": asset_manifest,
        "copy_ready": copy_ready,
    })


@app.post("/upload/brief")
async def upload_brief(brief: UploadFile = File(...)):
    dest = UPLOADS_PATH / "brief.pdf"
    with dest.open("wb") as f:
        shutil.copyfileobj(brief.file, f)
    return JSONResponse({"status": "ok", "filename": brief.filename})


@app.post("/upload/assets")
async def upload_assets(files: list[UploadFile] = File(...)):
    asset_dir = UPLOADS_PATH / "assets"
    asset_dir.mkdir(exist_ok=True)
    saved = []
    for file in files:
        dest = asset_dir / Path(file.filename).name
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        saved.append(dest.name)
    return JSONResponse({"status": "ok", "saved": saved, "count": len(saved)})


@app.post("/config/models")
async def update_model_config(request: Request):
    body = await request.json()
    cfg = load_config()
    for model in cfg["stage1_image_models"]:
        model["enabled"] = model["id"] in body.get("stage1_enabled", [])
    for model in cfg["stage2_video_models"]:
        model["enabled"] = model["id"] in body.get("stage2_enabled", [])
    save_config(cfg)
    return JSONResponse({"status": "ok"})


@app.get("/config/sizes")
async def get_sizes():
    cfg = load_config()
    return JSONResponse({"sizes": cfg.get("sizes", [])})


@app.post("/config/sizes")
async def update_sizes(request: Request):
    body = await request.json()
    cfg = load_config()
    action = body.get("action")

    if action == "toggle":
        size_id = body["id"]
        for s in cfg["sizes"]:
            if s["id"] == size_id:
                s["enabled"] = body["enabled"]
                break

    elif action == "add":
        w = int(body["width"])
        h = int(body["height"])
        label = body.get("label", f"{w}×{h}")
        new_size = {
            "id": f"{w}x{h}",
            "label": label,
            "comp_name": f"Comp_{w}x{h}",
            "width": w,
            "height": h,
            "gen_width": w * 2,
            "gen_height": h * 2,
            "billboard": False,
            "enabled": True,
        }
        existing_ids = {s["id"] for s in cfg["sizes"]}
        if new_size["id"] not in existing_ids:
            cfg["sizes"].append(new_size)

    elif action == "remove":
        size_id = body["id"]
        cfg["sizes"] = [s for s in cfg["sizes"] if s["id"] != size_id]

    save_config(cfg)
    return JSONResponse({"status": "ok", "sizes": cfg["sizes"]})


@app.post("/config/project")
async def update_project_config(request: Request):
    body = await request.json()
    cfg = load_config()
    if "project_name" in body:
        cfg["project_name"] = body["project_name"]
    if "output_destination" in body:
        dest = body["output_destination"]
        cfg["output_destination"] = {
            "type": dest.get("type", "local"),
            "local_path": dest.get("local_path", "./output"),
            "gcs_bucket": dest.get("gcs_bucket", ""),
            "gcs_prefix": dest.get("gcs_prefix", "renders"),
        }
    save_config(cfg)
    return JSONResponse({"status": "ok"})


@app.post("/run/parse")
async def run_parse():
    run_id = str(uuid.uuid4())[:8]
    asyncio.create_task(_run_step(run_id, "parse"))
    return JSONResponse({"run_id": run_id})


@app.post("/run/preview")
async def run_preview():
    run_id = str(uuid.uuid4())[:8]
    asyncio.create_task(_run_step(run_id, "preview"))
    return JSONResponse({"run_id": run_id})


@app.post("/run/batch")
async def run_batch():
    run_id = str(uuid.uuid4())[:8]
    asyncio.create_task(_run_step(run_id, "batch"))
    return JSONResponse({"run_id": run_id})


@app.post("/run/rerender")
async def run_rerender():
    run_id = str(uuid.uuid4())[:8]
    asyncio.create_task(_run_step(run_id, "rerender"))
    return JSONResponse({"run_id": run_id})


@app.get("/run/{run_id}/stream")
async def stream_progress(run_id: str):
    return StreamingResponse(
        sse_generator(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/run/{run_id}/regenerate")
async def regenerate_variant(run_id: str, request: Request):
    body = await request.json()
    new_run = str(uuid.uuid4())[:8]
    asyncio.create_task(_run_regenerate(new_run, body))
    return JSONResponse({"run_id": new_run})


@app.get("/results", response_class=HTMLResponse)
async def results(request: Request):
    cfg = load_config()
    dest = cfg.get("output_destination", {})
    local_path = dest.get("local_path", "./output")
    output_base = Path(local_path) if Path(local_path).is_absolute() else (ROOT / local_path).resolve()

    renders = []
    if output_base.exists():
        for mp4 in output_base.rglob("*.mp4"):
            # Only include files from renders/ subdirectories
            if "renders" not in mp4.parts:
                continue
            try:
                rel = mp4.relative_to(output_base)
            except ValueError:
                continue
            parts = mp4.stem.split("_")
            # filename format: {LOCALE}_{asset}_{WxH}_{NNN}
            # size_id contains 'x' so split carefully from the right
            renders.append({
                "filename": mp4.name,
                "path": f"/output/{rel.as_posix()}",
                "locale": parts[0] if len(parts) > 0 else "",
                "asset": parts[1] if len(parts) > 1 else "",
                "size": parts[2] if len(parts) > 2 else "",
                "number": parts[3] if len(parts) > 3 else "",
            })
    return templates.TemplateResponse("results.html", {
        "request": request,
        "renders": renders,
        "config": cfg,
    })


# ── Background task runners ───────────────────────────────────────────────────

async def _run_step(run_id: str, mode: str):
    import subprocess
    q = get_queue(run_id)
    steps = {
        "parse":   ["python", str(ROOT / "run_pipeline.py"), "--steps", "1,2"],
        "preview": ["python", str(ROOT / "run_pipeline.py"), "--steps", "3", "--preview"],
        "batch":   ["python", str(ROOT / "run_pipeline.py"), "--steps", "3,4,5"],
        "rerender":["python", str(ROOT / "run_pipeline.py"), "--steps", "4,5"],
    }
    cmd = steps.get(mode, steps["batch"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for line in proc.stdout:
        await q.put(line.decode().rstrip())
    await proc.wait()
    await q.put("__done__")


async def _run_regenerate(run_id: str, params: dict):
    import subprocess
    q = get_queue(run_id)
    cmd = [
        "python", str(ROOT / "run_pipeline.py"),
        "--steps", "3,4,5",
        "--asset", params.get("asset", ""),
        "--locale", params.get("locale", ""),
        "--aspect", params.get("aspect", ""),
        "--model", params.get("model", ""),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for line in proc.stdout:
        await q.put(line.decode().rstrip())
    await proc.wait()
    await q.put("__done__")
