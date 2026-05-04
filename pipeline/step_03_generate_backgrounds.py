"""
Step 3: Two-stage background generation via fal.ai.

Stage 1 — Image synthesis: product PNG + scene prompt → instrument placed in scene
Stage 2 — Video animation: Stage 1 image + motion prompt → 6-8s animated clip

Output structure:
  generated/backgrounds/{product_id}_{model_id}_{variant_id}/{aspect_ratio}/
    stage1/{img_model_id}/gen_001.png   (2× target resolution)
    stage2/{vid_model_id}/gen_001.mp4   (6-8s, subtle motion)

Resolution targets (2× output resolution):
  16x9     → 3840×2160
  Billboard→ 3840×960  (generated as 16:9 then cropped in AE)
  1x1      → 2160×2160
"""
import asyncio
import base64
import json
import os
import time
from pathlib import Path

import fal_client
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
GEN = ROOT / "generated" / "backgrounds"
GEN.mkdir(parents=True, exist_ok=True)

# Generation resolution per aspect ratio (2× target)
RESOLUTIONS = {
    "16x9":      {"width": 3840, "height": 2160, "aspect": "16:9"},
    "Billboard": {"width": 3840, "height": 2160, "aspect": "16:9"},  # cropped in AE
    "1x1":       {"width": 2160, "height": 2160, "aspect": "1:1"},
}

# Billboard prompt addition to ensure horizontal-safe composition
BILLBOARD_PROMPT_SUFFIX = (
    " Wide cinematic horizontal composition. Subject centered left-to-right. "
    "Generous empty space above and below the subject to allow cropping to a banner format."
)


def _out_dir(product_id: str, model_id: str, variant_id: str, aspect: str) -> Path:
    slug = f"{product_id}_{model_id}_{variant_id}"
    return GEN / slug / aspect


def _next_gen_index(directory: Path) -> int:
    existing = list(directory.glob("gen_*.png")) + list(directory.glob("gen_*.mp4"))
    if not existing:
        return 1
    nums = [int(f.stem.split("_")[1]) for f in existing if f.stem.split("_")[1].isdigit()]
    return max(nums) + 1 if nums else 1


def _image_to_data_uri(path: Path) -> str:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return f"data:image/png;base64,{data}"


async def generate_stage1(fal_path: str, model_id: str, asset_png: Path,
                           prompt: str, aspect: str, out_dir: Path,
                           gen_index: int, skip_existing: bool) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "stage1" / model_id / f"gen_{gen_index:03d}.png"

    if skip_existing and out_path.exists():
        print(f"    [skip] {out_path.relative_to(ROOT)}")
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    res = RESOLUTIONS[aspect]

    full_prompt = prompt
    if aspect == "Billboard":
        full_prompt += BILLBOARD_PROMPT_SUFFIX

    print(f"    Stage1 [{model_id}] {aspect} — submitting to fal.ai...")

    try:
        image_url = _image_to_data_uri(asset_png)

        result = await asyncio.to_thread(
            fal_client.run,
            fal_path,
            arguments={
                "prompt": full_prompt,
                "image_url": image_url,
                "width": res["width"],
                "height": res["height"],
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
            }
        )

        # Download the result image
        import httpx
        img_url = result["images"][0]["url"] if "images" in result else result.get("image", {}).get("url")
        if not img_url:
            raise ValueError(f"No image URL in response: {list(result.keys())}")

        async with httpx.AsyncClient() as client:
            r = await client.get(img_url, timeout=60)
            r.raise_for_status()
            out_path.write_bytes(r.content)

        print(f"    Stage1 [{model_id}] saved → {out_path.name}")
        return out_path

    except Exception as e:
        print(f"    ERROR Stage1 [{model_id}]: {e}")
        return None


async def generate_stage2(fal_path: str, model_id: str, stage1_image: Path,
                           prompt: str, aspect: str, out_dir: Path,
                           gen_index: int, skip_existing: bool) -> Path | None:
    out_path = out_dir / "stage2" / model_id / f"gen_{gen_index:03d}.mp4"

    if skip_existing and out_path.exists():
        print(f"    [skip] {out_path.relative_to(ROOT)}")
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"    Stage2 [{model_id}] {aspect} — submitting to fal.ai...")

    try:
        image_url = _image_to_data_uri(stage1_image)

        result = await asyncio.to_thread(
            fal_client.run,
            fal_path,
            arguments={
                "prompt": prompt,
                "image_url": image_url,
                "duration": "8",
            }
        )

        # Download the result video
        import httpx
        vid_url = (
            result.get("video", {}).get("url")
            or (result.get("videos") or [{}])[0].get("url")
        )
        if not vid_url:
            raise ValueError(f"No video URL in response: {list(result.keys())}")

        async with httpx.AsyncClient() as client:
            r = await client.get(vid_url, timeout=120)
            r.raise_for_status()
            out_path.write_bytes(r.content)

        print(f"    Stage2 [{model_id}] saved → {out_path.name}")
        return out_path

    except Exception as e:
        print(f"    ERROR Stage2 [{model_id}]: {e}")
        return None


async def process_variant(product_id: str, model_id: str, variant_id: str,
                           asset_png: Path, aspect: str, copy: dict,
                           cfg: dict, gen_index: int,
                           filter_model: str | None = None):
    out_dir = _out_dir(product_id, model_id, variant_id, aspect)
    skip = cfg.get("skip_existing", True)

    stage1_models = [m for m in cfg["stage1_image_models"] if m["enabled"]]
    stage2_models = [m for m in cfg["stage2_video_models"] if m["enabled"]]

    if filter_model:
        stage2_models = [m for m in stage2_models if m["id"] == filter_model]

    # Stage 1: run all enabled image models
    stage1_results: dict[str, Path] = {}
    primary_id = next((m["id"] for m in stage1_models if m.get("primary")), None)

    for img_model in stage1_models:
        result = await generate_stage1(
            fal_path=img_model["fal_path"],
            model_id=img_model["id"],
            asset_png=asset_png,
            prompt=copy["background_prompt_stage1"],
            aspect=aspect,
            out_dir=out_dir,
            gen_index=gen_index,
            skip_existing=skip,
        )
        if result:
            stage1_results[img_model["id"]] = result

    # Choose the primary stage1 image for stage2 (or first available)
    stage1_for_video = stage1_results.get(primary_id) or next(iter(stage1_results.values()), None)
    if not stage1_for_video:
        print(f"    Skipping Stage2 — no Stage1 image available for {product_id}/{model_id}/{variant_id}/{aspect}")
        return

    # Stage 2: animate using primary stage1 image as starting frame
    for vid_model in stage2_models:
        await generate_stage2(
            fal_path=vid_model["fal_path"],
            model_id=vid_model["id"],
            stage1_image=stage1_for_video,
            prompt=copy["background_prompt_stage2"],
            aspect=aspect,
            out_dir=out_dir,
            gen_index=gen_index,
            skip_existing=skip,
        )


def run(cfg: dict, preview: bool = False, filter_asset: str | None = None,
        filter_locale: str | None = None, filter_aspect: str | None = None,
        filter_model: str | None = None, dry_run: bool = False):

    brief = json.loads((DATA / "campaign_brief.json").read_text())
    manifest = json.loads((DATA / "asset_manifest.json").read_text())
    copy_manifest = json.loads((DATA / "copy_manifest.json").read_text())

    # Build lookup: (product_id, model_id, variant_id) → asset_png
    asset_lookup: dict[tuple, Path] = {}
    for match in manifest["matches"]:
        key = (match["product_id"], match["model_id"], match["variant_id"])
        asset_lookup[key] = Path(match["asset_png"])

    # Build copy lookup: (product_id, model_id, variant_id, locale_id) → copy
    copy_lookup: dict[tuple, dict] = {}
    for entry in copy_manifest["variants"]:
        for locale_id, copy in entry["locales"].items():
            key = (entry["product_id"], entry["model_id"], entry["variant_id"], locale_id)
            copy_lookup[key] = copy

    # Build work list
    tasks = []
    locales = brief["locales"]

    preview_asset = cfg.get("preview_asset_id", "sax1")
    preview_aspect = cfg.get("preview_aspect_ratio", "16x9")

    for product in brief["products"]:
        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                asset_key = (product["id"], model_entry["id"], variant["id"])
                asset_png = asset_lookup.get(asset_key)

                if not asset_png or not Path(asset_png).exists():
                    print(f"  WARNING: No asset found for {asset_key}, skipping")
                    continue

                if filter_asset and Path(asset_png).stem != filter_asset:
                    continue

                for aspect in model_entry["aspect_ratios"]:
                    if filter_aspect and aspect != filter_aspect:
                        continue

                    if preview and (Path(asset_png).stem != preview_asset or aspect != preview_aspect):
                        continue

                    # Use English copy for background generation (locale-agnostic backgrounds)
                    # But allow locale override if locale filter is set
                    locale_for_prompt = filter_locale or "en"
                    copy_key = (product["id"], model_entry["id"], variant["id"], locale_for_prompt)
                    copy = copy_lookup.get(copy_key) or copy_lookup.get(
                        (product["id"], model_entry["id"], variant["id"], "en"), {}
                    )

                    if not copy:
                        print(f"  WARNING: No copy found for {copy_key}")
                        continue

                    out_dir = _out_dir(product["id"], model_entry["id"], variant["id"], aspect)
                    gen_index = _next_gen_index(out_dir)

                    tasks.append((
                        product["id"], model_entry["id"], variant["id"],
                        asset_png, aspect, copy, cfg, gen_index, filter_model
                    ))

    if dry_run:
        print(f"  [DRY RUN] Would generate backgrounds for {len(tasks)} variant/aspect combinations")
        return

    if preview:
        print(f"  Preview mode — {len(tasks)} combination(s) for asset '{preview_asset}' / {preview_aspect}")

    async def run_all():
        for args in tasks:
            await process_variant(*args)

    asyncio.run(run_all())
    print(f"  Background generation complete — {len(tasks)} targets processed")
