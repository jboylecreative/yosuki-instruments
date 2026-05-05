"""
Step 5: Batch render all variant comps from the output AEP via nexrender + aerender.

Reads data/render_jobs/*.json (one per variant comp).
Runs nexrender-cli for each job sequentially.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"


def build_nexrender_job(job: dict, output_aep: str) -> dict:
    return {
        "template": {
            "src": f"file://{output_aep.replace(chr(92), '/')}",
            "composition": job["comp_name"],
            "outputModule": "H.264 - Match Render Settings - 15 Mb/s",
            "outputExt": "mp4",
            "settingsTemplate": "Best Settings",
        },
        "assets": [],  # Content is already baked into the output AEP comps
        "actions": {
            "postrender": [
                {
                    "module": "@nexrender/action-copy",
                    "input": "result.mp4",
                    "output": job["output_path"],
                }
            ]
        },
    }


def _resolve_output_base(cfg: dict) -> Path:
    dest = cfg.get("output_destination", {})
    local_path = dest.get("local_path", "./output")
    p = Path(local_path)
    return p if p.is_absolute() else (ROOT / p).resolve()


def run(cfg: dict, dry_run: bool = False):
    jobs_dir = DATA / "render_jobs"
    if not jobs_dir.exists() or not list(jobs_dir.glob("*.json")):
        raise FileNotFoundError("No render jobs found — run Step 4 first")

    run_id_file = DATA / "current_run_id.txt"
    if not run_id_file.exists():
        raise FileNotFoundError("current_run_id.txt not found — run Step 4 first")
    run_timestamp = run_id_file.read_text().strip()

    project_name = cfg.get("project_name", "output")
    run_dir = _resolve_output_base(cfg) / project_name / run_timestamp
    output_aep = run_dir / "output.aep"
    if not output_aep.exists():
        raise FileNotFoundError(f"Output AEP not found: {output_aep} — run Step 4 first")

    job_files = sorted(jobs_dir.glob("*.json"))
    total = len(job_files)
    aerender_path = cfg.get("aerender_path") or os.environ.get("AERENDER_PATH", "aerender")

    print(f"  {total} render jobs queued")

    for i, job_file in enumerate(job_files, 1):
        job = json.loads(job_file.read_text())
        out_path = Path(job["output_path"])

        if out_path.exists() and cfg.get("skip_existing"):
            print(f"  [{i}/{total}] [skip] {job['output_filename']}")
            continue

        print(f"  [{i}/{total}] Rendering: {job['output_filename']}")

        if dry_run:
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Build nexrender job JSON
        nxr_job = build_nexrender_job(job, str(output_aep))
        nxr_job_path = jobs_dir / f"_nxr_{job['comp_name']}.json"
        nxr_job_path.write_text(json.dumps(nxr_job, indent=2))

        cmd = [
            "nexrender-cli",
            "--file", str(nxr_job_path),
            "--aerender-path", aerender_path,
            "--no-license",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.strip():
                    print(f"    {line}")
        if result.returncode != 0:
            print(f"  ERROR rendering {job['output_filename']}:\n{result.stderr[:500]}")
        else:
            print(f"    → Saved: {job['output_filename']}")

    if dry_run:
        print(f"  [DRY RUN] Would render {total} comps")
    else:
        print(f"  Rendering complete")
