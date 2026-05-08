"""
Step 1: Parse the campaign brief PDF and uploaded assets.

- Reads brief PDF via Gemini Pro → produces campaign_brief.json
- Matches asset images to brief variants by filename keyword overlap (no Vision API calls)
- Uses variant-first matching with fair distribution so every variant gets an image
- Saves asset_manifest.json
"""
import json
import os
import re
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

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
  "copy_constraints": {
    "tagline_max_words": 6,
    "tagline_guidance": "string — tone and style rules for taglines extracted verbatim or closely paraphrased from the brief",
    "localization_guidance": "string — how localized copy should feel: native/fluent, culturally adapted, not literal translation"
  },
  "locales": [
    {
      "id": "en",
      "language": "English",
      "cultural_tone": "string — how copy should feel in this market (e.g. aspirational and bold, respectful and refined)",
      "locale_creative_overrides": {}
    }
  ],
  "products": [
    {
      "id": "product-line-id",
      "series": "Full product series name from brief",
      "key_message": "The single overarching campaign message for this product line",
      "target_personas": "string — who this product is for: demographics (age, lifestyle, role) and psychographics (motivations, values, relationship with music)",
      "messaging_pillars": [
        "Pillar theme 1 (e.g. Stage Ownership)",
        "Pillar theme 2 (e.g. Expressive Power)",
        "Pillar theme 3 (e.g. Urban Prestige)"
      ],
      "creative_direction": {
        "scene": "string — the physical environment and setting for image generation",
        "vibe": "string — the emotional tone and energy of the visual world",
        "visual_motif": "string — recurring visual elements, textures, and compositional devices",
        "copy_style": "string — how copy should feel for this product: bold/terse, poetic/evocative, refined/measured, aggressive/unapologetic, etc.",
        "audience_context": "string — what kind of audience is present in the scene and how they relate to the performer (e.g. patrons at candlelit tables in a jazz club, a formal recital audience, a dense concert crowd)"
      },
      "models": [
        {
          "id": "model-id",
          "name": "Full model name",
          "variants": [{"id": "standard", "color": null}],
          "aspect_ratios": ["1920x1080", "1080x1080", "970x250"]
        }
      ]
    }
  ]
}
"""

# Abbreviation/alias → canonical instrument word used in brief text
_INSTRUMENT_KEYWORDS = {
    "sax":         "saxophone",
    "saxophone":   "saxophone",
    "guitar":      "guitar",
    "guit":        "guitar",
    "piano":       "piano",
    "keyboard":    "piano",
    "keys":        "piano",
    "bass":        "bass",
    "drum":        "drum",
    "violin":      "violin",
    "trumpet":     "trumpet",
    "flute":       "flute",
    "cello":       "cello",
    "ukulele":     "ukulele",
    "uke":         "ukulele",
    "banjo":       "banjo",
    "mandolin":    "mandolin",
    "synth":       "synthesizer",
    "synthesizer": "synthesizer",
    "horn":        "horn",
    "trombone":    "trombone",
    "clarinet":    "clarinet",
    "oboe":        "oboe",
}


_MODEL = "gemini-3.1-pro-preview"

def _gemini_client():
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def parse_brief(client, brief_pdf: Path, enabled_size_ids: list[str]) -> dict:
    print(f"  Parsing brief: {brief_pdf.name}")
    pdf_bytes = brief_pdf.read_bytes()
    size_list = json.dumps(enabled_size_ids)

    prompt = f"""You are a motion graphics pipeline assistant. Your job is to extract a complete, structured
representation of this campaign brief as JSON for use by an automated advertising production pipeline.

Follow this schema exactly:

{BRIEF_SCHEMA}

EXTRACTION GUIDANCE — read the brief carefully for each of the following:

INSTRUMENTS & PRODUCTS
- Identify every instrument family / product line featured in the brief
- For each product line, extract all models (e.g. Grand Piano, Upright, Digital Piano are three models)
- For each model, extract all finish or color variants. If none are specified, create one variant with id "standard" and color null.
- Assign aspect_ratios from the available size IDs: {size_list}. Give all sizes to every model unless the brief explicitly restricts certain products to fewer formats.

TARGET PERSONAS & DEMOGRAPHICS
- For each product line, identify who the target buyer/user is
- Capture age range, lifestyle, relationship with music, motivations, and how they think about the instrument
- This goes in the "target_personas" field — write it as a concise paragraph

TONE & MESSAGING PILLARS
- Extract the key_message (the single overarching campaign line for that product, e.g. "Own the stage")
- Then identify 3–5 messaging pillars — the core emotional themes or brand values that copy should draw from
- These are not taglines — they are thematic territories (e.g. "Stage Ownership", "Expressive Power", "Urban Prestige")
- These go in the "messaging_pillars" array

CREATIVE DIRECTION (per product line)
- scene: the physical setting and environment for image generation
- vibe: the emotional energy and mood
- visual_motif: recurring visual devices, textures, compositional cues
- copy_style: how copy should feel — e.g. "Bold and terse. Short punchy lines. Speak to the performer's confidence." or "Refined and measured. Let quality speak quietly. Avoid hype."
- audience_context: who makes up the audience in this scene and how they relate to the performer — infer from the scene if not stated explicitly (e.g. a jazz club scene implies patrons at tables; a concert hall implies a formal seated audience; an underground warehouse venue implies a dense energetic crowd)

LOCALES & CULTURAL TONE
- Create one locale entry PER LANGUAGE (not per region) — use lowercase ISO 639-1 codes (en, ja, de, pt, es, fr, ko, zh)
- IMPORTANT: if a market lists multiple languages (e.g. "Brazilian Portuguese, Spanish"), create a SEPARATE locale entry for EACH
- For cultural_tone: describe how copy should feel in that specific cultural context, not just the language
- For locale_creative_overrides: use {{}} unless the brief specifies locale-specific scene changes

COPY CONSTRAINTS
- character_limits: extract tagline, CTA, and product_name character limits from the brief
- If not specified in the brief, use defaults: tagline 40, cta 25, product_name 50
- copy_constraints.tagline_max_words: extract the word count limit for taglines (default 6 if not specified)
- copy_constraints.tagline_guidance: extract any stated rules about tagline tone, style, or construction (bold/direct, avoid clichés, adaptable across languages, etc.)
- copy_constraints.localization_guidance: extract any stated rules about how localized copy should feel (native/fluent, not machine-translated, culturally adapted, etc.)

Output ONLY valid JSON, no markdown fences."""

    response = client.models.generate_content(
        model=_MODEL,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ],
    )

    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def _stem_words(text: str) -> set[str]:
    return {w for w in re.split(r'[\s\-_\.]+', text.lower()) if len(w) > 2}


def _score_image_for_variant(img: Path, variant: dict) -> int:
    """Score how well an image filename matches a brief variant. Higher = better match."""
    stem_lower = img.stem.lower()
    score = 0

    # Collect all searchable words from brief text for this variant
    brief_words = (
        _stem_words(variant["series"]) |
        _stem_words(variant["model_name"]) |
        _stem_words(variant["model_id"]) |
        _stem_words(variant.get("color") or "")
    )

    # Expand instrument abbreviations based on what the brief says
    all_brief_text = f"{variant['series']} {variant['model_name']}".lower()
    for abbrev, instrument in _INSTRUMENT_KEYWORDS.items():
        if instrument in all_brief_text or abbrev in all_brief_text:
            brief_words.add(abbrev)
            brief_words.add(instrument)

    # Instrument keyword match: a recognised instrument word appears in the filename
    # These get a high score because they're a strong semantic signal
    for word in brief_words:
        if word in _INSTRUMENT_KEYWORDS or word in _INSTRUMENT_KEYWORDS.values():
            if word in stem_lower:
                score += 8  # high weight for instrument-type match
                break  # count the instrument type once

    # General keyword overlap (model name, series words, etc.)
    for word in brief_words:
        if word in _INSTRUMENT_KEYWORDS or word in _INSTRUMENT_KEYWORDS.values():
            continue  # already handled above
        if word in stem_lower:
            score += 5 if len(word) >= 5 else 3

    # Strongest signal: full model_id slug in filename
    if variant["model_id"].lower() in stem_lower:
        score += 10

    # Color in filename
    if variant.get("color") and variant["color"].lower() in stem_lower:
        score += 4

    # Variant id in filename (ignore "standard" — too generic)
    v_id = variant.get("variant_id", "")
    if v_id and v_id.lower() not in ("standard", "") and v_id.lower() in stem_lower:
        score += 4

    return score


def match_assets_by_filename(brief: dict, image_files: list) -> dict:
    """
    Variant-first matching: for each product variant in the brief, find the
    best-matching image. Multiple variants may share one image (e.g. color
    variants). Images are distributed fairly — when variants tie on score,
    less-used images are preferred, spreading piano1/piano2/piano3 across the
    three piano models instead of all going to one.

    No Vision API calls — relies on descriptive filenames (sax1.png, piano2.png, guitar1-a.png).
    """
    matches = []
    warnings = []

    if not image_files:
        return {"matches": [], "warnings": ["No image files found in asset folder"]}

    # Build flat variant list preserving brief order
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

    # Track usage count per image stem for fair distribution
    usage: dict[str, int] = {img.stem: 0 for img in image_files}

    for v in all_variants:
        # Score every image for this variant
        scored = [(
            _score_image_for_variant(img, v),
            img.stem,
            img,
        ) for img in image_files]

        # Skip images that scored 0 (no meaningful match at all)
        scored = [(s, st, img) for s, st, img in scored if s > 0]

        if not scored:
            warnings.append(f"No matching image for: {v['model_id']}/{v['variant_id']}")
            continue

        # Sort: best score first; among ties, prefer least-used image (fair distribution)
        scored.sort(key=lambda x: (-x[0], usage.get(x[1], 0), x[1]))

        best_score, best_stem, best_img = scored[0]
        usage[best_stem] = usage.get(best_stem, 0) + 1

        confidence = min(1.0, best_score / 12.0)
        matches.append({
            "asset_filename": best_img.name,
            "asset_stem": best_img.stem,
            "product_id": v["product_id"],
            "model_id": v["model_id"],
            "variant_id": v["variant_id"],
            "description": f"Filename-matched: {best_img.name}",
            "match_confidence": round(confidence, 2),
        })
        if confidence < 0.3:
            warnings.append(
                f"Low-confidence match ({confidence:.0%}): {best_img.name} → {v['model_id']}"
            )

    return {"matches": matches, "warnings": warnings}


def run(cfg: dict, dry_run: bool = False):
    brief_pdf = UPLOADS / "brief.pdf"
    if not brief_pdf.exists():
        client_brief_dir = ROOT / "client-brief"
        pdfs = list(client_brief_dir.glob("*.pdf")) if client_brief_dir.exists() else []
        if pdfs:
            brief_pdf = sorted(pdfs)[0]

    if not brief_pdf.exists():
        raise FileNotFoundError(
            "No brief PDF found. Upload one via the dashboard, or place a PDF in the client-brief/ folder."
        )

    if dry_run:
        print("  [DRY RUN] Would parse brief and match assets")
        return

    enabled_size_ids = [s["id"] for s in cfg.get("sizes", []) if s.get("enabled", True)]
    if not enabled_size_ids:
        enabled_size_ids = ["1920x1080", "1080x1080", "970x250"]

    gemini = _gemini_client()

    # Parse the brief (1 API call)
    brief = parse_brief(gemini, brief_pdf, enabled_size_ids)  # client passed as first arg
    (DATA / "campaign_brief.json").write_text(
        json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Saved campaign_brief.json — {len(brief['products'])} products, {len(brief['locales'])} locales")

    # Locate asset images
    asset_dir = UPLOADS / "assets"
    if not asset_dir.exists():
        assets_folder = cfg.get("assets_folder", "./fde_asset_bundle")
        asset_dir = (
            Path(assets_folder) if Path(assets_folder).is_absolute()
            else (ROOT / assets_folder).resolve()
        )

    image_files = list(asset_dir.rglob("*.png")) + list(asset_dir.rglob("*.jpg"))
    glb_files = {f.stem: str(f) for f in asset_dir.rglob("*.glb")}

    print(f"  Found {len(image_files)} image assets — matching by filename (no Vision API calls)")

    # Variant-first filename matching
    manifest = match_assets_by_filename(brief, image_files)

    # Unmatched images: log as informational only
    matched_filenames = {m["asset_filename"] for m in manifest["matches"]}
    for img in image_files:
        if img.name not in matched_filenames:
            print(f"  INFO: {img.name} — not matched to any brief variant (e.g. logo)")

    # Enrich matches with full file paths and GLB paths
    image_by_stem = {f.stem: f for f in image_files}
    for match in manifest["matches"]:
        stem = match["asset_stem"]
        img_path = image_by_stem.get(stem)
        match["asset_png"] = str(img_path) if img_path else ""
        match["asset_glb"] = glb_files.get(stem.rstrip("-ab"), "")

    (DATA / "asset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if manifest["warnings"]:
        for w in manifest["warnings"]:
            print(f"  WARNING: {w}")

    print(f"  Saved asset_manifest.json — {len(manifest['matches'])} variant→asset mappings")
