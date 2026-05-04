"""
Step 1: Parse the campaign brief PDF and uploaded assets.

- Reads brief PDF via Gemini 3.1 Pro → produces campaign_brief.json
- Uses Gemini Vision to describe each uploaded asset image
- Auto-matches asset images to brief products by description similarity
- Saves asset_manifest.json
"""
import base64
import json
import os
import re
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from pydantic import ValidationError

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
UPLOADS = ROOT / "uploads"
DATA.mkdir(exist_ok=True)

BRIEF_SCHEMA = """
{
  "campaign_name": "string",
  "client": "string",
  "launch_window": "string",
  "character_limits": {
    "tagline": 40,
    "cta": 25,
    "product_name": 50
  },
  "locales": [
    {
      "id": "en",
      "language": "English",
      "cultural_tone": "string",
      "locale_creative_overrides": {}
    }
  ],
  "products": [
    {
      "id": "saxophone",
      "series": "Yosuki Signature Series Saxophones",
      "key_message": "Own the stage",
      "creative_direction": {
        "scene": "string",
        "vibe": "string",
        "visual_motif": "string"
      },
      "models": [
        {
          "id": "sax1",
          "name": "Yosuki Signature Saxophone",
          "variants": [{"id": "standard", "color": null}],
          "aspect_ratios": ["16x9", "Billboard", "1x1"]
        }
      ]
    }
  ]
}
"""


def _gemini_client():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    return genai.GenerativeModel("gemini-2.0-flash-exp")


def _pdf_to_base64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode()


def parse_brief(model, brief_pdf: Path) -> dict:
    print(f"  Parsing brief: {brief_pdf.name}")
    pdf_data = _pdf_to_base64(brief_pdf)

    prompt = f"""You are a motion graphics pipeline assistant. Extract a complete structured representation
of this campaign brief as JSON. Follow this schema exactly:

{BRIEF_SCHEMA}

Rules:
- locale ids must be lowercase 2-letter codes: en, jp, de, br
- aspect_ratios per model must be a subset of: ["16x9", "Billboard", "1x1"]
  (Saxophone: all 3; Pianos: ["16x9","Billboard"]; Guitars: all 3)
- For locale_creative_overrides, use an empty object {{}} unless the brief specifies locale-specific scene overrides
- Extract all products, models, variants, and creative direction faithfully from the brief
- Output ONLY valid JSON, no markdown fences"""

    response = model.generate_content([
        {"mime_type": "application/pdf", "data": pdf_data},
        prompt,
    ])

    raw = response.text.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def describe_asset(model, image_path: Path) -> str:
    print(f"  Describing asset: {image_path.name}")
    img_data = base64.standard_b64encode(image_path.read_bytes()).decode()
    suffix = image_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"

    response = model.generate_content([
        {"mime_type": mime, "data": img_data},
        "Describe this product image in one sentence. Include: instrument type, finish/color, and any distinctive features. Be specific and concise.",
    ])
    return response.text.strip()


def match_assets(brief: dict, asset_descriptions: dict[str, str]) -> dict:
    """Match uploaded asset filenames to brief products using description similarity."""
    matches = []
    warnings = []

    all_variants = []
    for product in brief["products"]:
        for model_entry in product["models"]:
            for variant in model_entry["variants"]:
                all_variants.append({
                    "product_id": product["id"],
                    "model_id": model_entry["id"],
                    "variant_id": variant["id"],
                    "color": variant.get("color"),
                    "series": product["series"],
                    "model_name": model_entry["name"],
                })

    for filename, description in asset_descriptions.items():
        stem = Path(filename).stem
        best_score = -1
        best_variant = None

        # Score each variant by keyword overlap between description and brief text
        for v in all_variants:
            search_text = f"{v['series']} {v['model_name']} {v.get('color') or ''}".lower()
            desc_lower = description.lower()

            score = 0
            # Check instrument type keywords
            for kw in ["saxophone", "sax", "piano", "guitar"]:
                if kw in desc_lower and kw in search_text:
                    score += 3
            # Check color keywords
            for kw in ["black", "blue", "burst", "gold", "white", "silver"]:
                if kw in desc_lower and kw in search_text:
                    score += 2
            # Filename-based hints (e.g., guitar1-a = black, guitar1-b = blueburst)
            if stem.endswith("-a") and v.get("color") and "black" in v["color"].lower():
                score += 2
            if stem.endswith("-b") and v.get("color") and ("blue" in v["color"].lower() or "burst" in v["color"].lower()):
                score += 2
            # Direct stem match
            if v["model_id"] in stem:
                score += 4

            if score > best_score:
                best_score = score
                best_variant = v

        confidence = min(1.0, best_score / 8.0)
        if best_variant:
            matches.append({
                "asset_filename": filename,
                "asset_stem": stem,
                "product_id": best_variant["product_id"],
                "model_id": best_variant["model_id"],
                "variant_id": best_variant["variant_id"],
                "description": description,
                "match_confidence": round(confidence, 2),
            })
            if confidence < 0.4:
                warnings.append(f"Low-confidence match ({confidence:.0%}): {filename} → {best_variant['model_id']}")
        else:
            warnings.append(f"No match found for: {filename}")

    return {"matches": matches, "warnings": warnings}


def run(cfg: dict, dry_run: bool = False):
    brief_pdf = UPLOADS / "brief.pdf"
    if not brief_pdf.exists():
        # Fall back to the provided client-brief
        brief_pdf = ROOT / "client-brief" / "Brief - Yosuki 2026 Spring Performance.pdf"

    if not brief_pdf.exists():
        raise FileNotFoundError(f"No brief PDF found. Upload one via the dashboard or place it at {brief_pdf}")

    if dry_run:
        print("  [DRY RUN] Would parse brief and match assets")
        return

    gemini = _gemini_client()

    # Parse the brief
    brief = parse_brief(gemini, brief_pdf)
    (DATA / "campaign_brief.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False))
    print(f"  Saved campaign_brief.json — {len(brief['products'])} products, {len(brief['locales'])} locales")

    # Describe uploaded assets
    asset_dir = UPLOADS / "assets"
    if not asset_dir.exists():
        # Fall back to the provided asset bundle
        asset_dir = ROOT / "fde_asset_bundle"

    image_files = list(asset_dir.rglob("*.png")) + list(asset_dir.rglob("*.jpg"))
    glb_files = {f.stem: str(f) for f in asset_dir.rglob("*.glb")}

    asset_descriptions = {}
    for img in image_files:
        try:
            asset_descriptions[img.name] = describe_asset(gemini, img)
        except Exception as e:
            print(f"  Warning: could not describe {img.name}: {e}")
            asset_descriptions[img.name] = img.stem

    # Auto-match assets to products
    manifest = match_assets(brief, asset_descriptions)

    # Enrich matches with GLB paths and full asset paths
    for match in manifest["matches"]:
        stem = match["asset_stem"]
        match["asset_png"] = str(next(
            (f for f in image_files if f.stem == stem), ""
        ))
        match["asset_glb"] = glb_files.get(stem.rstrip("-ab"), "")

    (DATA / "asset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    if manifest["warnings"]:
        for w in manifest["warnings"]:
            print(f"  WARNING: {w}")

    print(f"  Saved asset_manifest.json — {len(manifest['matches'])} asset matches")
