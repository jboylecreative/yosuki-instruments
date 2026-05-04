"""
Step 6: Generate the Google Sheets delivery tracking matrix.

Creates (or updates) a spreadsheet with one row per rendered file:
  Locale | Asset | Aspect Ratio | Stage1 Model | Stage2 Model | Gen# |
  Output Filename | File Path | Drive Link | Status | Timestamp
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADERS = [
    "Locale", "Asset", "Variant", "Aspect Ratio",
    "Stage1 Model", "Stage2 Model", "Gen #",
    "Output Filename", "File Path", "Drive Link",
    "Status", "Timestamp",
]


def _sheets_service():
    creds_path = ROOT / "google_service_account.json"
    if not creds_path.exists():
        raise FileNotFoundError(
            "google_service_account.json not found. "
            "Download your service account key from Google Cloud Console and place it at the project root."
        )
    creds = service_account.Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def collect_rows(cfg: dict) -> list[list]:
    run_id_file = DATA / "current_run_id.txt"
    if not run_id_file.exists():
        return []
    run_id = run_id_file.read_text().strip()
    renders_dir = ROOT / "output" / run_id / "renders"

    rows = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for mp4 in sorted(renders_dir.rglob("*.mp4")):
        parts = mp4.stem.split("_")
        locale = parts[0] if len(parts) > 0 else ""
        asset = parts[1] if len(parts) > 1 else ""
        aspect = parts[2] if len(parts) > 2 else ""
        gen_num = parts[3] if len(parts) > 3 else ""

        rows.append([
            locale, asset, "", aspect,
            "", "", gen_num,
            mp4.name, str(mp4), "",  # Drive link filled by step 7
            "Rendered", timestamp,
        ])

    return rows


def run(cfg: dict, dry_run: bool = False):
    rows = collect_rows(cfg)
    if not rows:
        print("  No rendered files found — skipping sheet update")
        return

    sheets_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not sheets_id:
        print("  GOOGLE_SHEETS_ID not set — writing local CSV instead")
        csv_path = DATA / "delivery_matrix.csv"
        with csv_path.open("w", encoding="utf-8") as f:
            f.write(",".join(HEADERS) + "\n")
            for row in rows:
                f.write(",".join(f'"{v}"' for v in row) + "\n")
        print(f"  Saved delivery_matrix.csv ({len(rows)} rows)")
        return

    if dry_run:
        print(f"  [DRY RUN] Would write {len(rows)} rows to Google Sheet {sheets_id}")
        return

    service = _sheets_service()
    sheet = service.spreadsheets()

    # Clear and rewrite the sheet
    sheet.values().clear(spreadsheetId=sheets_id, range="Sheet1").execute()
    sheet.values().update(
        spreadsheetId=sheets_id,
        range="Sheet1!A1",
        valueInputOption="RAW",
        body={"values": [HEADERS] + rows},
    ).execute()

    print(f"  Updated Google Sheet ({len(rows)} rows) — "
          f"https://docs.google.com/spreadsheets/d/{sheets_id}")
