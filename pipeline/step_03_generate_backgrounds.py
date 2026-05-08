"""
Step 3: Background image generation via Google Gemini API (Nano Banana 2).

Scene prompt → Nano Banana 2 generates background still image at 2× target resolution.

Output structure:
  generated/backgrounds/{product_id}_{model_id}_{variant_id}/{size_id}/
    stage1/{img_model_id}/gen_001.png
"""
import asyncio
from collections import defaultdict
import io
import json
import os
from pathlib import Path

from PIL import Image

from google import genai
from google.genai import types
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
GEN = ROOT / "generated" / "backgrounds"
GEN.mkdir(parents=True, exist_ok=True)

_LEGACY_SIZE_MAP = {
    "16x9":      "1920x1080",
    "1x1":       "1080x1080",
    "Billboard": "970x250",
}


def _build_size_lookup(cfg: dict) -> dict:
    sizes = cfg.get("sizes", [])
    if sizes:
        return {s["id"]: s for s in sizes}
    return {
        "1920x1080": {"gen_width": 3840, "gen_height": 2160, "billboard": False},
        "1080x1080": {"gen_width": 2160, "gen_height": 2160, "billboard": False},
        "970x250":   {"gen_width": 1940, "gen_height":  500, "billboard": True},
    }


def _normalize_size_id(size_id: str) -> str:
    return _LEGACY_SIZE_MAP.get(size_id, size_id)


def _out_dir(product_id: str, model_id: str, variant_id: str, size_id: str) -> Path:
    slug = f"{product_id}_{model_id}_{variant_id}"
    return GEN / slug / size_id


def _next_gen_index(directory: Path, primary_model_id: str | None = None) -> int:
    """Return the next generation index for a variant/size directory.

    Scopes to the primary model's stage1 folder so that switching models or adding
    a second model doesn't inflate the index from unrelated previous runs.
    """
    if primary_model_id:
        search = directory / "stage1" / primary_model_id
        existing = sorted(search.glob("gen_*.png")) if search.exists() else []
    else:
        existing = list(directory.rglob("gen_*.png")) + list(directory.rglob("gen_*.mp4"))
    if not existing:
        return 1
    nums = [int(f.stem.split("_")[1]) for f in existing if f.stem.split("_")[1].isdigit()]
    return max(nums) + 1 if nums else 1


def _gemini_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _image_mime_type(path: Path) -> str:
    return "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"


def _aspect_ratio_label(gen_width: int, gen_height: int) -> str:
    """Human-readable aspect ratio label used in the prompt for non-standard ratios."""
    ratio = gen_width / gen_height
    if ratio >= 3.0:
        return "ultra-wide panoramic"
    elif ratio >= 1.5:
        return "16:9 landscape"
    elif ratio >= 1.1:
        return "4:3 landscape"
    elif ratio >= 0.9:
        return "1:1 square"
    elif ratio >= 0.7:
        return "3:4 portrait"
    else:
        return "9:16 portrait"


def _image_api_aspect_ratio(gen_width: int, gen_height: int) -> str:
    """Map pixel dimensions to the closest supported ImageConfig aspect_ratio string.
    Supported: 1:1, 1:4, 1:8, 2:3, 3:2, 3:4, 4:1, 4:3, 4:5, 5:4, 8:1, 9:16, 16:9, 21:9
    """
    ratio = gen_width / gen_height
    if ratio >= 6.0:
        return "8:1"
    elif ratio >= 3.0:
        return "4:1"   # billboard ~3.88:1
    elif ratio >= 2.0:
        return "21:9"
    elif ratio >= 1.6:
        return "16:9"
    elif ratio >= 1.2:
        return "4:3"
    elif ratio >= 1.0:
        return "1:1"
    elif ratio >= 0.75:
        return "4:5"
    elif ratio >= 0.6:
        return "3:4"
    elif ratio >= 0.4:
        return "2:3"
    elif ratio >= 0.2:
        return "1:4"
    else:
        return "1:8"


async def generate_stage1(model_id: str, gemini_model: str,
                           prompt: str, size_id: str,
                           gen_width: int, gen_height: int,
                           out_dir: Path, gen_index: int,
                           skip_existing: bool,
                           asset_png: Path | None = None,
                           brand_look: str = "",
                           ref_type: str = "product",
                           product_ref: Path | None = None) -> Path | None:
    """
    ref_type controls how the reference image is used:
      "product"  — asset_png is the client's uploaded product photo; enforce exact instrument fidelity
      "master"   — asset_png is the generated 16x9 hero; recreate same scene at new aspect ratio.
                   If product_ref is also supplied, both images are sent: hero for scene consistency,
                   product_ref for instrument fidelity.
      "billboard" — asset_png is the generated 16x9 hero; recreate scene at ultra-wide aspect ratio
    """
    out_path = out_dir / "stage1" / model_id / f"gen_{gen_index:03d}.png"

    if skip_existing and out_path.exists():
        print(f"    [skip] {out_path.relative_to(ROOT)}")
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ar_label = _aspect_ratio_label(gen_width, gen_height)
    full_prompt = f"{ar_label} composition. {prompt}"

    if ref_type != "billboard" and brand_look:
        full_prompt = f"{full_prompt}. {brand_look}"

    # Build multimodal contents with a reference image and a role-specific instruction
    if asset_png and Path(asset_png).exists():
        mime = _image_mime_type(Path(asset_png))
        asset_bytes = Path(asset_png).read_bytes()

        if ref_type == "product":
            full_prompt = (
                "Take the instrument shown in the attached reference image and place it into the scene "
                "with a person actively playing it. Do not change the details or look and feel of the "
                "instrument in any way and ensure it has the same appearance as the input image. "
                + full_prompt
            )
            contents = [
                types.Part.from_bytes(data=asset_bytes, mime_type=mime),
                full_prompt,
            ]
        elif ref_type == "master":
            if product_ref and Path(product_ref).exists():
                # Dual reference: hero image for scene consistency + product image for instrument fidelity
                product_mime = _image_mime_type(Path(product_ref))
                product_bytes = Path(product_ref).read_bytes()
                full_prompt = (
                    "Generate a NEW square (1:1) image. "
                    "Reference image 1 establishes the scene — match its lighting, mood, atmosphere, "
                    "and environment exactly. Reference image 2 is the exact instrument — match all "
                    "details, finish, and design precisely. "
                    "Crop tighter around the performer to create a natural square composition. "
                    "CRITICAL: Do NOT blend, ghost, double-expose, or composite either reference image "
                    "into the output — generate entirely fresh pixel content. "
                    "Do NOT squeeze, stretch, or distort the scene to fit a square canvas — "
                    "this is a crop-and-reframe operation, not a resize. "
                    "Performer and environment must look natural and undistorted within the square frame. "
                    + full_prompt
                )
                contents = [
                    types.Part.from_bytes(data=asset_bytes, mime_type=mime),
                    types.Part.from_bytes(data=product_bytes, mime_type=product_mime),
                    full_prompt,
                ]
            else:
                full_prompt = (
                    "Generate a NEW square (1:1) image. "
                    "The reference image establishes the scene — match its lighting, mood, atmosphere, "
                    "performer, instrument, and environment exactly. "
                    "Crop tighter around the performer to create a natural square composition. "
                    "CRITICAL: Do NOT blend, ghost, double-expose, or composite the reference image "
                    "into the output — generate entirely fresh pixel content. "
                    "Do NOT squeeze, stretch, or distort the scene to fit a square canvas — "
                    "this is a crop-and-reframe operation, not a resize. "
                    + full_prompt
                )
                contents = [
                    types.Part.from_bytes(data=asset_bytes, mime_type=mime),
                    full_prompt,
                ]
        elif ref_type == "billboard":
            if product_ref and Path(product_ref).exists():
                product_mime = _image_mime_type(Path(product_ref))
                product_bytes = Path(product_ref).read_bytes()
                full_prompt = (
                    "Generate a NEW ultra-wide panoramic image. "
                    "Reference image 1 establishes the scene — match its lighting, mood, atmosphere, "
                    "and environment exactly. Reference image 2 is the exact instrument — match all "
                    "details, finish, and design precisely. "
                    "Extend the environment naturally to the left and right, as if the camera pulled back "
                    "to reveal a wider view of the same venue — the crowd, architecture, lighting, and "
                    "atmosphere must flow and continue seamlessly across the full width with no hard edges, "
                    "visible seams, or abrupt transitions where the scene ends. "
                    "Performer on the RIGHT side. Left side darker and open for text overlay. "
                    "CRITICAL: Do NOT blend, ghost, double-expose, or composite either reference image "
                    "into the output — generate entirely fresh pixel content. "
                    + full_prompt
                )
                contents = [
                    types.Part.from_bytes(data=asset_bytes, mime_type=mime),
                    types.Part.from_bytes(data=product_bytes, mime_type=product_mime),
                    full_prompt,
                ]
            else:
                full_prompt = (
                    "Generate a NEW ultra-wide panoramic image. "
                    "The reference image establishes the scene — match its lighting, mood, atmosphere, "
                    "and environment exactly. "
                    "Extend the environment naturally to the left and right, as if the camera pulled back "
                    "to reveal a wider view of the same venue — the crowd, architecture, lighting, and "
                    "atmosphere must flow and continue seamlessly across the full width with no hard edges, "
                    "visible seams, or abrupt transitions where the scene ends. "
                    "Performer on the RIGHT side. Left side darker and open for text overlay. "
                    "CRITICAL: Do NOT blend, ghost, double-expose, or composite the reference image "
                    "into the output — generate entirely fresh pixel content. "
                    + full_prompt
                )
                contents = [
                    types.Part.from_bytes(data=asset_bytes, mime_type=mime),
                    full_prompt,
                ]
        else:
            contents = [
                types.Part.from_bytes(data=asset_bytes, mime_type=mime),
                full_prompt,
            ]
    else:
        contents = [full_prompt]

    api_ar = _image_api_aspect_ratio(gen_width, gen_height)
    print(f"    Stage1 [{model_id}] {size_id} ({ar_label}, 2K) — submitting to Nano Banana 2...")

    try:
        client = _gemini_client()

        def _run():
            return client.models.generate_content(
                model=gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    image_config=types.ImageConfig(
                        image_size="2K",
                        aspect_ratio=api_ar,
                    ),
                ),
            )

        response = await asyncio.wait_for(asyncio.to_thread(_run), timeout=120)

        img_bytes = None
        for part in response.parts:
            if part.inline_data is not None:
                img_bytes = part.inline_data.data
                break

        if not img_bytes:
            raise ValueError("Nano Banana 2 returned no image")

        # Nano Banana 2 returns JPEG bytes — convert to PNG for After Effects.
        img = Image.open(io.BytesIO(img_bytes))
        png_buf = io.BytesIO()
        img.save(png_buf, format="PNG")
        out_path.write_bytes(png_buf.getvalue())
        print(f"    Stage1 [{model_id}] saved → {out_path.name}")
        return out_path

    except Exception as e:
        print(f"    ERROR Stage1 [{model_id}]: {e}")
        return None


async def process_variant(product_id: str, model_id: str, variant_id: str,
                           asset_png: Path, size_id: str, copy: dict,
                           cfg: dict, gen_index: int,
                           master_ref: Path | None = None) -> Path | None:
    """Generate a Stage 1 background image for one variant/size.

    master_ref: path to an already-generated 16x9 hero image for this variant.
      If provided for a non-hero size, the hero is used as reference so the scene
      stays visually consistent across all output sizes.
    """
    size_id = _normalize_size_id(size_id)
    size_lookup = _build_size_lookup(cfg)
    size = size_lookup.get(size_id, {})
    gen_width = size.get("gen_width", 3840)
    gen_height = size.get("gen_height", 2160)

    out_dir = _out_dir(product_id, model_id, variant_id, size_id)
    skip = cfg.get("skip_existing", True)
    brand_look = cfg.get("brand_look", "")
    is_billboard = size.get("billboard", False)

    stage1_models = [m for m in cfg["stage1_image_models"] if m.get("enabled", True)]
    composition_hint = size.get("composition_hint", "")

    # Reinforces the audience requirement — the specific audience type is already
    # described in the stage1 prompt generated by step_02 from the brief's audience_context field.
    _AUDIENCE = (
        "The scene must include a visible audience in the background appropriate to the setting. "
        "The performer is the focus but audience members must be clearly present."
    )

    if is_billboard and master_ref is not None:
        # Billboard: extend the hero scene to ultra-wide — uses its own ref_type so the
        # instruction in generate_stage1 says "extend wide" rather than "crop tighter"
        stage1_prompt = copy.get("background_prompt_stage1", "")
        if composition_hint:
            stage1_prompt = f"{stage1_prompt} {composition_hint}"
        stage1_prompt = f"{stage1_prompt} {_AUDIENCE}"
        asset_for_stage1 = master_ref
        ref_type = "billboard"
    elif master_ref is not None:
        # Non-hero size with an approved hero — reframe around performer at new aspect ratio
        stage1_prompt = copy.get("background_prompt_stage1", "")
        if composition_hint:
            stage1_prompt = f"{stage1_prompt} {composition_hint}"
        stage1_prompt = f"{stage1_prompt} {_AUDIENCE}"
        asset_for_stage1 = master_ref
        ref_type = "master"
    else:
        # Hero / primary size — use the client's product photo to establish the instrument
        stage1_prompt = copy.get("background_prompt_stage1", "")
        if composition_hint:
            stage1_prompt = f"{stage1_prompt} {composition_hint}"
        stage1_prompt = f"{stage1_prompt} {_AUDIENCE}"
        asset_for_stage1 = asset_png
        ref_type = "product"

    # Stage 1: image generation
    stage1_results: dict[str, Path] = {}
    primary_id = next(
        (m["id"] for m in stage1_models if m.get("primary")),
        stage1_models[0]["id"] if stage1_models else None,
    )

    for img_model in stage1_models:
        result = await generate_stage1(
            model_id=img_model["id"],
            gemini_model=img_model.get("gemini_model", "gemini-3.1-flash-image-preview"),
            prompt=stage1_prompt,
            size_id=size_id,
            gen_width=gen_width,
            gen_height=gen_height,
            out_dir=out_dir,
            gen_index=gen_index,
            skip_existing=skip,
            asset_png=asset_for_stage1,
            brand_look=brand_look,
            ref_type=ref_type,
            product_ref=asset_png if ref_type == "master" else None,
        )
        if result:
            stage1_results[img_model["id"]] = result

    primary_stage1 = stage1_results.get(primary_id) or next(iter(stage1_results.values()), None)
    return primary_stage1


def run(cfg: dict, preview: bool = False, filter_asset: str | None = None,
        filter_locale: str | None = None, filter_aspect: str | None = None,
        filter_model: str | None = None, dry_run: bool = False):

    brief = json.loads((DATA / "campaign_brief.json").read_text())
    manifest = json.loads((DATA / "asset_manifest.json").read_text())
    copy_manifest = json.loads((DATA / "copy_manifest.json").read_text())

    asset_lookup: dict[tuple, Path] = {}
    for match in manifest["matches"]:
        key = (match["product_id"], match["model_id"], match["variant_id"])
        asset_lookup[key] = Path(match["asset_png"])

    copy_lookup: dict[tuple, dict] = {}
    for entry in copy_manifest["variants"]:
        for locale_id, copy in entry["locales"].items():
            key = (entry["product_id"], entry["model_id"], entry["variant_id"], locale_id)
            copy_lookup[key] = copy

    size_lookup = _build_size_lookup(cfg)
    tasks = []
    locales = brief["locales"]

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

                    locale_for_prompt = filter_locale or "en"
                    copy_key = (product["id"], model_entry["id"], variant["id"], locale_for_prompt)
                    copy = copy_lookup.get(copy_key) or copy_lookup.get(
                        (product["id"], model_entry["id"], variant["id"], "en"), {}
                    )

                    if not copy:
                        print(f"  WARNING: No copy found for {copy_key}")
                        continue

                    out_dir = _out_dir(product["id"], model_entry["id"], variant["id"], size_id)
                    primary_model_id = next(
                        (m["id"] for m in cfg.get("stage1_image_models", []) if m.get("primary")),
                        cfg.get("stage1_image_models", [{}])[0].get("id") if cfg.get("stage1_image_models") else None,
                    )
                    gen_index = _next_gen_index(out_dir, primary_model_id)

                    tasks.append((
                        product["id"], model_entry["id"], variant["id"],
                        asset_png, size_id, copy, cfg, gen_index
                    ))

    if dry_run:
        print(f"  [DRY RUN] Would generate backgrounds for {len(tasks)} variant/size combinations")
        return

    if preview:
        print(f"  Preview mode — {len(tasks)} combination(s) across all assets / en only")

    async def run_all():
        HERO_SIZE = "1920x1080"
        max_concurrent = cfg.get("gemini_concurrency", 4)
        sem = asyncio.Semaphore(max_concurrent)

        async def guarded(coro):
            async with sem:
                return await coro

        variant_groups: dict[tuple, list] = defaultdict(list)
        for task in tasks:
            variant_groups[(task[0], task[1], task[2])].append(task)

        async def run_variant(variant_tasks: list) -> None:
            hero   = [t for t in variant_tasks if t[4] == HERO_SIZE]
            others = [t for t in variant_tasks if t[4] != HERO_SIZE]

            master_ref = None
            if hero:
                p_id, m_id, v_id, a_png, s_id, cp, cfg_, gi = hero[0]
                result = await guarded(
                    process_variant(p_id, m_id, v_id, a_png, s_id, cp, cfg_, gi)
                )
                if result:
                    master_ref = result

            if others:
                async def run_other(task):
                    p_id, m_id, v_id, a_png, s_id, cp, cfg_, gi = task
                    await guarded(
                        process_variant(
                            p_id, m_id, v_id, a_png, s_id, cp, cfg_, gi,
                            master_ref=master_ref,
                        )
                    )
                await asyncio.gather(*[run_other(t) for t in others])

        await asyncio.gather(*[run_variant(vt) for vt in variant_groups.values()])

    asyncio.run(run_all())
    print(f"  Background generation complete — {len(tasks)} targets processed")
