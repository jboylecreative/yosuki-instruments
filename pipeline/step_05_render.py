"""
Step 5: Render all variant comps via a single aerender session, then batch-encode to MP4.

Reads data/aep_build_config.json for the output AEP path and job list.
Step 4 baked all comps into the output AEP's render queue (lossless output).
A single aerender call processes every queued item — one AE startup, one project load.
FFmpeg then batch-encodes the lossless files to H.264 MP4 and cleans up the intermediates.

This replaces the previous nexrender-per-comp approach, which paid the AE startup
and project-load cost (35-40 seconds) once per comp.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"


def _find_aerender(cfg_path: str) -> str:
    if cfg_path and Path(cfg_path).exists():
        return cfg_path
    # Dynamically scan the Adobe install directory so any AE version works
    if sys.platform == "win32":
        adobe_root = Path(r"C:\Program Files\Adobe")
        exe_name = Path("Support Files") / "aerender.exe"
    else:
        adobe_root = Path("/Applications")
        exe_name = Path("aerender")
    if adobe_root.is_dir():
        hits = sorted(
            [d / exe_name for d in adobe_root.iterdir()
             if d.is_dir() and d.name.startswith("Adobe After Effects") and (d / exe_name).exists()],
            reverse=True,  # newest version first (lexicographic sort works for YYYY suffix)
        )
        if hits:
            return str(hits[0])
    raise RuntimeError(
        "aerender not found. Set 'aerender_path' in config.json or in the AERENDER_PATH env var.\n"
        '  Windows: "C:/Program Files/Adobe/Adobe After Effects YYYY/Support Files/aerender.exe"\n'
        '  macOS:   "/Applications/Adobe After Effects YYYY/aerender"'
    )


def _find_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError(
        "ffmpeg not found. Run: pip install imageio-ffmpeg\n"
        "Or install ffmpeg system-wide and ensure it is on your PATH."
    )


def run(cfg: dict, dry_run: bool = False):
    config_path = DATA / "aep_build_config.json"
    if not config_path.exists():
        raise FileNotFoundError("aep_build_config.json not found — run Step 4 first")

    aep_config = json.loads(config_path.read_text(encoding="utf-8"))
    output_aep = Path(aep_config["output_aep_path"])
    jobs = aep_config.get("jobs", [])

    if not output_aep.exists():
        raise FileNotFoundError(
            f"Output AEP not found: {output_aep}\n"
            "Run Step 4 first to build the output AEP."
        )

    total = len(jobs)
    print(f"  {total} comps queued in {output_aep.name}")

    if dry_run:
        print(f"  [DRY RUN] Would render {total} comps via single aerender session")
        return

    aerender_path = _find_aerender(
        cfg.get("aerender_path") or os.environ.get("AERENDER_PATH", "")
    )
    print(f"  aerender: {aerender_path}")

    # Single aerender call — opens the output AEP once, renders the full queue
    print(f"  Starting aerender session (renders all {total} comps)...")
    cmd = [aerender_path, "-project", str(output_aep)]
    result = subprocess.run(cmd, text=True)

    if result.returncode != 0:
        print(f"  ERROR: aerender exited with code {result.returncode}")
        return

    # Batch encode lossless (AVI/MOV) → H.264 MP4
    print(f"  Encoding lossless renders to MP4...")
    ffmpeg = _find_ffmpeg()
    encoded = 0
    failed = []

    for job in jobs:
        lossless = Path(job.get("output_lossless_path", ""))
        out_path = Path(job["output_path"])

        if not lossless.exists():
            print(f"  WARNING: lossless not found: {lossless.name} — skipping encode")
            failed.append(job["output_filename"])
            continue

        if out_path.exists() and cfg.get("skip_existing"):
            print(f"  [skip] {job['output_filename']}")
            lossless.unlink(missing_ok=True)
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        enc_cmd = [
            ffmpeg, "-y", "-i", str(lossless),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        enc = subprocess.run(enc_cmd, capture_output=True, text=True)
        if enc.returncode == 0:
            lossless.unlink(missing_ok=True)
            encoded += 1
            print(f"  → {job['output_filename']}")
        else:
            print(f"  ERROR encoding {job['output_filename']}:")
            print(f"    {enc.stderr[-300:].strip()}")
            failed.append(job["output_filename"])

    # Remove lossless temp dir if empty
    lossless_dirs = {
        Path(j["output_lossless_path"]).parent
        for j in jobs
        if j.get("output_lossless_path")
    }
    for d in lossless_dirs:
        try:
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        except Exception:
            pass

    print(f"  Encoded {encoded}/{total} renders")
    if failed:
        print(f"  Failed: {', '.join(failed)}")
