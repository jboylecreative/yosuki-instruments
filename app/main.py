import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data"
UPLOADS_PATH = ROOT / "uploads"
UPLOADS_PATH.mkdir(exist_ok=True)

(ROOT / "generated").mkdir(exist_ok=True)

import time as _time
_STATIC_VERSION = str(int(_time.time()))  # changes on every server restart → busts browser cache

app = FastAPI(title="Motion Graphics Pipeline")
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
templates.env.filters["tojson"] = lambda obj: __import__("json").dumps(obj)
templates.env.globals["static_version"] = _STATIC_VERSION


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


_DEFAULT_SIZES = [
    {
        "id": "1920x1080", "label": "YouTube / 16:9", "comp_name": "YouTube_1920x1080",
        "width": 1920, "height": 1080, "gen_width": 3840, "gen_height": 2160,
        "billboard": False, "enabled": True, "composition_hint": "",
    },
    {
        "id": "1080x1080", "label": "Instagram / 1:1", "comp_name": "Instagram_1080x1080",
        "width": 1080, "height": 1080, "gen_width": 2160, "gen_height": 2160,
        "billboard": False, "enabled": True, "composition_hint": "",
    },
    {
        "id": "970x250", "label": "Billboard", "comp_name": "Billboard_970x250",
        "width": 970, "height": 250, "gen_width": 1940, "gen_height": 500,
        "billboard": True, "enabled": True, "composition_hint": "",
    },
]

_CONFIG_DEFAULTS = {
    "project_name": "",
    "output_destination": {"type": "local", "local_path": ""},
    "sizes": _DEFAULT_SIZES,
    "preview_asset_id": "",
}


@app.post("/reset")
async def reset_project():
    """Clear uploads, parsed data, and reset all project-specific config fields."""
    print("── RESET: clearing project state ──")

    # Reset project-specific config fields
    cfg = load_config()
    cfg.update(_CONFIG_DEFAULTS)
    save_config(cfg)
    print("  config.json reset")

    # Clear uploads folder
    if UPLOADS_PATH.exists():
        for item in UPLOADS_PATH.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    print("  uploads cleared")

    # Clear parsed data files
    for name in ("campaign_brief.json", "copy_manifest.json", "asset_manifest.json",
                 "aep_build_config.json", "render_jobs.json"):
        p = DATA_PATH / name
        if p.exists():
            p.unlink()
    print("  data files cleared")

    return JSONResponse({"status": "ok"})


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

@app.get("/pick-folder")
async def pick_folder():
    """Open a native OS folder picker and return the selected path."""
    script = (
        "import tkinter as tk; from tkinter import filedialog; "
        "root = tk.Tk(); root.withdraw(); root.wm_attributes('-topmost', True); "
        "path = filedialog.askdirectory(title='Select output folder'); "
        "root.destroy(); print(path, end='')"
    )
    import subprocess
    result = await asyncio.to_thread(
        lambda: subprocess.run([sys.executable, "-c", script],
                               capture_output=True, text=True, timeout=60)
    )
    return JSONResponse({"path": result.stdout.strip()})


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    cfg = load_config()

    brief_pdf_ready = (UPLOADS_PATH / "brief.pdf").exists()
    brief_parsed = (DATA_PATH / "campaign_brief.json").exists()

    assets_dir = UPLOADS_PATH / "assets"
    assets_ready = assets_dir.exists() and any(assets_dir.iterdir())

    asset_matches = []
    manifest_path = DATA_PATH / "asset_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        asset_matches = manifest.get("matches", [])

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "config": cfg,
        "brief_pdf_ready": brief_pdf_ready,
        "brief_parsed": brief_parsed,
        "assets_ready": assets_ready,
        "asset_matches": asset_matches,
        "run_ready": brief_pdf_ready and assets_ready,
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
        # file.filename may include a relative path from webkitdirectory or our
        # recursive drop handler, e.g. "myfolder/subfolder/image.png".
        # Strip the first path component (the root folder the user selected) so
        # we preserve subfolder structure without the top-level folder name.
        parts = Path(file.filename).parts
        sub_path = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
        dest = asset_dir / sub_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        saved.append(str(sub_path))
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
        }
    save_config(cfg)
    return JSONResponse({"status": "ok"})


@app.post("/config/destination")
async def update_destination(request: Request):
    body = await request.json()
    cfg = load_config()
    # Merge into existing dest so drive_folder_id/url are preserved when toggling
    dest = cfg.get("output_destination", {})
    dest["type"] = body.get("type", "local")
    if "local_path" in body:
        dest["local_path"] = body["local_path"]
    cfg["output_destination"] = dest
    save_config(cfg)
    return JSONResponse({"status": "ok"})


@app.post("/run/parse")
async def run_parse():
    run_id = str(uuid.uuid4())[:8]
    asyncio.create_task(_run_step(run_id, "parse"))
    return JSONResponse({"run_id": run_id})


@app.post("/run/preview")
async def run_preview(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if body.get("asset_id"):
        cfg = load_config()
        cfg["preview_asset_id"] = body["asset_id"]
        save_config(cfg)
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


# ── Google Drive OAuth routes ────────────────────────────────────────────────

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_DRIVE_REDIRECT_URI = "http://localhost:8000/drive/callback"
_drive_flow = None  # preserved between /connect and /callback so the PKCE code_verifier survives


def _drive_get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Find or create a Drive folder. Returns folder ID."""
    safe = name.replace("'", "\\'")
    q = (f"name='{safe}' and '{parent_id}' in parents and "
         "mimeType='application/vnd.google-apps.folder' and trashed=false")
    result = service.files().list(q=q, fields="files(id)", spaces="drive").execute()
    items = result.get("files", [])
    if items:
        return items[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _drive_client_config() -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env. "
            "Create an OAuth 2.0 Client ID (Desktop app) in Google Cloud Console, "
            "then paste the values into your .env file."
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [_DRIVE_REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


@app.get("/drive/connect")
async def drive_connect():
    """Build the Google OAuth consent URL and redirect the browser there."""
    global _drive_flow
    from google_auth_oauthlib.flow import Flow

    try:
        client_config = _drive_client_config()
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    _drive_flow = Flow.from_client_config(
        client_config,
        scopes=_DRIVE_SCOPES,
        redirect_uri=_DRIVE_REDIRECT_URI,
    )
    auth_url, _ = _drive_flow.authorization_url(
        access_type="offline",
        prompt="consent",  # always issue refresh token, even on re-auth
        include_granted_scopes="true",
    )
    return RedirectResponse(auth_url)


@app.get("/drive/callback")
async def drive_callback(code: str | None = None, error: str | None = None,
                         state: str | None = None):
    """Exchange OAuth code for tokens, auto-create project folder, store in config."""
    if error:
        return RedirectResponse(f"/?drive_error={error}")
    if not code:
        return RedirectResponse("/?drive_error=no_code")

    try:
        global _drive_flow
        from googleapiclient.discovery import build

        if _drive_flow is None:
            return RedirectResponse("/?drive_error=session_expired_restart_and_try_again")
        _drive_flow.fetch_token(code=code)
        flow = _drive_flow
        _drive_flow = None
        creds = flow.credentials

        # Persist token
        (DATA_PATH / "drive_token.json").write_text(creds.to_json())

        # Auto-create project folder in Drive root
        service = build("drive", "v3", credentials=creds)
        cfg = load_config()
        project_name = cfg.get("project_name") or "Motion Graphics Pipeline"
        folder_id = _drive_get_or_create_folder(service, project_name, "root")
        folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

        cfg["output_destination"]["drive_folder_id"] = folder_id
        cfg["output_destination"]["drive_folder_url"] = folder_url
        save_config(cfg)

        return HTMLResponse("""<!DOCTYPE html><html><body>
<p style="font-family:sans-serif;padding:2rem;">Google Drive connected ✓ — closing…</p>
<script>
  if (window.opener) { window.opener.postMessage('drive_connected', '*'); window.close(); }
  else { window.location.href = '/?drive_connected=1'; }
</script></body></html>""")
    except Exception as exc:
        safe_msg = str(exc)[:200].replace("'", "").replace('"', "")
        return HTMLResponse(f"""<!DOCTYPE html><html><body>
<p style="font-family:sans-serif;padding:2rem;color:#e05252;">Drive error: {safe_msg}</p>
<script>
  if (window.opener) {{ window.opener.postMessage({{'drive_error': '{safe_msg}'}}, '*'); window.close(); }}
  else {{ window.location.href = '/?drive_error={safe_msg}'; }}
</script></body></html>""")


@app.get("/drive/status")
async def drive_status():
    """Return whether Drive credentials are valid and the folder URL if set."""
    token_path = DATA_PATH / "drive_token.json"
    if not token_path.exists():
        return JSONResponse({"connected": False, "folder_url": None})
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(str(token_path), _DRIVE_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        cfg = load_config()
        folder_url = cfg.get("output_destination", {}).get("drive_folder_url") or None
        return JSONResponse({"connected": creds.valid, "folder_url": folder_url})
    except Exception:
        return JSONResponse({"connected": False, "folder_url": None})


@app.delete("/drive/token")
async def drive_disconnect():
    """Remove stored Drive credentials."""
    token_path = DATA_PATH / "drive_token.json"
    if token_path.exists():
        token_path.unlink()
    return JSONResponse({"status": "ok"})


# ── Background task runners ───────────────────────────────────────────────────

def _stream_subprocess(cmd: list, q: asyncio.Queue, loop: asyncio.AbstractEventLoop,
                       label: str | None = None) -> int:
    """Run cmd in a thread, push each stdout line into q via the event loop. Returns exit code."""
    import subprocess
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"       # force UTF-8 for all file I/O in pipeline subprocesses on Windows
    env["PYTHONUNBUFFERED"] = "1"  # flush print() immediately so the browser log updates in real time
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", bufsize=1, env=env,
    )
    for line in proc.stdout:
        stripped = line.rstrip()
        # Drop aerender's verbose per-frame timecodes and comp-header fields — the pipeline
        # steps emit their own start/finish messages around aerender.
        if stripped.startswith("PROGRESS:"):
            continue
        text = f"[{label}] {stripped}" if label else stripped
        loop.call_soon_threadsafe(q.put_nowait, text)
    proc.wait()
    return proc.returncode


async def _run_step(run_id: str, mode: str):
    import threading
    q = get_queue(run_id)
    loop = asyncio.get_running_loop()
    _cfg = load_config()
    dest_type = _cfg.get("output_destination", {}).get("type", "local")
    batch_steps   = "1,2,3,4,5,7" if dest_type == "drive" else "1,2,3,4,5"
    preview_steps = "1,2,3,4,5,7" if dest_type == "drive" else "1,2,3,4,5"
    steps = {
        "parse":   [sys.executable, str(ROOT / "run_pipeline.py"), "--steps", "1,2"],
        "preview": [sys.executable, str(ROOT / "run_pipeline.py"), "--steps", preview_steps,
                    "--preview", "--preview-locale", "en"],
        "batch":   [sys.executable, str(ROOT / "run_pipeline.py"), "--steps", batch_steps],
        "rerender":[sys.executable, str(ROOT / "run_pipeline.py"), "--steps", "4,5"],
    }
    cmd = steps.get(mode, steps["batch"])
    finish = asyncio.Event()

    def _run():
        _stream_subprocess(cmd, q, loop)
        loop.call_soon_threadsafe(q.put_nowait, "__done__")
        loop.call_soon_threadsafe(finish.set)

    threading.Thread(target=_run, daemon=True).start()
    await finish.wait()


async def _run_regenerate(run_id: str, params: dict):
    import threading
    q = get_queue(run_id)
    loop = asyncio.get_running_loop()
    cmd = [
        sys.executable, str(ROOT / "run_pipeline.py"),
        "--steps", "3,4,5",
        "--asset", params.get("asset", ""),
        "--locale", params.get("locale", ""),
        "--aspect", params.get("aspect", ""),
        "--model", params.get("model", ""),
    ]
    finish = asyncio.Event()

    def _run():
        _stream_subprocess(cmd, q, loop)
        loop.call_soon_threadsafe(q.put_nowait, "__done__")
        loop.call_soon_threadsafe(finish.set)

    threading.Thread(target=_run, daemon=True).start()
    await finish.wait()


