"""
Step 6: Write a local CSV delivery tracking matrix.

Scans the current run's renders directory and writes one row per rendered file:
  Locale | Asset | Aspect Ratio | Gen# | Output Filename | File Path | Status | Timestamp

Saves to data/delivery_matrix.csv.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

HEADERS = [
    "Locale", "Asset", "Aspect Ratio", "Gen #",
    "Output Filename", "File Path", "Status", "Timestamp",
]


def collect_rows(cfg: dict) -> list[list]:
    run_id_file = DATA / "current_run_id.txt"
    if not run_id_file.exists():
        return []
    run_id = run_id_file.read_text().strip()

    dest = cfg.get("output_destination", {})
    local_path = dest.get("local_path", "./output")
    p = Path(local_path)
    output_base = p if p.is_absolute() else (ROOT / p).resolve()
    project_name = cfg.get("project_name", "output")
    renders_dir = output_base / project_name / run_id / "renders"

    if not renders_dir.exists():
        return []

    rows = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for mp4 in sorted(renders_dir.rglob("*.mp4")):
        parts = mp4.stem.split("_")
        locale = parts[0] if len(parts) > 0 else ""
        asset = parts[1] if len(parts) > 1 else ""
        aspect = parts[2] if len(parts) > 2 else ""
        gen_num = parts[3] if len(parts) > 3 else ""
        rows.append([locale, asset, aspect, gen_num, mp4.name, str(mp4), "Rendered", timestamp])

    return rows


def run(cfg: dict, dry_run: bool = False):
    rows = collect_rows(cfg)
    if not rows:
        print("  No rendered files found — skipping delivery matrix")
        return

    if dry_run:
        print(f"  [DRY RUN] Would write {len(rows)} rows to delivery_matrix.csv")
        return

    csv_path = DATA / "delivery_matrix.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(HEADERS)
        writer.writerows(rows)

    print(f"  Saved delivery_matrix.csv — {len(rows)} rendered files")
