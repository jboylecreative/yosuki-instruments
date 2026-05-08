"""
Step 5: Render every variant comp with its own aerender invocation, then batch-encode to MP4.

Reads data/aep_build_config.json for the output AEP path and job list.
Each job triggers a dedicated `aerender -comp <name>` call: one comp per process.
This is slower than a single batched session (every call pays ~35-40s of AE startup),
but a failure in one comp can't cascade into the rest of the queue — which is what
we observed when running 30 items in a single aerender session on some machines.
FFmpeg then batch-encodes the lossless files to H.264 MP4 and cleans up the intermediates.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"


def _ae_is_running() -> bool:
    """Return True if an AfterFX or aerender process is currently running."""
    if sys.platform == "win32":
        for exe in ("AfterFX.exe", "aerender.exe"):
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"],
                capture_output=True, text=True,
            )
            if exe.lower() in result.stdout.lower():
                return True
        return False
    else:
        # macOS: pgrep -xi matches exact process name, case-insensitive
        for name in ("aerender", "After Effects"):
            result = subprocess.run(
                ["pgrep", "-xi", name],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return True
        return False


def _wait_for_ae_exit(timeout: int = 60) -> None:
    """Wait for any lingering AfterFX/aerender processes to exit before starting a new session."""
    deadline = time.time() + timeout
    warned = False
    while time.time() < deadline:
        if not _ae_is_running():
            return
        if not warned:
            print("  Waiting for previous After Effects process to exit...")
            warned = True
        time.sleep(2)
    print(f"  WARNING: After Effects process still running after {timeout}s — aerender may fail")


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
        print(f"  [DRY RUN] Would render {total} comps via per-comp aerender calls")
        return

    aerender_path = _find_aerender(
        cfg.get("aerender_path") or os.environ.get("AERENDER_PATH", "")
    )
    print(f"  aerender: {aerender_path}")

    # Per-comp aerender calls — isolate each render so a failure in one comp
    # can't kill the rest of the queue. Each call costs ~35-40s of AE startup
    # but the pipeline survives individual failures and we get clear per-comp logs.
    print(f"  Rendering {total} comps individually (one aerender call per comp)...")
    ae_log = output_aep.parent / "aerender_step5.log"
    rendered = 0
    render_failed: list[str] = []

    for idx, job in enumerate(jobs, 1):
        comp_name = job["comp_name"]
        lossless_path = Path(job["output_lossless_path"])
        out_path = Path(job["output_path"])

        # If the final MP4 is already there and skip_existing is set, skip both
        # the render and the encode for this comp.
        if out_path.exists() and cfg.get("skip_existing"):
            print(f"  [{idx}/{total}] {comp_name} — already encoded, skipping")
            rendered += 1
            continue

        # Wait for any prior AE instance (from Step 4 or the previous comp) to
        # fully exit. aerender fails with "Error Code: 1" if a prior AE process
        # is still shutting down.
        _wait_for_ae_exit()

        lossless_path.parent.mkdir(parents=True, exist_ok=True)

        # Use the render queue item settings the JSX already baked into the AEP
        # (output path, OM template, render settings). Passing -output / -OMtemplate
        # / -RStemplate on the CLI alongside an existing queue item produces an
        # exit-0-but-no-output failure mode on AE 2026.
        print(f"  [{idx}/{total}] Rendering {comp_name}...")
        cmd = [
            aerender_path,
            "-project", str(output_aep),
            "-comp", comp_name,
            "-log", str(ae_log),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and lossless_path.exists():
            print(f"  [{idx}/{total}] -> {comp_name}")
            rendered += 1
        else:
            print(f"  [{idx}/{total}] ERROR: {comp_name} (exit code {result.returncode})")
            # Show what aerender actually wrote where we expected output
            if not lossless_path.exists():
                siblings = sorted(p.name for p in lossless_path.parent.glob("*"))
                print(f"    Expected: {lossless_path.name}")
                print(f"    Actual files in {lossless_path.parent.name}/: {siblings or '(empty)'}")
            if result.stderr.strip():
                tail = "\n".join(result.stderr.strip().splitlines()[-5:])
                print(f"    [stderr] {tail}")
            if result.stdout.strip():
                tail = "\n".join(result.stdout.strip().splitlines()[-10:])
                print(f"    [stdout] {tail}")
            if ae_log.exists():
                log_text = ae_log.read_text(encoding="utf-8", errors="replace").strip()
                if log_text:
                    log_tail = "\n".join(log_text.splitlines()[-15:])
                    print(f"    [aerender log] {log_tail}")
            render_failed.append(comp_name)

    print(f"  Rendered {rendered}/{total} comps")
    if render_failed:
        print(f"  Render failures ({len(render_failed)}): {', '.join(render_failed)}")

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
