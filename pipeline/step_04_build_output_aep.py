"""
Step 4: Build the output AEP via ExtendScript.

Reads campaign_brief.json, copy_manifest.json, and the generated backgrounds.
Writes data/aep_build_config.json (read by build_output_aep.jsx).
Runs aerender -script to execute the ExtendScript.
Result: output/{run_id}/yosuki_output_{run_id}.aep with one comp per variant.
"""
import json
import os
import subprocess
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
GEN = ROOT / "generated" / "backgrounds"
TEMPLATES = ROOT / "templates"
OUTPUT_BASE = ROOT / "output"
SCRIPTS = ROOT / "scripts"


def _comp_name_for_aspect(aspect: str) -> str:
    mapping = {
        "16x9":      "YouTube_1920x1080",
        "Billboard": "Billboard_970x250",
        "1x1":       "Instagram_1080x1080",
    }
    return mapping.get(aspect, "YouTube_1920x1080")


def _find_best_bg_video(product_id: str, model_id: str, variant_id: str,
                         aspect: str, cfg: dict) -> str | None:
    slug = f"{product_id}_{model_id}_{variant_id}"
    base = GEN / slug / aspect / "stage2"
    if not base.exists():
        return None

    # Prefer enabled models in order
    for vid_model in cfg["stage2_video_models"]:
        if not vid_model["enabled"]:
            continue
        model_dir = base / vid_model["id"]
        if model_dir.exists():
            videos = sorted(model_dir.glob("gen_*.mp4"))
            if videos:
                return str(videos[-1])
    return None


def build_jobs(brief: dict, copy_manifest: dict, cfg: dict, run_id: str) -> list[dict]:
    output_dir = OUTPUT_BASE / run_id / "renders"
    output_dir.mkdir(parents=True, exist_ok=True)

    copy_lookup: dict[tuple, dict] = {}
    for entry in copy_manifest["variants"]:
        for locale_id, copy in entry["locales"].items():
            key = (entry["product_id"], entry["model_id"], entry["variant_id"], locale_id)
            copy_lookup[key] = copy

    jobs = []
    for product in brief["products"]:
        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                for aspect in model_entry["aspect_ratios"]:
                    bg_video = _find_best_bg_video(
                        product["id"], model_entry["id"], variant["id"], aspect, cfg
                    )
                    if not bg_video:
                        print(f"  WARNING: No background video for "
                              f"{product['id']}/{model_entry['id']}/{variant['id']}/{aspect} — skipping")
                        continue

                    for locale in brief["locales"]:
                        copy_key = (product["id"], model_entry["id"], variant["id"], locale["id"])
                        copy = copy_lookup.get(copy_key)
                        if not copy:
                            print(f"  WARNING: No copy for {copy_key}")
                            continue

                        asset_stem = Path(bg_video).parents[2].name.split("_")[-1]
                        # Recover asset stem from manifest
                        asset_stem = f"{model_entry['id']}"
                        if variant.get("color"):
                            color_suffix = "-a" if "black" in (variant["color"] or "").lower() else "-b"
                            asset_stem += color_suffix

                        locale_code = locale["id"].upper()
                        gen_num = int(Path(bg_video).stem.split("_")[1])
                        output_filename = f"{locale_code}_{asset_stem}_{aspect}_{gen_num:03d}.mp4"
                        output_path = str(output_dir / output_filename)

                        comp_name = output_filename.replace(".mp4", "")

                        jobs.append({
                            "comp_name": comp_name,
                            "composition_name": _comp_name_for_aspect(aspect),
                            "locale": locale["id"],
                            "product_id": product["id"],
                            "model_id": model_entry["id"],
                            "variant_id": variant["id"],
                            "asset_stem": asset_stem,
                            "aspect": aspect,
                            "bg_video_path": bg_video,
                            "logo_path": str(ROOT / "fde_asset_bundle" / "logo.png"),
                            "tagline": copy["tagline"],
                            "product_name": copy["product_name"],
                            "cta": copy["cta"],
                            "output_filename": output_filename,
                            "output_path": output_path,
                        })

    return jobs


def run(cfg: dict, dry_run: bool = False):
    brief_path = DATA / "campaign_brief.json"
    copy_path = DATA / "copy_manifest.json"
    master_aep = TEMPLATES / "yosuki_master_template.aep"

    if not brief_path.exists():
        raise FileNotFoundError("campaign_brief.json not found — run Step 1 first")
    if not copy_path.exists():
        raise FileNotFoundError("copy_manifest.json not found — run Step 2 first")
    if not master_aep.exists():
        raise FileNotFoundError(
            f"Master template not found at {master_aep}\n"
            "Create it in After Effects using scripts/create_template.jsx, "
            "then save to templates/yosuki_master_template.aep"
        )

    brief = json.loads(brief_path.read_text())
    copy_manifest = json.loads(copy_path.read_text())

    run_id_file = DATA / "current_run_id.txt"
    run_id = run_id_file.read_text().strip() if run_id_file.exists() else str(uuid.uuid4())[:8]
    run_id_file.write_text(run_id)

    jobs = build_jobs(brief, copy_manifest, cfg, run_id)
    print(f"  Built {len(jobs)} render jobs")

    output_aep = OUTPUT_BASE / run_id / f"yosuki_output_{run_id}.aep"
    output_aep.parent.mkdir(parents=True, exist_ok=True)

    aep_config = {
        "master_aep_path": str(master_aep),
        "output_aep_path": str(output_aep),
        "logo_path": str(ROOT / "fde_asset_bundle" / "logo.png"),
        "jobs": jobs,
    }
    config_path = DATA / "aep_build_config.json"
    config_path.write_text(json.dumps(aep_config, indent=2))

    # Also write individual nexrender job JSONs
    jobs_dir = DATA / "render_jobs"
    jobs_dir.mkdir(exist_ok=True)
    for job in jobs:
        job_path = jobs_dir / f"{job['comp_name']}.json"
        job_path.write_text(json.dumps(job, indent=2))

    if dry_run:
        print(f"  [DRY RUN] Would build output AEP at {output_aep}")
        print(f"  [DRY RUN] Would run ExtendScript with {len(jobs)} jobs")
        return

    aerender = cfg.get("aerender_path") or os.environ.get("AERENDER_PATH", "aerender")
    script_path = SCRIPTS / "build_output_aep.jsx"

    cmd = [aerender, "-script", str(script_path)]
    print(f"  Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        for line in result.stdout.splitlines():
            print(f"  [AE] {line}")
    if result.returncode != 0:
        raise RuntimeError(f"aerender ExtendScript failed (exit {result.returncode}):\n{result.stderr}")

    print(f"  Output AEP saved: {output_aep}")
