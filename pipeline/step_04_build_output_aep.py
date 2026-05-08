"""
Step 4: Prepare render job manifests and build the output AEP headlessly.

Reads campaign_brief.json, copy_manifest.json, and the generated backgrounds.

1. Writes data/render_jobs/*.json — one job file per variant/locale/size.

2. Builds the deliverable output AEP via nexrender:
   nexrender opens master_template.aep, runs build_output_aep.jsx as a prerender
   script (which duplicates all variant comps, bakes in footage + text, adds them
   to the render queue, and saves the output AEP), then renders one frame to
   trigger the script. Requires npm install to have been run once.

One-time setup: run scripts/create_template.jsx inside After Effects once to
create the master template. After that, all runs are fully headless.

Result: {output_base}/{project_name}/{YYYY-MM-DD_HH-MM-SS}/
  output_{YYYY-MM-DD_HH-MM-SS}.aep   ← deliverable AEP with all baked variant comps
  renders/*.mp4                        ← written by Step 5
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
GEN = ROOT / "generated" / "backgrounds"
TEMPLATES = ROOT / "templates"
SCRIPTS = ROOT / "scripts"


def _resolve_output_base(cfg: dict) -> Path:
    dest = cfg.get("output_destination", {})
    local_path = dest.get("local_path", "./output")
    p = Path(local_path)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _run_output_dir(cfg: dict, run_timestamp: str) -> Path:
    project_name = cfg.get("project_name", "output")
    return _resolve_output_base(cfg) / project_name / run_timestamp


_LEGACY_SIZE_MAP = {
    "16x9":      "1920x1080",
    "1x1":       "1080x1080",
    "Billboard": "970x250",
}

_DEFAULT_COMP_NAMES = {
    "1920x1080": "YouTube_1920x1080",
    "1080x1080": "Instagram_1080x1080",
    "970x250":   "Billboard_970x250",
}


def _normalize_size_id(size_id: str) -> str:
    return _LEGACY_SIZE_MAP.get(size_id, size_id)


def _comp_name_for_size(size_id: str, cfg: dict) -> str:
    size_id = _normalize_size_id(size_id)
    for s in cfg.get("sizes", []):
        if s["id"] == size_id:
            return s.get("comp_name", f"Comp_{size_id}")
    return _DEFAULT_COMP_NAMES.get(size_id, f"Comp_{size_id}")


def _size_dimensions(size_id: str, cfg: dict) -> tuple[int, int]:
    """Return (width, height) for a size_id, looking up config first then parsing the ID string."""
    for s in cfg.get("sizes", []):
        if s["id"] == size_id:
            return s.get("width", 1920), s.get("height", 1080)
    # Custom sizes not yet in config — parse from "WxH" string
    try:
        w, h = size_id.split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1920, 1080


def _find_best_bg_media(product_id: str, model_id: str, variant_id: str,
                         size_id: str, cfg: dict) -> str | None:
    """Returns path to best available background: Stage 2 video if present, Stage 1 PNG otherwise."""
    size_id = _normalize_size_id(size_id)
    slug = f"{product_id}_{model_id}_{variant_id}"
    base = GEN / slug / size_id

    # Prefer Stage 2 video (Advanced mode)
    stage2_base = base / "stage2"
    if stage2_base.exists():
        for vid_model in cfg.get("stage2_video_models", []):
            if not vid_model.get("enabled", False):
                continue
            model_dir = stage2_base / vid_model["id"]
            if model_dir.exists():
                videos = sorted(model_dir.glob("gen_*.mp4"))
                if videos:
                    return str(videos[-1])

    # Fall back to Stage 1 still image (Easy mode — no video generated)
    stage1_base = base / "stage1"
    if stage1_base.exists():
        primary_id = next(
            (m["id"] for m in cfg.get("stage1_image_models", []) if m.get("primary")), None
        )
        if primary_id:
            primary_dir = stage1_base / primary_id
            images = sorted(primary_dir.glob("gen_*.png")) if primary_dir.exists() else []
            if images:
                return str(images[-1])
        for img in sorted(stage1_base.rglob("gen_*.png")):
            return str(img)

    return None


def _logo_path(cfg: dict) -> str:
    assets_folder = cfg.get("assets_folder", "./fde_asset_bundle")
    base = Path(assets_folder) if Path(assets_folder).is_absolute() else (ROOT / assets_folder).resolve()
    return str(base / "logo.png")


def _product_label(product_id: str) -> str:
    return " ".join(w.capitalize() for w in product_id.replace("-", " ").split())


def build_jobs(brief: dict, copy_manifest: dict, cfg: dict,
               run_timestamp: str, master_aep: Path) -> list[dict]:
    output_base = _run_output_dir(cfg, run_timestamp) / "renders"
    output_base.mkdir(parents=True, exist_ok=True)

    # Lossless intermediates written by aerender; FFmpeg encodes them to MP4 in step 5
    lossless_ext = "avi" if sys.platform == "win32" else "mov"
    lossless_base = _run_output_dir(cfg, run_timestamp) / "lossless"
    lossless_base.mkdir(parents=True, exist_ok=True)

    copy_lookup: dict[tuple, dict] = {}
    for entry in copy_manifest["variants"]:
        for locale_id, copy in entry["locales"].items():
            key = (entry["product_id"], entry["model_id"], entry["variant_id"], locale_id)
            copy_lookup[key] = copy

    jobs = []
    for product in brief["products"]:
        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                for size_id_raw in model_entry["aspect_ratios"]:
                    size_id = _normalize_size_id(size_id_raw)
                    bg_media = _find_best_bg_media(
                        product["id"], model_entry["id"], variant["id"], size_id, cfg
                    )
                    if not bg_media:
                        print(f"  WARNING: No background media for "
                              f"{product['id']}/{model_entry['id']}/{variant['id']}/{size_id} — skipping")
                        continue

                    for locale in brief["locales"]:
                        copy_key = (product["id"], model_entry["id"], variant["id"], locale["id"])
                        copy = copy_lookup.get(copy_key)
                        if not copy:
                            print(f"  WARNING: No copy for {copy_key}")
                            continue

                        variant_id_clean = variant["id"].replace(" ", "-").lower()
                        if variant_id_clean and variant_id_clean != "standard":
                            asset_stem = f"{model_entry['id']}-{variant_id_clean}"
                        else:
                            asset_stem = model_entry["id"]

                        locale_code = locale["id"].upper()
                        gen_num = int(Path(bg_media).stem.split("_")[1])
                        output_filename = f"{locale_code}_{asset_stem}_{size_id}_{gen_num:03d}.mp4"
                        # Renders go into renders/{Instrument}/{LOCALE}/
                        instrument_label = _product_label(product["id"])
                        output_dir = output_base / instrument_label / locale_code
                        output_dir.mkdir(parents=True, exist_ok=True)
                        output_path = str(output_dir / output_filename)
                        comp_name = output_filename.replace(".mp4", "")
                        # Forward slashes required for ExtendScript's File() on Windows
                        output_lossless_path = (
                            lossless_base / f"{comp_name}.{lossless_ext}"
                        ).as_posix()

                        w, h = _size_dimensions(size_id, cfg)
                        jobs.append({
                            "comp_name": comp_name,
                            "composition_name": _comp_name_for_size(size_id, cfg),
                            "master_aep_path": str(master_aep),
                            "locale": locale["id"],
                            "product_id": product["id"],
                            "model_id": model_entry["id"],
                            "variant_id": variant["id"],
                            "asset_stem": asset_stem,
                            "size_id": size_id,
                            "width": w,
                            "height": h,
                            "bg_media_path": bg_media,
                            "logo_path": _logo_path(cfg),
                            "tagline": copy["tagline"],
                            "product_name": copy["product_name"],
                            "cta": copy["cta"],
                            "output_filename": output_filename,
                            "output_path": output_path,
                            "output_lossless_path": output_lossless_path,
                        })

    return jobs


def _find_nexrender() -> str:
    local_name = "nexrender-cli.cmd" if sys.platform == "win32" else "nexrender-cli"
    local = ROOT / "node_modules" / ".bin" / local_name
    if local.exists():
        return str(local)
    import shutil as _shutil
    found = _shutil.which("nexrender-cli")
    if found:
        return found
    raise RuntimeError(
        "nexrender-cli not found — run npm install in the project root first"
    )


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


def _build_output_aep_headless(
    master_aep: Path, output_aep: Path, config_path: Path, aerender_path: str
) -> bool:
    """
    Run build_output_aep.jsx headlessly via nexrender.
    Returns True if output_aep was created successfully.
    """
    jsx_template_path = SCRIPTS / "build_output_aep.jsx"
    jsx_text = jsx_template_path.read_text(encoding="utf-8")
    config_path_fwd = str(config_path).replace("\\", "/")
    jsx_runtime_text = jsx_text.replace("__CONFIG_PATH__", config_path_fwd)
    jsx_runtime = DATA / "_build_aep_runtime.jsx"
    jsx_runtime.write_text(jsx_runtime_text, encoding="utf-8")

    # Render frame 0 of one comp so aerender runs and the prerender JSX executes.
    # The rendered frame is discarded; the JSX's side-effect (saving output.aep) is what we want.
    lossless_ext = "avi" if sys.platform == "win32" else "mov"
    nxr_job = {
        "template": {
            "src": master_aep.as_uri(),
            "composition": "YouTube_1920x1080",
            "outputModule": "Lossless",
            "outputExt": lossless_ext,
            "settingsTemplate": "Best Settings",
            "frameStart": 0,
            "frameEnd": 0,
        },
        "assets": [
            {
                "type": "script",
                "src": jsx_runtime.as_uri(),
            }
        ],
    }
    nxr_job_path = DATA / "_build_aep_job.json"
    nxr_job_path.write_text(json.dumps(nxr_job, indent=2))

    bin_path = _find_nexrender()
    args = [bin_path, "--file", str(nxr_job_path), "--binary", aerender_path, "--no-license"]
    if sys.platform == "win32" and bin_path.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c"] + args
    else:
        cmd = args

    print(f"  Building output AEP headlessly via nexrender...")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    for line in result.stdout.splitlines():
        if line.strip():
            print(f"    {line}")
    if result.returncode != 0 and result.stderr:
        print(f"    nexrender stderr: {result.stderr[:500]}")

    if output_aep.exists():
        print(f"  Output AEP: {output_aep}")
        return True

    print(f"  WARNING: Output AEP not created — nexrender script may have failed")
    print(f"  Tip: make sure setup.bat / setup.sh was run as admin at least once")
    return False


def run(cfg: dict, dry_run: bool = False, preview: bool = False):
    brief_path = DATA / "campaign_brief.json"
    copy_path = DATA / "copy_manifest.json"

    master_aep_cfg = cfg.get("master_template_path")
    if master_aep_cfg:
        master_aep = Path(master_aep_cfg) if Path(master_aep_cfg).is_absolute() else (ROOT / master_aep_cfg).resolve()
    else:
        candidates = sorted(TEMPLATES.glob("*.aep"))
        master_aep = candidates[0] if candidates else TEMPLATES / "master_template.aep"

    if not brief_path.exists():
        raise FileNotFoundError("campaign_brief.json not found — run Step 1 first")
    if not copy_path.exists():
        raise FileNotFoundError("copy_manifest.json not found — run Step 2 first")

    if not master_aep.exists():
        create_jsx = SCRIPTS / "create_template.jsx"
        raise RuntimeError(
            f"\n\nMaster template not found: {master_aep}\n\n"
            f"One-time setup required — create it manually in After Effects:\n"
            f"  1. Open After Effects\n"
            f"  2. Go to File > Scripts > Run Script File\n"
            f"  3. Select: {create_jsx}\n"
            f"  4. The script saves the template automatically to: {master_aep}\n\n"
            f"Then re-run the pipeline. This only needs to be done once."
        )

    print(f"  Master template: {master_aep}")

    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    copy_manifest = json.loads(copy_path.read_text(encoding="utf-8"))

    run_id_file = DATA / "current_run_id.txt"
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_id_file.write_text(run_timestamp)

    run_dir = _run_output_dir(cfg, run_timestamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    jobs = build_jobs(brief, copy_manifest, cfg, run_timestamp, master_aep)
    if preview:
        preview_asset = cfg.get("preview_asset_id", "").strip()
        if preview_asset:
            jobs = [j for j in jobs if j.get("asset_stem") == preview_asset]
            print(f"  Preview mode — filtered to asset '{preview_asset}'")
    print(f"  Built {len(jobs)} render jobs")
    print(f"  Output dir: {run_dir}")

    # Output AEP path — created headlessly below
    output_aep = run_dir / f"output_{run_timestamp}.aep"

    # Write config consumed by build_output_aep.jsx and the web app
    config_path = DATA / "aep_build_config.json"
    config_path.write_text(json.dumps({
        "master_aep_path": str(master_aep),
        "output_aep_path": str(output_aep),
        "logo_path": _logo_path(cfg),
        "jobs": jobs,
    }, indent=2))

    # Clear stale jobs from any previous run before writing the new set
    jobs_dir = DATA / "render_jobs"
    jobs_dir.mkdir(exist_ok=True)
    for old in jobs_dir.glob("*.json"):
        old.unlink()

    for job in jobs:
        job_path = jobs_dir / f"{job['comp_name']}.json"
        job_path.write_text(json.dumps(job, indent=2))

    if dry_run:
        print(f"  [DRY RUN] Would build output AEP and render {len(jobs)} comps from {master_aep.name}")
        return

    # Build the deliverable output AEP headlessly via nexrender
    aerender_cfg = cfg.get("aerender_path") or os.environ.get("AERENDER_PATH", "")
    try:
        aerender_path = _find_aerender(aerender_cfg)
        _build_output_aep_headless(master_aep, output_aep, config_path, aerender_path)
    except Exception as e:
        print(f"  WARNING: Could not build output AEP: {e}")
        print(f"  MP4 renders will still work (Step 5) — output AEP is a separate deliverable")

    print(f"  Output AEP ready — run Step 5 to render all {len(jobs)} comps via aerender")
