"""
Step 7: Deliver outputs to Google Drive.

Uploads all render artifacts from the current run to Google Drive:
  - renders/ subtree (all MP4 files, organised by locale)
  - output.aep + (Footage)/ folder (under an "AE Project" subfolder)

Folder hierarchy in Drive:
  <project folder>  ← auto-created at connect time, stored in config.json
    └── YYYY-MM-DD/
        └── HH-MM-SS/
            ├── renders/
            │   └── ...locale subdirs...
            └── AE Project/
                ├── output.aep
                └── (Footage)/

Skips silently if output_destination.type is not "drive".
"""
import mimetypes
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_run_dir(cfg: dict) -> Path | None:
    run_id_file = DATA / "current_run_id.txt"
    if not run_id_file.exists():
        return None
    run_id = run_id_file.read_text().strip()
    dest = cfg.get("output_destination", {})
    local_path = dest.get("local_path", "./output")
    p = Path(local_path)
    output_base = p if p.is_absolute() else (ROOT / p).resolve()
    project_name = cfg.get("project_name", "output")
    return output_base / project_name / run_id


def _load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = DATA / "drive_token.json"
    if not token_path.exists():
        raise FileNotFoundError(
            "data/drive_token.json not found — "
            "click 'Connect Google Drive' in the dashboard first."
        )
    creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Find or create a Drive folder under parent_id. Returns folder ID."""
    safe = name.replace("'", "\\'")
    query = (
        f"name='{safe}' and '{parent_id}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    result = service.files().list(q=query, fields="files(id)", spaces="drive").execute()
    items = result.get("files", [])
    if items:
        return items[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _upload_file(service, local_path: Path, parent_folder_id: str) -> str:
    """Upload a single file using resumable upload. Returns Drive file ID."""
    from googleapiclient.http import MediaFileUpload

    mime_type, _ = mimetypes.guess_type(str(local_path))
    if mime_type is None:
        mime_type = "application/octet-stream"
    metadata = {"name": local_path.name, "parents": [parent_folder_id]}
    media = MediaFileUpload(
        str(local_path),
        mimetype=mime_type,
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks — safe for 1+ GB AEP files
    )
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return file["id"]


def _mirror_directory(service, local_dir: Path, drive_parent_id: str):
    """Recursively mirror a local directory tree into Drive."""
    folder_id = _get_or_create_folder(service, local_dir.name, drive_parent_id)
    for item in sorted(local_dir.iterdir()):
        if item.is_dir():
            _mirror_directory(service, item, folder_id)
        elif item.is_file():
            size_kb = item.stat().st_size // 1024
            print(f"    Uploading {item.name} ({size_kb} KB)…")
            _upload_file(service, item, folder_id)


def run(cfg: dict, dry_run: bool = False):
    load_dotenv(ROOT / ".env")

    dest = cfg.get("output_destination", {})
    if dest.get("type") != "drive":
        print("  Output destination is not Google Drive — skipping upload")
        return

    run_dir = _get_run_dir(cfg)
    if not run_dir or not run_dir.exists():
        print("  No current run directory found — run Steps 4+5 first")
        return

    drive_folder_id = dest.get("drive_folder_id", "").strip()
    if not drive_folder_id:
        print("  ERROR: No Drive folder configured — click 'Connect Google Drive' in the dashboard.")
        return

    renders_dir = run_dir / "renders"
    aep_candidates = list(run_dir.glob("*.aep"))
    aep = aep_candidates[0] if aep_candidates else None
    footage_dir = run_dir / "(Footage)"
    mp4s = list(renders_dir.rglob("*.mp4")) if renders_dir.exists() else []

    if dry_run:
        print(f"  [DRY RUN] Would upload to Google Drive from {run_dir}")
        print(f"    {len(mp4s)} MP4(s), AEP: {aep is not None}, Footage: {footage_dir.exists()}")
        return

    try:
        creds = _load_credentials()
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}")
        return
    except Exception as exc:
        print(f"  ERROR refreshing Google Drive credentials: {exc}")
        return

    from googleapiclient.discovery import build
    service = build("drive", "v3", credentials=creds)

    # Build run folder hierarchy: project_root → date → time
    run_id = run_dir.name  # format: YYYY-MM-DD_HH-MM-SS
    parts = run_id.split("_", 1)
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else run_id

    print("  Building Drive folder hierarchy…")
    date_folder_id = _get_or_create_folder(service, date_part, drive_folder_id)
    run_folder_id  = _get_or_create_folder(service, time_part, date_folder_id)

    if renders_dir.exists():
        print(f"  Uploading renders/ ({len(mp4s)} MP4s)…")
        try:
            _mirror_directory(service, renders_dir, run_folder_id)
        except Exception as exc:
            print(f"  ERROR uploading renders: {exc}")

    ae_folder_id = _get_or_create_folder(service, "AE Project", run_folder_id)

    if aep:
        size_mb = aep.stat().st_size // (1024 * 1024)
        print(f"  Uploading {aep.name} ({size_mb} MB)…")
        try:
            _upload_file(service, aep, ae_folder_id)
        except Exception as exc:
            print(f"  ERROR uploading {aep.name}: {exc}")

    if footage_dir.exists():
        print("  Uploading (Footage)/…")
        try:
            _mirror_directory(service, footage_dir, ae_folder_id)
        except Exception as exc:
            print(f"  ERROR uploading (Footage)/: {exc}")

    drive_url = dest.get("drive_folder_url", "")
    print(f"  Drive upload complete.{('  View: ' + drive_url) if drive_url else ''}")
