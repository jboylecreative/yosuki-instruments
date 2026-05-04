"""
Step 7: Deliver final renders to Google Drive. (DEFERRED — tested last)

Mirrors output/{run_id}/ to the configured Google Drive folder.
Updates the tracking sheet with shareable Drive links.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"


def run(cfg: dict, dry_run: bool = False):
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        print("  GOOGLE_DRIVE_FOLDER_ID not set — skipping Drive delivery")
        return

    run_id_file = DATA / "current_run_id.txt"
    if not run_id_file.exists():
        print("  No current run ID — nothing to deliver")
        return
    run_id = run_id_file.read_text().strip()

    renders_dir = ROOT / "output" / run_id / "renders"
    output_aep = ROOT / "output" / run_id / f"yosuki_output_{run_id}.aep"

    mp4s = list(renders_dir.rglob("*.mp4"))
    files_to_upload = mp4s + ([output_aep] if output_aep.exists() else [])

    if dry_run:
        print(f"  [DRY RUN] Would upload {len(files_to_upload)} files to Drive folder {folder_id}")
        return

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("  google-api-python-client not installed — skipping Drive delivery")
        return

    creds_path = ROOT / "google_service_account.json"
    if not creds_path.exists():
        print("  google_service_account.json not found — skipping Drive delivery")
        return

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]
    creds = service_account.Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    service = build("drive", "v3", credentials=creds)

    drive_links = {}
    for i, file_path in enumerate(files_to_upload, 1):
        print(f"  [{i}/{len(files_to_upload)}] Uploading: {file_path.name}")
        mime = "video/mp4" if file_path.suffix == ".mp4" else "application/octet-stream"
        metadata = {"name": file_path.name, "parents": [folder_id]}
        media = MediaFileUpload(str(file_path), mimetype=mime, resumable=True)
        uploaded = service.files().create(
            body=metadata, media_body=media, fields="id,webViewLink"
        ).execute()
        drive_links[file_path.name] = uploaded.get("webViewLink", "")
        print(f"    → {uploaded.get('webViewLink', 'no link')}")

    # Persist links for the tracking sheet
    links_path = DATA / "drive_links.json"
    links_path.write_text(json.dumps(drive_links, indent=2))
    print(f"  Delivered {len(drive_links)} files to Google Drive")
