"""
Step 2: Generate all per-locale copy using Gemini 3.1 Pro.

For each product variant × locale, produces:
  - tagline (≤40 chars, ≤6 words, culturally adapted)
  - cta (≤25 chars, ≤4 words)
  - product_name (display name for that locale)
  - background_prompt_stage1 (for Nano Banana Pro — product placement in scene)
  - background_prompt_stage2 (for video models — subtle motion direction)

Saves copy_manifest.json.
"""
import json
import os
import re
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"

CHAR_LIMITS = {
    "tagline": 40,
    "cta": 25,
    "de": {"tagline": 32, "cta": 20},  # German gets tighter limits
}


def _gemini_client():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    return genai.GenerativeModel("gemini-3.1-pro-preview")


def _tagline_limit(locale_id: str) -> int:
    return CHAR_LIMITS.get(locale_id, {}).get("tagline", CHAR_LIMITS["tagline"])


def _cta_limit(locale_id: str) -> int:
    return CHAR_LIMITS.get(locale_id, {}).get("cta", CHAR_LIMITS["cta"])


def generate_copy_for_variant(model, product: dict, model_entry: dict, variant: dict,
                               locale: dict, char_limits: dict, retries: int = 2) -> dict:
    tagline_limit = _tagline_limit(locale["id"])
    cta_limit = _cta_limit(locale["id"])

    scene = product["creative_direction"]["scene"]
    vibe = product["creative_direction"]["vibe"]
    visual_motif = product["creative_direction"]["visual_motif"]

    # Check for locale-specific scene override
    overrides = locale.get("locale_creative_overrides", {})
    product_override = overrides.get(product["id"], {})
    scene_override = product_override.get("scene_override")
    effective_scene = scene_override if scene_override else scene

    color_note = f" (color variant: {variant['color']})" if variant.get("color") else ""
    series_name = product["series"]
    model_name = model_entry["name"]
    key_message = product["key_message"]
    locale_lang = locale["language"]
    locale_tone = locale["cultural_tone"]

    prompt = f"""You are a creative copywriter for a motion graphics advertising campaign.

Product: {model_name}{color_note}
Series: {series_name}
Key message concept: "{key_message}"
Target language: {locale_lang}
Cultural tone: {locale_tone}

Scene description for background: {effective_scene}
Vibe: {vibe}
Visual motifs: {visual_motif}

Generate the following as JSON with exactly these keys:

{{
  "tagline": "...",
  "cta": "...",
  "product_name": "...",
  "background_prompt_stage1": "...",
  "background_prompt_stage2": "...",
  "background_prompt_billboard": "..."
}}

Rules:
- tagline: In {locale_lang}. ≤{tagline_limit} characters, ≤6 words. Bold and direct. Culturally native — NOT a literal translation. Avoid clichés. No line breaks.
- cta: In {locale_lang}. ≤{cta_limit} characters, ≤4 words. Action-oriented. Clear and concise. No line breaks.
- product_name: Display name for this product in {locale_lang}. ≤50 characters.
- background_prompt_stage1: In English. A detailed image generation prompt for placing the {model_name} instrument into this scene: "{effective_scene}". Include: instrument positioned naturally in the scene, lighting, atmosphere, and mood. Style: cinematic product photography. Do NOT mention text overlays or UI elements.
- background_prompt_stage2: In English. A short video motion prompt for animating the stage1 image. Emphasize SUBTLE motion only: slow push-in, gentle drift, barely perceptible camera movement. Duration: 6-8 seconds. Scene: {effective_scene}.
- background_prompt_billboard: In English. An image generation prompt for creating an ABSTRACT ATMOSPHERIC TEXTURE inspired by this scene: "{effective_scene}". This will be generated using the 16:9 master image as a style reference. Focus ONLY on color, light, mood, bokeh, and texture — absolutely NO instruments, NO people, NO objects. Keep it painterly and abstract. Examples: "warm amber bokeh lights, jazz club atmospheric glow, soft golden depth, painterly grain texture" or "misty forest bokeh, cool blue-green depth, atmospheric haze, abstract color wash".

Output ONLY valid JSON, no markdown fences."""

    for attempt in range(retries + 1):
        response = model.generate_content(prompt)
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        try:
            copy = json.loads(raw)
        except json.JSONDecodeError as e:
            if attempt < retries:
                continue
            raise ValueError(f"Failed to parse Gemini JSON response: {e}\nRaw: {raw[:200]}")

        # Validate lengths — retry with stricter prompt if exceeded
        tagline_ok = len(copy.get("tagline", "")) <= tagline_limit
        cta_ok = len(copy.get("cta", "")) <= cta_limit

        if tagline_ok and cta_ok:
            return copy

        if attempt < retries:
            print(f"    Retrying copy for {locale['id']}/{model_entry['id']} — length exceeded")
            tl = copy.get("tagline", "")
            ct = copy.get("cta", "")
            prompt += f"\n\nPREVIOUS ATTEMPT FAILED:\nTagline was '{tl}' ({len(tl)} chars) — must be ≤{tagline_limit}.\nCTA was '{ct}' ({len(ct)} chars) — must be ≤{cta_limit}.\nShorten both. Do not exceed the limits."
        else:
            # Truncate as last resort rather than crash
            if not tagline_ok:
                print(f"    WARNING: tagline for {locale['id']}/{model_entry['id']} truncated to {tagline_limit}")
                copy["tagline"] = copy["tagline"][:tagline_limit].rsplit(" ", 1)[0]
            if not cta_ok:
                print(f"    WARNING: cta for {locale['id']}/{model_entry['id']} truncated to {cta_limit}")
                copy["cta"] = copy["cta"][:cta_limit].rsplit(" ", 1)[0]

    return copy


def run(cfg: dict, dry_run: bool = False):
    brief_path = DATA / "campaign_brief.json"
    if not brief_path.exists():
        raise FileNotFoundError("campaign_brief.json not found — run Step 1 first")

    brief = json.loads(brief_path.read_text())

    if dry_run:
        products = brief["products"]
        locales = brief["locales"]
        total = sum(
            len(p["models"]) * sum(len(m["variants"]) for m in p["models"]) * len(locales)
            for p in products
        )
        print(f"  [DRY RUN] Would generate copy for ~{total} variant/locale combinations")
        return

    gemini = _gemini_client()
    manifest = {"variants": []}

    locales = brief["locales"]
    char_limits = brief.get("character_limits", {})

    for product in brief["products"]:
        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                variant_key = f"{product['id']}_{model_entry['id']}_{variant['id']}"
                locale_copies = {}

                for locale in locales:
                    print(f"  Generating copy: {variant_key} / {locale['id']}")
                    try:
                        copy = generate_copy_for_variant(
                            gemini, product, model_entry, variant, locale, char_limits
                        )
                        locale_copies[locale["id"]] = copy
                    except Exception as e:
                        print(f"  ERROR generating copy for {variant_key}/{locale['id']}: {e}")
                        locale_copies[locale["id"]] = {
                            "tagline": product["key_message"],
                            "cta": "Learn More",
                            "product_name": model_entry["name"],
                            "background_prompt_stage1": product["creative_direction"]["scene"],
                            "background_prompt_stage2": "Slow subtle push-in camera movement, 6 seconds.",
                            "background_prompt_billboard": f"Abstract atmospheric texture. {product['creative_direction']['vibe']}. Warm cinematic bokeh, painterly depth, no objects or people.",
                        }

                manifest["variants"].append({
                    "product_id": product["id"],
                    "model_id": model_entry["id"],
                    "variant_id": variant["id"],
                    "locales": locale_copies,
                })

    (DATA / "copy_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"  Saved copy_manifest.json — {len(manifest['variants'])} variants")
