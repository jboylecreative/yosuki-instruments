"""
Step 7: Deliver final renders.

Dispatches based on output_destination.type in config:
  "local"  — files are already in place, nothing to move
  "gcs"    — upload renders dir to Google Cloud Storage
  "drive"  — upload to Google Drive folder

GCS path structure: {gcs_prefix}/{project_name}/{YYYY-MM-DD}/{HH-MM-SS}/{filename}
Auth: GCS_KEY_FILE env var (service account JSON) or Application Default Credentials
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"


def _resolve_output_base(cfg: dict) -> Path:
    dest = cfg.get("output_destination", {})
    local_path = dest.get("local_path", "./output")
    p = Path(local_path)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _get_run_dir(cfg: dict) -> Path | None:
    run_id_file = DATA / "current_run_id.txt"
    if not run_id_file.exists():
        return None
    run_timestamp = run_id_file.read_text().strip()
    project_name = cfg.get("project_name", "output")
    return _resolve_output_base(cfg) / project_name / run_timestamp


def _deliver_gcs(cfg: dict, run_dir: Path, files: list[Path], dry_run: bool):
    dest = cfg.get("output_destination", {})
    bucket_name = dest.get("gcs_bucket", "") or os.environ.get("GCS_BUCKET", "")
    if not bucket_name:
        print("  ERROR: gcs_bucket not set in config or GCS_BUCKET env var")
        return

    gcs_prefix = dest.get("gcs_prefix", "renders").rstrip("/")
    project_name = cfg.get("project_name", "output")
    run_timestamp = (DATA / "current_run_id.txt").read_text().strip()
    gcs_base = f"{gcs_prefix}/{project_name}/{run_timestamp}"

    if dry_run:
        print(f"  [DRY RUN] Would upload {len(files)} files to gs://{bucket_name}/{gcs_base}/")
        return

    try:
        from google.cloud import storage as gcs
    except ImportError:
        print("  google-cloud-storage not installed — pip install google-cloud-storage")
        return

    key_file = os.environ.get("GCS_KEY_FILE", "").strip()
    if key_file and Path(key_file).exists():
        client = gcs.Client.from_service_account_json(key_file)
    else:
        client = gcs.Client()

    bucket = client.bucket(bucket_name)
    links = {}

    for i, file_path in enumerate(files, 1):
        blob_name = f"{gcs_base}/{file_path.name}"
        print(f"  [{i}/{len(files)}] → gs://{bucket_name}/{blob_name}")
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(file_path))
        blob.make_public()
        links[file_path.name] = blob.public_url

    links_path = DATA / "gcs_links.json"
    links_path.write_text(json.dumps(links, indent=2))
    print(f"  Uploaded {len(links)} files to GCS — links saved to data/gcs_links.json")


def _deliver_drive(run_dir: Path, files: list[Path], dry_run: bool):
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    if not folder_id:
        print("  GOOGLE_DRIVE_FOLDER_ID not set — skipping Drive delivery")
        return

    if dry_run:
        print(f"  [DRY RUN] Would upload {len(files)} files to Drive folder {folder_id}")
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
    for i, file_path in enumerate(files, 1):
        print(f"  [{i}/{len(files)}] Uploading: {file_path.name}")
        mime = "video/mp4" if file_path.suffix == ".mp4" else "application/octet-stream"
        metadata = {"name": file_path.name, "parents": [folder_id]}
        media = MediaFileUpload(str(file_path), mimetype=mime, resumable=True)
        uploaded = service.files().create(
            body=metadata, media_body=media, fields="id,webViewLink"
        ).execute()
        drive_links[file_path.name] = uploaded.get("webViewLink", "")
        print(f"    → {uploaded.get('webViewLink', 'no link')}")

    links_path = DATA / "drive_links.json"
    links_path.write_text(json.dumps(drive_links, indent=2))
    print(f"  Delivered {len(drive_links)} files to Google Drive")


def run(cfg: dict, dry_run: bool = False):
    run_dir = _get_run_dir(cfg)
    if not run_dir:
        print("  No current run found — run Step 4 first")
        return

    renders_dir = run_dir / "renders"
    output_aep = run_dir / "output.aep"
    mp4s = list(renders_dir.rglob("*.mp4")) if renders_dir.exists() else []
    files_to_upload = mp4s + ([output_aep] if output_aep.exists() else [])

    if not files_to_upload:
        print("  No files to deliver — run Steps 4+5 first")
        return

    print(f"  {len(mp4s)} MP4s + {'1 AEP' if output_aep.exists() else '0 AEP'} ready for delivery")

    dest_type = cfg.get("output_destination", {}).get("type", "local")

    if dest_type == "local":
        print(f"  Output destination: local — files already at {run_dir}")

    elif dest_type == "gcs":
        print(f"  Output destination: Google Cloud Storage")
        _deliver_gcs(cfg, run_dir, files_to_upload, dry_run)

    elif dest_type == "drive":
        print(f"  Output destination: Google Drive")
        _deliver_drive(run_dir, files_to_upload, dry_run)

    else:
        print(f"  Unknown output destination type: {dest_type}")
