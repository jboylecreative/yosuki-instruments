# Yosuki Motion Graphics Pipeline — Full Reference

## What This Project Is

Adobe FDE (Front Door Engineer) take-home assessment for a Motion Graphics Creative Technologist role at Adobe. Build an automated motion graphics pipeline for Yosuki Musical Instrument Corporation's "Find Your Sound" 2026 Spring Performance campaign.

**Working directory:** `c:\Users\HyperrealLabs\Desktop\Adobe_FDE_Assignment\`

**Deliverables required:**
- Public GitHub repo
- Narrated demo video of the pipeline running end-to-end
- 20–30 min walkthrough with 2 Adobe team members if it passes

---

## The Brief (What the Client Needs)

**Client:** Yosuki Musical Instrument Corporation (fictional Japanese instrument brand)
**Campaign:** "Find Your Sound" — Spring 2026 Performance campaign

**Products & Variants:**
- Yosuki Signature Saxophone — 1 model, no color variants
- Yosuki Savant Series Pianos — 3 models: Digital Piano, Upright, Grand Piano
- Yosuki Apex Series Guitars — 3 models × 2 colors (Black, Blue-burst): San Jose (SJ), Paulie, Super Stratoblaster

**Locales:**
- JP (Japanese) — Respectful, refined, craftsmanship-focused
- EN / NAMER (English) — Aspirational, bold, expressive
- DE (German) — Precision, engineering excellence, serious
- BR (Brazilian Portuguese + Spanish) — Emotional, energetic, expressive

**Key Messages:**
- Saxophone: "Own the stage"
- Pianos: "Crafted for Generations"
- Guitars: "Play Loud"

**Ad formats per product:**
- Saxophone: Billboard 970×250, YouTube 16:9, Instagram 1:1 (3 formats)
- Pianos: Billboard 970×250, YouTube 16:9 (2 formats)
- Guitars: Billboard 970×250, YouTube 16:9, Instagram 1:1 (3 formats)

**Creative direction per product:**
- **Saxophone:** Intimate jazz club, warm golden lighting, haze/smoke, spotlighted performer. Vibe: Confident, Expressive. Motifs: stage lights, velvet curtains, brass/chrome reflections.
- **Pianos:** Elegant living room or grand hall, natural daylight, marble/wood/glass textures. Vibe: Refined, Timeless, Prestige. Motifs: soft shadows, slow camera movement, close-up keys.
- **Guitars:** Industrial warehouse, concrete walls, neon accents, high contrast. Vibe: Raw, Energetic, Rebellious. Motifs: motion blur, amplifier stacks, crowd silhouettes.

**Animation structure (per brief):**
1. 0–2s: Scene draws in audience attention
2. 2–4s: Tagline + product name tween in
3. 4–6s: Text fades out, scene transitions
4. 6–8s: Logo + CTA hold as final state

**Copy constraints:**
- Taglines: ≤6 words, ≤40 chars, bold/direct, culturally adapted (not literal translation)
- CTA: ≤4 words, ≤25 chars, action-oriented
- German needs tighter limits due to compound words
- No line breaks in copy

---

## Provided Asset Bundle (`fde_asset_bundle/`)

```
logo.png
guitars/
  guitar1.glb, guitar1-a.png (Black), guitar1-b.png (Blue-burst)   ← San Jose
  guitar2.glb, guitar2-a.png (Black), guitar2-b.png (Blue-burst)   ← Paulie
  guitar3.glb, guitar3-a.png (Black), guitar3-b.png (Blue-burst)   ← Super Stratoblaster
pianos/
  piano1.glb, piano1.png    ← Digital Piano
  piano2.glb, piano2.png    ← Upright
  piano3.glb, piano3.png    ← Grand Piano
saxophone/
  sax1.glb, sax1.png
```

No After Effects template was provided — must be created from scratch.

---

## Architecture Overview

### Two After Effects Files

**1. Master Template** (`templates/yosuki_master_template.aep`)
- Created ONCE manually in After Effects by the creative team
- Contains 3 named compositions: `Billboard_970x250`, `YouTube_1920x1080`, `Instagram_1080x1080`
- Generic named placeholder layers (see layer structure below)
- Polished animation keyframes — the creative team iterates here during test phase
- NEVER modified by the pipeline — only READ
- Source of truth: edit this → re-render → changes propagate to all variants

**2. Output Project** (`output/{run_id}/yosuki_output_{run_id}.aep`)
- Built programmatically by the pipeline via ExtendScript
- Contains one named composition per variant (e.g., `EN_sax1_16x9_001`)
- All assets and text already swapped into each comp — fully prepped, immediately renderable
- Delivered to Google Drive alongside final MP4s
- Creatives open this to find any comp, make targeted edits, re-render just that comp in AE

### AE Template Layer Structure

Both master and output project comps use ONLY these named layers:

| Layer Name | Type | Content |
|---|---|---|
| `BG_MEDIA` | Footage | Stage 2 video (instrument already embedded in scene) |
| `TEXT_TAGLINE` | Text | Locale-adapted tagline |
| `TEXT_PRODUCT_NAME` | Text | Product/series name |
| `TEXT_CTA` | Text | Call to action |
| `LOGO` | Footage | Client logo (logo.png) |

**NO PRODUCT_IMG LAYER.** The instrument is baked into the generated video via Stage 1 AI generation. No duplication of the instrument in the scene.

### Rendering Stack

nexrender + aerender (NOT Adobe Media Encoder):
- nexrender is an open-source Node.js tool that orchestrates batch AE rendering
- aerender = Adobe After Effects' own built-in command-line renderer
- Workflow: nexrender → processes named comps in output AEP → calls aerender → MP4 output files
- Output format (H.264 MP4) set by the Output Module template inside the AEP

---

## Generation Workflow (Two Stages)

### Stage 1 — Product-in-Scene Image Synthesis

**Input:** product PNG (as image reference) + scene prompt (Gemini-generated)

**Primary model:** Nano Banana Pro (via fal.ai) — always runs

**Optional alt models (all via fal.ai):** Flux 2 Pro, GPT Image 2, Seedream 5

**What happens:** Product PNG is used as visual reference. The model places the instrument INTO the generated environment (jazz club, concert hall, warehouse). Output is a composite — instrument embedded in scene.

**Resolution:** 2× target output resolution (see Aspect Ratio table)

**Output path:** `generated/backgrounds/{product_variant_slug}/{aspect_ratio}/stage1/{img_model}/gen_{i:03d}.png`

### Stage 2 — Video Animation

**Input:** Stage 1 composite image (as starting frame) + motion prompt (Gemini-generated)

**Models (all via fal.ai):** Kling, Veo 3.1, HappyHorse, Seedance 2.0, Hailuo 2.3

**What happens:** Stage 1 image is animated into a 6-8s video clip. Motion is ALWAYS subtle — slow push-in, gentle drift, barely perceptible zoom. Gemini generates the motion prompt with emphasis on restraint.

**Output path:** `generated/backgrounds/{product_variant_slug}/{aspect_ratio}/stage2/{vid_model}/gen_{i:03d}.mp4`

### Aspect Ratio & Framing

| Format | Target | Generate At | AE Framing | Prompt Note |
|---|---|---|---|---|
| Billboard 970×250 | 3.88:1 | 16:9 @ 3840×2160 | Crop vertical center band | "wide cinematic horizontal, subject centered, breathing room above/below" |
| YouTube 16:9 | 16:9 | 3840×2160 | Full frame | Standard cinematic |
| Instagram 1:1 | 1:1 | 2160×2160 | Full frame | Square-safe, subject centered |

---

## Output Scale

Base: 108 renders (one per variant/locale/aspect ratio, one model). With N video models enabled: 108 × N renders.

| Product | Variants × Locales × Aspect Ratios | Base | All 5 Models |
|---|---|---|---|
| Saxophone | 1×4×3 | 12 | 60 |
| Pianos | 3×4×2 | 24 | 120 |
| Guitars | 6×4×3 | 72 | 360 |
| **Total** | | **108** | **540** |

Output scale is gated by the Preview & Select step before the full batch run.

---

## Output Naming Convention

```
{LOCALE}_{source_asset_name}_{AspectRatio}_{NNN}.mp4
```

- `LOCALE`: EN, JP, DE, BR
- `source_asset_name`: asset filename without extension (e.g., `sax1`, `guitar1-a`, `piano2`)
- `AspectRatio`: `16x9`, `Billboard`, `1x1`
- `NNN`: zero-padded sequential number (001, 002...) — increments per additional model/generation

Examples:
```
EN_sax1_16x9_001.mp4
JP_guitar1-a_Billboard_001.mp4
DE_piano2_16x9_002.mp4
BR_guitar3-b_1x1_001.mp4
```

Comp names in the output AEP exactly match filenames (minus .mp4).

---

## Tech Stack

| Layer | Tool |
|---|---|
| Web Dashboard | FastAPI + Jinja2 HTML + SSE (Server-Sent Events) for live progress |
| LLM + Vision | Google Gemini 3.1 Pro (`gemini-3.1-pro-preview`) — LLM and Vision ONLY |
| ALL AI Generation | fal.ai — ALL image and video models go through fal.ai |
| Schema Validation | Pydantic v2 |
| Output AEP Building | ExtendScript (.jsx) run via `aerender -script` |
| Batch Rendering | nexrender (`@nexrender/cli`) + Adobe aerender |
| Output Tracking | Google Sheets API |
| Delivery | Google Drive API (deferred — tested last) |
| Env Management | python-dotenv |

**API Keys (only 2 needed):**
- `GEMINI_API_KEY` — Gemini 3.1 Pro (LLM + Vision for asset description matching)
- `FAL_KEY` — ALL generation (Nano Banana Pro, Flux 2 Pro, GPT Image 2, Seedream 5, Kling, Veo 3.1, HappyHorse, Seedance 2.0, Hailuo 2.3)

No OpenAI API key. GPT Image 2, Nano Banana Pro, and Veo 3.1 are all accessed via fal.ai.

---

## `config.json` Structure

```json
{
  "stage1_image_models": [
    { "id": "nano-banana-pro", "fal_path": "fal-ai/nano-banana-pro",  "enabled": true,  "primary": true },
    { "id": "flux-2-pro",      "fal_path": "fal-ai/flux-pro-v2",      "enabled": true,  "primary": false },
    { "id": "gpt-image-2",     "fal_path": "fal-ai/gpt-image-2",      "enabled": true,  "primary": false },
    { "id": "seedream-5",      "fal_path": "fal-ai/seedream-5",       "enabled": true,  "primary": false }
  ],
  "stage2_video_models": [
    { "id": "kling",           "fal_path": "fal-ai/kling-video",      "enabled": true },
    { "id": "veo-3.1",         "fal_path": "fal-ai/veo-3",            "enabled": true },
    { "id": "happyhorse",      "fal_path": "fal-ai/happy-horse",      "enabled": true },
    { "id": "seedance-2",      "fal_path": "fal-ai/seedance-2",       "enabled": true },
    { "id": "hailuo-2.3",      "fal_path": "fal-ai/minimax-video-01", "enabled": true }
  ],
  "generations_per_model": 1,
  "skip_existing": true,
  "aerender_path": "C:/Program Files/Adobe/Adobe After Effects 2025/aerender.exe"
}
```

**IMPORTANT:** Verify all `fal_path` strings against fal.ai docs at build time — model slugs update frequently.

---

## Reusability

**Nothing is hardcoded.** "Saxophone," "guitar," "piano" do not appear in pipeline code. All product info is extracted from the brief via Gemini. Asset-to-product matching is done automatically via Gemini Vision (describes uploaded images, matches to brief product descriptions by similarity).

**To add a new product line:** New brief PDF + new asset folder → same pipeline, no code changes.

---

## Web Dashboard UI Flow

### Ingestion
1. **Upload Brief** — drag-drop PDF → Gemini parses → extracts product list + descriptions
2. **Upload Assets** — folder upload (`webkitdirectory`) or ZIP — batch, not one-at-a-time
3. **Auto-Matching** — Gemini Vision describes assets → auto-maps to products — no manual approval gate (low-confidence = warning only, not blocking)
4. **Configure** — model checkboxes per image/video model (reads config.json)

### Run Phases
1. **Preview & Select** — run all enabled models on ONE test asset (one instrument, one aspect ratio) → side-by-side results → check/uncheck which models to include in full batch
2. **Full Batch** — runs only selected models → N × 108 renders → live progress via SSE
3. **Results Gallery** — grid of render cards with preview + action buttons

### Results Gallery Card Actions (no CLI required)
- **Regenerate** — re-runs that specific variant with same model (new generation)
- **Try Different Model** — dropdown to pick alternate model, re-runs just that variant
- **Re-render in AE** — triggers aerender for that one comp (after AE template edits)

### Dashboard-Level Actions
- **Re-render All** — rebuilds output AEP + re-renders all (Steps 4+5) without regenerating backgrounds — most common after editing master AEP
- **Add Model** — enable a new model, generates only missing files, adds to gallery
- **Export Sheet** — updates/opens Google Sheets delivery matrix

---

## Pipeline Code Files

```
pipeline/
  01_parse_brief.py         Brief PDF → campaign_brief.json + asset_manifest.json
  02_generate_copy.py       Gemini → copy_manifest.json (copy + stage1/2 prompts per locale)
  03_generate_backgrounds.py Stage 1 image → Stage 2 video per enabled model
  04_build_output_aep.py    Runs build_output_aep.jsx → output AEP with all variant comps
  05_render.py              nexrender batch renders from output AEP
  06_tracking_sheet.py      Google Sheets delivery matrix
  07_deliver.py             Google Drive upload (DEFERRED — build structure, test last)

scripts/
  build_output_aep.jsx      ExtendScript: opens master AEP, duplicates comps per variant,
                            swaps BG_MEDIA/TEXT/LOGO, saves as output AEP

templates/
  yosuki_master_template.aep   Created manually in AE (one-time manual step)
  create_template.jsx           ExtendScript to regenerate master template programmatically

app/
  main.py                   FastAPI: ingestion endpoints, pipeline trigger, SSE progress
  templates/dashboard.html  Main UI (ingestion + model toggles + run buttons)
  templates/progress.html   Live progress log + results gallery

run_pipeline.py             CLI orchestrator (also called by web app)
config.json
.env.example                GEMINI_API_KEY, FAL_KEY, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SHEETS_ID
requirements.txt
package.json
```

### Data Files (Generated at Runtime)

```
data/
  campaign_brief.json       Structured extraction of the brief
  asset_manifest.json       Auto-generated product ↔ asset filename mapping
  copy_manifest.json        Per-locale copy: taglines, CTAs, stage1/2 prompts
  render_jobs/              nexrender job JSONs (one per variant comp)

generated/
  backgrounds/
    {product_variant_slug}/{aspect_ratio}/
      stage1/{img_model}/gen_{i:03d}.png   ← instrument-in-scene composite (2× res)
      stage2/{vid_model}/gen_{i:03d}.mp4   ← animated clip (6-8s, subtle motion)

output/
  {run_id}/
    yosuki_output_{run_id}.aep             ← output AEP with all variant comps
    renders/
      {LOCALE}_{asset_name}_{AspectRatio}_{NNN}.mp4
```

---

## Build Sequence (Implementation Order)

1. Scaffolding: folders, requirements.txt, package.json, .env.example, config.json, git init
2. FastAPI app skeleton + ingestion UI (folder upload → parse → auto-match → config screen)
3. Steps 1–2: brief parsing + copy generation → validate JSON
4. Step 3: background generation — test one product + one model per stage
5. **Manual AE work**: build master template in After Effects, commit .aep to repo
6. Step 4: ExtendScript builds output AEP → verify comps correct in AE
7. Step 5: `--test` render → review MP4 → iterate on master .aep
8. Full batch render
9. Step 6: Google Sheets tracking matrix
10. Dashboard results gallery with regenerate buttons wired up
11. Step 7: Google Drive delivery

---

## Key Decisions & Rationale

| Decision | Rationale |
|---|---|
| Two AEP files (master + output) | Creatives fix individual variants in the output AEP; master stays clean |
| No PRODUCT_IMG layer in AE | Instrument baked into Stage 1/2 output — no duplication in scene |
| fal.ai for ALL AI generation | Single API key, single client library; no OpenAI/Google SDKs for generation |
| Gemini for LLM/Vision only | Best for structured reasoning, copy writing, schema extraction; not generation |
| Folder upload (webkitdirectory) | Batch asset upload — no one-at-a-time |
| No manual asset mapping approval | Auto-match with warnings; simplifies UX |
| Preview & Select before full batch | Prevents committing to 540 renders before knowing which models produce good results |
| Results gallery with UI regenerate | No CLI for clients — all actions in the browser |
| Asset filename as output name base | Simple, consistent, client-familiar (e.g., sax1, guitar1-a) |
| skip_existing=True everywhere | Idempotency — re-runs safe, only generate/render what's missing |
| Google Sheets delivery matrix | Track all versions with links in one shareable place |
| Google Drive deferred | Test everything else before adding OAuth complexity |
| subtle motion always in stage2 prompt | Brief specifies restrained animation; Gemini always includes this in generated prompts |

---

## Notes on Setup

- **aerender path:** `C:/Program Files/Adobe/Adobe After Effects 2025/aerender.exe` — verify actual AE version
- **After Effects** IS installed on this machine
- **AEP Output Module:** Set to H.264 MP4 in the master AEP before committing
- **nexrender:** install globally via `npm install -g @nexrender/cli`
- **Gemini model ID:** `gemini-3.1-pro-preview` — verify this is still current when building

## Fal.ai Model Paths (Verify at Build Time)

These are best estimates — confirm against fal.ai model browser before implementing Step 3:
- `fal-ai/nano-banana-pro`
- `fal-ai/flux-pro-v2`
- `fal-ai/gpt-image-2`
- `fal-ai/seedream-5`
- `fal-ai/kling-video`
- `fal-ai/veo-3`
- `fal-ai/happy-horse`
- `fal-ai/seedance-2`
- `fal-ai/minimax-video-01` (Hailuo 2.3)
