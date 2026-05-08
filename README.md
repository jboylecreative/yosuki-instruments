# Motion Graphics Pipeline

Brief-driven automated motion graphics pipeline. Ingests a campaign brief PDF + asset folder → AI-generates backgrounds → batch renders all variant MP4s via After Effects headlessly.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11–3.13** | [python.org](https://www.python.org/downloads/) — 3.14 is not yet supported by all dependencies |
| **Node.js 18+** | [nodejs.org](https://nodejs.org/) — required for nexrender, which builds the output AEP headlessly |
| **Adobe After Effects 2026+** | Licensed install. The pipeline drives it headlessly via aerender + nexrender. |
| **Gemini API key** | [aistudio.google.com](https://aistudio.google.com) — brief parsing, copy generation, and image generation |
| **Google OAuth credentials** | Client ID + Client Secret from [console.cloud.google.com](https://console.cloud.google.com) — required for Google Drive delivery. See [Google Drive Delivery](#google-drive-delivery-step-7) below. |
| **Century Gothic font** | Must be installed on the system — used in the After Effects template for all text layers. |

### Tool path auto-discovery

The pipeline locates all external tools automatically on both Windows and macOS — no manual path configuration required for a standard installation.

| Tool | How it's found |
|---|---|
| **aerender** | Scans `C:\Program Files\Adobe\` (Windows) or `/Applications/` (macOS) for any installed `Adobe After Effects *` folder and picks the newest version automatically |
| **nexrender** | Checks `node_modules/.bin/` in the project root (installed by `npm install`), then falls back to system PATH |
| **ffmpeg** | Uses the binary bundled with the `imageio-ffmpeg` Python package, then falls back to system PATH |

If After Effects is installed in a non-standard location, set `aerender_path` in `config.json` or the `AERENDER_PATH` environment variable — auto-discovery is skipped when either is present.

### Sample assets for testing

The `sample_assets/` folder in the project root contains everything needed to run the pipeline end-to-end without a real client deliverable:

- `sample_brief.pdf` — example campaign brief in the expected format
- `sample_images/` — sample client product images (PNG)
- `Century Gothic.ttf` — font file; install this before running the pipeline for the first time

---

## Setup (one-time per machine)

### 1. Install Python dependencies

```
pip3 install -r requirements.txt

```

### 2. Install Node dependencies

```
npm install
```

This installs `nexrender-cli`, which step 4 uses to run the AEP build script headlessly via aerender.

### 3. Configure API key

```
cp .env.example .env
```

Open `.env` and fill in your `GEMINI_API_KEY`.

### 4. Create the AE master template (once)

Open After Effects → **File → Scripts → Run Script File** → select `scripts/create_template.jsx`

The script builds three placeholder compositions (YouTube 16:9, Instagram 1:1, Billboard) with the correct named layers and animation keyframes, and saves to `templates/master_template.aep` automatically.

This is the only step that opens After Effects. All pipeline runs after this are fully headless.

---

## Start the server

```
python -m uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000)

---

## CLI

```
python run_pipeline.py --steps 1,2          # Parse brief + generate copy
python run_pipeline.py --steps 3 --preview  # Preview one asset before full batch
python run_pipeline.py --steps 3,4,5        # Full generation + render
python run_pipeline.py --steps 4,5          # Re-render only (after editing master AEP)
python run_pipeline.py --steps 7            # Upload last run to Google Drive
python run_pipeline.py --dry-run            # Validate without API calls
```

---

## Preview Run vs Generate & Render All

| | Preview Run | Generate & Render All |
|---|---|---|
| **Assets processed** | One — selected from the dropdown | Every asset in the brief |
| **Locales** | English only | All locales in the brief |
| **Sizes rendered** | All enabled sizes | All enabled sizes |
| **Steps run** | 1 → 2 → 3 → 4 → 5 (→ 7 if Drive) | 1 → 2 → 3 → 4 → 5 (→ 7 if Drive) |
| **Typical output** | 3 renders (1 asset × 3 sizes) | Full batch — all assets × sizes × locales |
| **Purpose** | Proof backgrounds, copy, and layout before committing to the full batch | Final delivery |

Use **Preview Run** first to check that the AI-generated backgrounds, taglines, and layout look right for at least one instrument. Once satisfied, hit **Generate & Render All** to produce the complete set.

Both runs upload to Google Drive automatically when Google Drive is selected as the output destination. Each run — preview or full — is stored in its own timestamped subfolder so they never overwrite each other.

---

## Pipeline Steps

| Step | File | Description |
|---|---|---|
| 1 | `step_01_parse_brief.py` | Brief PDF → `campaign_brief.json` + `asset_manifest.json` |
| 2 | `step_02_generate_copy.py` | Gemini 3.1 Pro → `copy_manifest.json` (tagline, CTA, background prompts per locale) |
| 3 | `step_03_generate_backgrounds.py` | Nano Banana 2 → background still image at 2× resolution for each variant/size |
| 4 | `step_04_build_output_aep.py` | Builds output AEP with all variant comps + render queue pre-configured |
| 5 | `step_05_render.py` | Single aerender session renders all comps; FFmpeg batch-encodes to MP4 |
| 6 | `step_06_tracking_sheet.py` | Writes `data/delivery_matrix.csv` |
| 7 | `step_07_deliver.py` | Uploads MP4s + AEP + Footage to Google Drive (when Drive destination is selected) |

---

## AI Models

| Task | Model | API |
|---|---|---|
| Brief parsing, copy generation | Gemini 3.1 Pro (`gemini-3.1-pro-preview`) | Gemini API |
| Background image generation | Nano Banana 2 (`gemini-3.1-flash-image-preview`) | Gemini API |

Both use the single `GEMINI_API_KEY`.

---

## Google Drive Delivery (Step 7)

When "Google Drive" is selected as the output destination, Step 7 runs automatically at the end of every batch and uploads the full run output: all MP4 renders, the output AEP, and the (Footage) folder.

### User flow

Select **Google Drive** as the output destination, then click **Connect Google Drive**. Your browser opens Google's sign-in screen — sign in and click Allow. A folder named after your project is created automatically in your Google Drive root. No folder IDs or further configuration needed.

After the one-time sign-in, all subsequent runs upload headlessly with no further interaction required. The access token refreshes automatically.

### App deployment (one-time, done by whoever hosts the app)

Google Drive requires OAuth app credentials to be configured in `.env` before the Connect button will work. This is a one-time step done by the person who deploys the app — end users never see or touch these values.

1. Go to [console.cloud.google.com](https://console.cloud.google.com), create or select a project
2. **APIs & Services → Library** → enable **Google Drive API**
3. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID** → choose **Desktop app**
4. Copy the Client ID and Client Secret into `.env`:

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

### Drive folder structure

```
{Project Name}/          ← auto-created in your Drive root on first connect
  YYYY-MM-DD/
    HH-MM-SS/
      renders/
        {Instrument}/
          {LOCALE}/
            EN_sax1_1920x1080_001.mp4
            ...
      AE Project/
        output_{YYYY-MM-DD_HH-MM-SS}.aep
        (Footage)/
          ...
```

---

## After Effects Template

The master template in `templates/master_template.aep` is the only AE file the pipeline touches. It contains three compositions:

| Composition | Size |
|---|---|
| `YouTube_1920x1080` | 1920 × 1080 |
| `Instagram_1080x1080` | 1080 × 1080 |
| `Billboard_970x250` | 970 × 250 |

Each composition uses these named layers, which the pipeline bakes in at build time:

| Layer | Type | Content |
|---|---|---|
| `BG_MEDIA` | Footage | AI-generated background still PNG |
| `TEXT_TAGLINE` | Text | Locale-adapted tagline |
| `TEXT_CTA` | Text | Call to action |
| `LOGO` | Footage | Client logo PNG |
| `END_CARD` | Solid | White end card — not swapped |

To update the animation globally: edit `templates/master_template.aep` in After Effects and re-run Steps 4–5. You never need to re-run Steps 1–3.

---

## Output

### File naming

```
{LOCALE}_{asset_stem}_{size_id}_{NNN}.mp4
```

Example: `EN_sax1_1920x1080_001.mp4`, `DE_guitar1-black_1080x1080_001.mp4`

### Local folder structure

```
{output_destination.local_path}/
  {project_name}/
    {YYYY-MM-DD_HH-MM-SS}/
      renders/
        {Instrument}/
          {LOCALE}/
            EN_sax1_1920x1080_001.mp4
            ...
      output_{YYYY-MM-DD_HH-MM-SS}.aep
      (Footage)/
```

Configure `output_destination.local_path` via the Output Location section of the dashboard.

---

## Roadmap / Future Features

### Per-asset regeneration
When running a large batch, a small number of AI-generated backgrounds will inevitably miss the mark. A future regeneration UI would let you flag individual assets, tweak the prompt or parameters, and re-generate only those — without re-running the full pipeline.

### AI video backgrounds
Replace the current static image + keyframed animation approach with AI-generated video backgrounds, looped or timed to the composition length. The most practical integration path is [fal.ai](https://fal.ai), which provides a unified API across multiple video generation models (Kling, Runway, Luma, etc.), making it straightforward to support model selection and fallback.

### Delivery tracking spreadsheet
A master grid (CSV or Google Sheet) that records every version produced across all runs — instrument, locale, size, timestamp, render path, and a direct link to the Drive asset. Would be auto-populated by step 6 and optionally appended on every run rather than overwritten.

### Advanced Mode
An approval-gated workflow that inserts human review between generation and rendering:

- **Copy approval** — Gemini generates several tagline and CTA options per locale; the user selects the hero copy before any rendering begins
- **Background approval** — the pipeline generates multiple background candidates per variant; the user picks the one to bake into the final render
- **Model selection** — choose which image and/or video generation model(s) to use per run, with the option to generate from several simultaneously and compare
- **Static vs video toggle** — per-size or per-asset control over whether the background is a still image or an AI video clip
