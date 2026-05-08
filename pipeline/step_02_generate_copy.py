"""
Step 2: Generate all per-locale copy using Gemini Pro.

Batches all variants into a single API call per locale, instead of one call
per variant × locale. For 10 variants × 4 locales this is 4 calls vs 40.

For each product variant × locale, produces:
  - tagline (≤40 chars, ≤6 words, driven by messaging pillars — key_message + vibe)
  - cta (≤25 chars, ≤4 words, drives traffic to e-commerce partners or regional distributors)
  - product_name (display name for that locale)
  - background_prompt_stage1 (scene/mood for image gen — no instrument/performer description)
  - background_prompt_stage2 (subtle motion direction for video models)

Saves copy_manifest.json.
"""
import json
import os
import re
from pathlib import Path

from google import genai
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"

# Languages with long compound words — apply a tighter character limit factor
_LONG_WORD_LOCALES = {"de", "fi", "nl", "sv", "no", "da"}


_MODEL = "gemini-3.1-pro-preview"

def _gemini_client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


_TAGLINE_MAX_WORDS = 6  # hardcoded — brief requirement, not configurable per run


def _char_limits(brief: dict, locale_id: str) -> tuple[int, int]:
    """Returns (tagline_char_limit, cta_char_limit)."""
    char_limits = brief.get("character_limits", {})
    base_tagline = char_limits.get("tagline", 40)
    base_cta = char_limits.get("cta", 25)
    factor = 0.80 if locale_id in _LONG_WORD_LOCALES else 1.0
    return int(base_tagline * factor), int(base_cta * factor)


def _effective_scene(product: dict, locale: dict) -> str:
    overrides = locale.get("locale_creative_overrides", {})
    override = overrides.get(product["id"], {}).get("scene_override")
    return override if override else product["creative_direction"]["scene"]


def generate_copy_for_locale_batch(
    client, brief: dict, products: list, locale: dict, retries: int = 2
) -> dict[str, dict]:
    """
    Generate copy for ALL variants in one locale with a single Gemini API call.
    Returns dict keyed by "product_id|model_id|variant_id".
    """
    tagline_limit, cta_limit = _char_limits(brief, locale["id"])
    tagline_word_limit = _TAGLINE_MAX_WORDS
    locale_lang = locale["language"]
    locale_tone = locale["cultural_tone"]
    copy_constraints = brief.get("copy_constraints", {})
    tagline_guidance = copy_constraints.get("tagline_guidance", "")
    localization_guidance = copy_constraints.get("localization_guidance", "")
    # CJK and other scripts don't split on spaces — use character limit only for word counting
    _space_separated = locale["id"] not in {"ja", "zh", "ko", "th", "my", "km"}

    # Build the list of all variant combinations
    combinations = []
    for product in products:
        scene = _effective_scene(product, locale)
        cd = product["creative_direction"]
        key_message = product["key_message"]
        series_name = product["series"]
        messaging_pillars = product.get("messaging_pillars", [])
        copy_style = cd.get("copy_style", "")
        target_personas = product.get("target_personas", "")
        audience_context = cd.get("audience_context", "")

        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                color_note = f" (color: {variant['color']})" if variant.get("color") else ""
                key = f"{product['id']}|{model_entry['id']}|{variant['id']}"
                combinations.append({
                    "key": key,
                    "product_name": f"{model_entry['name']}{color_note}",
                    "series": series_name,
                    "key_message": key_message,
                    "messaging_pillars": messaging_pillars,
                    "copy_style": copy_style,
                    "target_personas": target_personas,
                    "scene": scene,
                    "vibe": cd["vibe"],
                    "audience_context": audience_context,
                })

    def _pillars_str(pillars: list) -> str:
        return ", ".join(pillars) if pillars else "(see key message and vibe)"

    combo_block = "\n\n".join(
        f'KEY: {c["key"]}\n'
        f'MESSAGING PILLARS (drive tagline & CTA):\n'
        f'  Key message: "{c["key_message"]}"\n'
        f'  Pillars: {_pillars_str(c["messaging_pillars"])}\n'
        f'  Vibe: {c["vibe"]}\n'
        f'  Copy style: {c["copy_style"]}\n'
        f'  Target audience: {c["target_personas"]}\n'
        f'CREATIVE CONTEXT (for background prompts only — do NOT use for tagline/CTA):\n'
        f'  Product display name: {c["product_name"]}\n'
        f'  Scene: {c["scene"]}\n'
        f'  Audience in scene: {c["audience_context"]}'
        for c in combinations
    )

    prompt = f"""You are a creative copywriter for a motion graphics advertising campaign.
Target language: {locale_lang}
Cultural tone: {locale_tone}
Localization rule: {localization_guidance}

Generate copy for ALL {len(combinations)} product/variant combinations below.
Return a single JSON object where each key matches the KEY field, and each value has:
{{
  "tagline": "...",
  "cta": "...",
  "product_name": "...",
  "background_prompt_stage1": "..."
}}

Rules (apply to ALL entries):
- tagline: HARD LIMITS — maximum {tagline_word_limit} words AND maximum {tagline_limit} characters. Count the words explicitly before writing your answer. {tagline_word_limit} words means {tagline_word_limit} words — not {tagline_word_limit + 1} or {tagline_word_limit + 2}. {tagline_guidance} Write original, emotionally resonant copy inspired by the MESSAGING PILLARS. Do NOT restate the key message verbatim — interpret it creatively. Copy must feel native and fluent in {locale_lang} — culturally adapted, not translated. No line breaks.
- cta: Write a short, action-oriented CTA in {locale_lang}. Campaign goal: drive product consideration and direct audiences to local e-commerce partners or regional distributors. Choose the most compelling call to action for the locale and product context — appropriate intents include "Find a Dealer", "Shop Online", "Buy Now", "Shop Local", "Get Yours", "Find a Store", "Explore Now", or a culturally equivalent phrase. Adapt naturally for {locale_lang} culture and market — do not simply translate "Shop Now". HARD LIMIT: ≤{cta_limit} characters, ≤4 words. No line breaks.
- product_name: Display name for this product in {locale_lang}. ≤50 characters. Use the provided product display name as reference.
- background_prompt_stage1: In English. Describe the scene, environment, mood, and lighting for this product's campaign — the WHERE and the FEEL. Include: the venue or setting, atmospheric depth, dramatic lighting direction (rim light, backlight, spotlighting), mood, color palette, environmental details. Also describe the audience visible in the background — use the "Audience in scene" field as your reference for who they are and how they relate to the performer (e.g. patrons at tables, theatre audience, packed concert crowd). The audience must always be present. CRITICAL COMPOSITION: the subject MUST be positioned on the RIGHT side of the frame — the LEFT side must be noticeably darker and relatively empty to serve as text overlay space. Do NOT describe the instrument or the performer — those are provided separately. Do NOT include camera or lens technical specifications. No text, no UI elements.

PRODUCT COMBINATIONS:

{combo_block}

Output ONLY valid JSON, no markdown fences. Every KEY must appear in the output."""

    for attempt in range(retries + 1):
        response = client.models.generate_content(
            model=_MODEL, contents=[prompt],
            config=genai.types.GenerateContentConfig(temperature=0.7))
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            if attempt < retries:
                print(f"    Retrying batch for locale '{locale['id']}' — JSON parse error: {e}")
                continue
            # Fall through to individual generation below
            print(f"    WARNING: batch parse failed for locale '{locale['id']}', falling back to individual calls")
            return _generate_copy_individually(client, brief, products, locale)

        # Validate character limits AND word count — collect violating keys
        # Word count only applies to space-separated scripts (skip CJK etc.)
        violations = []
        for key, copy in result.items():
            tl = copy.get("tagline", "")
            ct = copy.get("cta", "")
            tl_words = len(tl.split()) if _space_separated else 0
            char_fail = len(tl) > tagline_limit or len(ct) > cta_limit
            word_fail = _space_separated and tl_words > tagline_word_limit
            if char_fail or word_fail:
                violations.append((key, tl, ct, tl_words))

        if not violations:
            return result

        if attempt < retries:
            violation_notes = "\n".join(
                f'- KEY {k}: tagline "{tl}" ({len(tl)} chars / {wc} words, '
                f'limits: {tagline_limit} chars / {tagline_word_limit} words), '
                f'cta "{ct}" ({len(ct)} chars, limit {cta_limit})'
                for k, tl, ct, wc in violations
            )
            print(f"    Retrying batch for locale '{locale['id']}' — {len(violations)} violations (chars/words)")
            prompt += (
                f"\n\nPREVIOUS ATTEMPT HAD VIOLATIONS — fix these:\n{violation_notes}\n"
                f"HARD LIMITS: taglines ≤{tagline_word_limit} words AND ≤{tagline_limit} chars. "
                f"Count words explicitly. CTAs ≤{cta_limit} chars. Output full JSON again."
            )
        else:
            # Truncate violating entries as last resort — enforce word limit first, then chars
            for key, tl, ct, tl_words in violations:
                if tl_words > tagline_word_limit:
                    tl = " ".join(tl.split()[:tagline_word_limit])
                    result[key]["tagline"] = tl
                    print(f"    WARNING: tagline word-truncated for {key}")
                if len(tl) > tagline_limit:
                    result[key]["tagline"] = tl[:tagline_limit].rsplit(" ", 1)[0]
                    print(f"    WARNING: tagline char-truncated for {key}")
                if len(ct) > cta_limit:
                    result[key]["cta"] = ct[:cta_limit].rsplit(" ", 1)[0]
                    print(f"    WARNING: cta truncated for {key}")

    return result


def _generate_copy_individually(client, brief: dict, products: list, locale: dict) -> dict[str, dict]:
    """Fallback: generate copy one variant at a time (used if batch fails to parse)."""
    tagline_limit, cta_limit = _char_limits(brief, locale["id"])
    tagline_word_limit = _TAGLINE_MAX_WORDS
    locale_lang = locale["language"]
    locale_tone = locale["cultural_tone"]
    copy_constraints = brief.get("copy_constraints", {})
    tagline_guidance = copy_constraints.get("tagline_guidance", "")
    result = {}

    for product in products:
        scene = _effective_scene(product, locale)
        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                key = f"{product['id']}|{model_entry['id']}|{variant['id']}"
                color_note = f" (color variant: {variant['color']})" if variant.get("color") else ""

                prompt = f"""You are a creative copywriter for a motion graphics advertising campaign.

MESSAGING PILLARS (drive tagline & CTA):
  Key message: "{product['key_message']}"
  Vibe: {product['creative_direction']['vibe']}
CREATIVE CONTEXT:
  Product display name: {model_entry['name']}{color_note}
  Scene: {scene}
Target language: {locale_lang}
Cultural tone: {locale_tone}

Generate JSON with exactly these keys:
{{"tagline": "...", "cta": "...", "product_name": "...",
  "background_prompt_stage1": "..."}}

Rules:
- tagline: HARD LIMITS — maximum {tagline_word_limit} words AND maximum {tagline_limit} characters. Count the words before finalizing. {tagline_guidance} Write original emotionally resonant copy from the MESSAGING PILLARS. Do NOT restate the key message verbatim. Must feel native in {locale_lang} — not translated.
- cta: Write a short, action-oriented CTA in {locale_lang}. Campaign goal: drive product consideration and direct audiences to local e-commerce partners or regional distributors. Choose the most compelling call to action for the locale and product context — appropriate intents include "Find a Dealer", "Shop Online", "Buy Now", "Shop Local", "Get Yours", "Find a Store", "Explore Now", or a culturally equivalent phrase. Adapt naturally for {locale_lang} culture and market. HARD LIMIT: ≤{cta_limit} characters, ≤4 words. No line breaks.
- product_name: Display name in {locale_lang}. ≤50 chars.
- background_prompt_stage1: English. Scene, environment, mood, lighting only — the WHERE and the FEEL. Subject on the RIGHT, left side dark and empty for text. Dramatic lighting, atmospheric depth. No instrument description, no performer description, no camera specs, no UI elements.

Output ONLY valid JSON, no markdown fences."""

                space_sep = locale["id"] not in {"ja", "zh", "ko", "th", "my", "km"}
                try:
                    response = client.models.generate_content(
                        model=_MODEL, contents=[prompt],
                        config=genai.types.GenerateContentConfig(temperature=0.7))
                    raw = response.text.strip()
                    raw = re.sub(r"^```(?:json)?\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw)
                    copy = json.loads(raw)
                    # Enforce limits — truncate as last resort
                    tl = copy.get("tagline", "")
                    ct = copy.get("cta", "")
                    if space_sep and len(tl.split()) > tagline_word_limit:
                        tl = " ".join(tl.split()[:tagline_word_limit])
                        copy["tagline"] = tl
                        print(f"    WARNING: tagline word-truncated for {key}")
                    if len(tl) > tagline_limit:
                        copy["tagline"] = tl[:tagline_limit].rsplit(" ", 1)[0]
                        print(f"    WARNING: tagline char-truncated for {key}")
                    if len(ct) > cta_limit:
                        copy["cta"] = ct[:cta_limit].rsplit(" ", 1)[0]
                        print(f"    WARNING: cta truncated for {key}")
                    result[key] = copy
                except Exception as e:
                    print(f"    ERROR generating copy for {key}/{locale['id']}: {e}")
                    result[key] = {
                        "tagline": product["key_message"],
                        "cta": "Learn More",
                        "product_name": model_entry["name"],
                        "background_prompt_stage1": scene,
                    }

    return result


def run(cfg: dict, dry_run: bool = False, preview: bool = False, preview_locale: str = "en"):
    brief_path = DATA / "campaign_brief.json"
    if not brief_path.exists():
        raise FileNotFoundError("campaign_brief.json not found — run Step 1 first")

    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    products = brief["products"]
    locales = brief["locales"]

    if preview:
        matched = [l for l in locales if l["id"] == preview_locale]
        locales = matched if matched else locales[:1]
        print(f"  Preview mode: generating copy for locale '{locales[0]['id']}' only")

    if dry_run:
        total = sum(
            len(p["models"]) * sum(len(m["variants"]) for m in p["models"])
            for p in products
        ) * len(locales)
        print(f"  [DRY RUN] Would generate copy for ~{total} variant/locale combinations")
        return

    client = _gemini_client()
    manifest = {"variants": []}

    # Build lookup keyed by "product_id|model_id|variant_id" → locale_id → copy
    locale_results: dict[str, dict[str, dict]] = {}

    for locale in locales:
        print(f"  Generating copy for locale '{locale['id']}' (batch) …")
        try:
            batch = generate_copy_for_locale_batch(client, brief, products, locale)
            for key, copy in batch.items():
                locale_results.setdefault(key, {})[locale["id"]] = copy
        except Exception as e:
            print(f"  ERROR in batch for locale '{locale['id']}': {e}")
            # Fallback errors → empty copy per variant
            for product in products:
                for model_entry in product["models"]:
                    for variant in model_entry["variants"]:
                        key = f"{product['id']}|{model_entry['id']}|{variant['id']}"
                        locale_results.setdefault(key, {})[locale["id"]] = {
                            "tagline": product["key_message"],
                            "cta": "Learn More",
                            "product_name": model_entry["name"],
                            "background_prompt_stage1": product["creative_direction"]["scene"],
                        }

    # Assemble manifest
    for product in products:
        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                key = f"{product['id']}|{model_entry['id']}|{variant['id']}"
                manifest["variants"].append({
                    "product_id": product["id"],
                    "model_id": model_entry["id"],
                    "variant_id": variant["id"],
                    "locales": locale_results.get(key, {}),
                })

    (DATA / "copy_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Saved copy_manifest.json — {len(manifest['variants'])} variants across {len(locales)} locale(s)")
