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
from pipeline.clients.firefly import generate_image as firefly_generate_image

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
GEN = ROOT / "generated" / "backgrounds"
GEN.mkdir(parents=True, exist_ok=True)

# Legacy key aliases — maps old aspect ratio labels to new resolution-string IDs.
# Allows brief JSONs generated before the sizes refactor to continue working.
_LEGACY_SIZE_MAP = {
    "16x9":      "1920x1080",
    "1x1":       "1080x1080",
    "Billboard": "970x250",
}

# No billboard suffix needed here — billboard prompt is supplied by step_02's
# background_prompt_billboard key and routed in process_variant().


def _build_size_lookup(cfg: dict) -> dict:
    """Return {size_id: {gen_width, gen_height, billboard}} from config, with legacy fallback."""
    sizes = cfg.get("sizes", [])
    if sizes:
        return {s["id"]: s for s in sizes}
    # Hardcoded fallback if config has no sizes yet
    return {
        "1920x1080": {"gen_width": 3840, "gen_height": 2160, "billboard": False},
        "1080x1080": {"gen_width": 2160, "gen_height": 2160, "billboard": False},
        "970x250":   {"gen_width": 1940, "gen_height":  500, "billboard": True},
    }


def _normalize_size_id(size_id: str) -> str:
    return _LEGACY_SIZE_MAP.get(size_id, size_id)


def _find_hero_stage1_image(product_id: str, model_id: str, variant_id: str,
                              cfg: dict) -> Path | None:
    """Return the best available stage1 image for the hero (1920x1080) size.

    Used as the reference image when generating the billboard atmospheric background.
    Prefers the primary image model's output; falls back to any available result.
    """
    hero_size = "1920x1080"
    slug = f"{product_id}_{model_id}_{variant_id}"
    base = GEN / slug / hero_size / "stage1"
    if not base.exists():
        return None

    primary_id = next(
        (m["id"] for m in cfg.get("stage1_image_models", []) if m.get("primary")), None
    )
    if primary_id:
        primary_dir = base / primary_id
        images = sorted(primary_dir.glob("gen_*.png")) if primary_dir.exists() else []
        if images:
            return images[-1]

    for img in sorted(base.rglob("gen_*.png")):
        return img
    return None


def _out_dir(product_id: str, model_id: str, variant_id: str, size_id: str) -> Path:
    slug = f"{product_id}_{model_id}_{variant_id}"
    return GEN / slug / size_id


def _next_gen_index(directory: Path) -> int:
    existing = list(directory.glob("gen_*.png")) + list(directory.glob("gen_*.mp4"))
    if not existing:
        return 1
    nums = [int(f.stem.split("_")[1]) for f in existing if f.stem.split("_")[1].isdigit()]
    return max(nums) + 1 if nums else 1


def _image_to_data_uri(path: Path) -> str:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return f"data:image/png;base64,{data}"


async def generate_stage1(fal_path: str | None, model_id: str, provider: str,
                           asset_png: Path, prompt: str, size_id: str,
                           gen_width: int, gen_height: int, is_billboard: bool,
                           out_dir: Path, gen_index: int,
                           skip_existing: bool) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "stage1" / model_id / f"gen_{gen_index:03d}.png"

    if skip_existing and out_path.exists():
        print(f"    [skip] {out_path.relative_to(ROOT)}")
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if provider == "firefly":
            client_id = os.environ.get("FIREFLY_CLIENT_ID", "")
            client_secret = os.environ.get("FIREFLY_CLIENT_SECRET", "")
            if not client_id or not client_secret:
                raise EnvironmentError("FIREFLY_CLIENT_ID / FIREFLY_CLIENT_SECRET not set")

            print(f"    Stage1 [{model_id}] {size_id} — submitting to Adobe Firefly...")
            img_bytes = await firefly_generate_image(
                client_id=client_id,
                client_secret=client_secret,
                prompt=prompt,
                width=gen_width,
                height=gen_height,
                reference_image_path=asset_png,
            )
            if img_bytes is None:
                raise RuntimeError("Firefly returned no image bytes")
            out_path.write_bytes(img_bytes)

        else:
            print(f"    Stage1 [{model_id}] {size_id} — submitting to fal.ai...")
            import httpx
            image_url = _image_to_data_uri(asset_png)

            result = await asyncio.to_thread(
                fal_client.run,
                fal_path,
                arguments={
                    "prompt": prompt,
                    "image_url": image_url,
                    "width": gen_width,
                    "height": gen_height,
                    "num_inference_steps": 28,
                    "guidance_scale": 3.5,
                }
            )

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
                           prompt: str, size_id: str, out_dir: Path,
                           gen_index: int, skip_existing: bool) -> Path | None:
    out_path = out_dir / "stage2" / model_id / f"gen_{gen_index:03d}.mp4"

    if skip_existing and out_path.exists():
        print(f"    [skip] {out_path.relative_to(ROOT)}")
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"    Stage2 [{model_id}] {size_id} — submitting to fal.ai...")

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
                           asset_png: Path, size_id: str, copy: dict,
                           cfg: dict, gen_index: int,
                           filter_model: str | None = None):
    size_id = _normalize_size_id(size_id)
    size_lookup = _build_size_lookup(cfg)
    size = size_lookup.get(size_id, {})
    gen_width = size.get("gen_width", 3840)
    gen_height = size.get("gen_height", 2160)
    is_billboard = size.get("billboard", False)

    out_dir = _out_dir(product_id, model_id, variant_id, size_id)
    skip = cfg.get("skip_existing", True)

    stage1_models = [m for m in cfg["stage1_image_models"] if m["enabled"]]
    stage2_models = [m for m in cfg["stage2_video_models"] if m["enabled"]]

    if filter_model:
        stage2_models = [m for m in stage2_models if m["id"] == filter_model]

    # Determine stage1 prompt and reference image
    if is_billboard:
        # Billboard: atmospheric texture generated from the hero (1920x1080) stage1 image
        # as a style reference rather than the raw product PNG.
        stage1_prompt = copy.get(
            "background_prompt_billboard",
            "Abstract atmospheric texture. Cinematic bokeh, warm depth, painterly. No objects or people.",
        )
        hero_img = _find_hero_stage1_image(product_id, model_id, variant_id, cfg)
        stage1_reference = hero_img if hero_img else asset_png
        if not hero_img:
            print(f"    [billboard] No hero image found — using product PNG as fallback reference")
    else:
        stage1_prompt = copy["background_prompt_stage1"]
        # Append per-size composition hint so the subject lands in the right area of frame
        composition_hint = size.get("composition_hint", "")
        if composition_hint:
            stage1_prompt = f"{stage1_prompt} {composition_hint}"
        stage1_reference = asset_png

    # Stage 1: run all enabled image models
    stage1_results: dict[str, Path] = {}
    primary_id = next((m["id"] for m in stage1_models if m.get("primary")), None)

    for img_model in stage1_models:
        result = await generate_stage1(
            fal_path=img_model.get("fal_path"),
            model_id=img_model["id"],
            provider=img_model.get("provider", "fal"),
            asset_png=stage1_reference,
            prompt=stage1_prompt,
            size_id=size_id,
            gen_width=gen_width,
            gen_height=gen_height,
            is_billboard=is_billboard,
            out_dir=out_dir,
            gen_index=gen_index,
            skip_existing=skip,
        )
        if result:
            stage1_results[img_model["id"]] = result

    # Choose the primary stage1 image for stage2 (or first available)
    stage1_for_video = stage1_results.get(primary_id) or next(iter(stage1_results.values()), None)
    if not stage1_for_video:
        print(f"    Skipping Stage2 — no Stage1 image for {product_id}/{model_id}/{variant_id}/{size_id}")
        return

    # Stage 2: animate using primary stage1 image as starting frame
    for vid_model in stage2_models:
        await generate_stage2(
            fal_path=vid_model["fal_path"],
            model_id=vid_model["id"],
            stage1_image=stage1_for_video,
            prompt=copy["background_prompt_stage2"],
            size_id=size_id,
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
    preview_size_id = _normalize_size_id(cfg.get("preview_size_id", cfg.get("preview_aspect_ratio", "1920x1080")))

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

                for size_id_raw in model_entry["aspect_ratios"]:
                    size_id = _normalize_size_id(size_id_raw)

                    if filter_aspect and size_id != _normalize_size_id(filter_aspect):
                        continue

                    if preview and (Path(asset_png).stem != preview_asset or size_id != preview_size_id):
                        continue

                    locale_for_prompt = filter_locale or "en"
                    copy_key = (product["id"], model_entry["id"], variant["id"], locale_for_prompt)
                    copy = copy_lookup.get(copy_key) or copy_lookup.get(
                        (product["id"], model_entry["id"], variant["id"], "en"), {}
                    )

                    if not copy:
                        print(f"  WARNING: No copy found for {copy_key}")
                        continue

                    out_dir = _out_dir(product["id"], model_entry["id"], variant["id"], size_id)
                    gen_index = _next_gen_index(out_dir)

                    tasks.append((
                        product["id"], model_entry["id"], variant["id"],
                        asset_png, size_id, copy, cfg, gen_index, filter_model
                    ))

    if dry_run:
        print(f"  [DRY RUN] Would generate backgrounds for {len(tasks)} variant/aspect combinations")
        return

    # Sort so billboard sizes run after non-billboard — billboard stage1 references the
    # hero (1920x1080) stage1 result, which must exist before billboard is processed.
    size_lookup = _build_size_lookup(cfg)
    tasks.sort(key=lambda t: 1 if size_lookup.get(t[4], {}).get("billboard", False) else 0)

    if preview:
        print(f"  Preview mode — {len(tasks)} combination(s) for asset '{preview_asset}' / {preview_size_id}")

    async def run_all():
        for args in tasks:
            await process_variant(*args)

    asyncio.run(run_all())
    print(f"  Background generation complete — {len(tasks)} targets processed")
