# Yosuki Motion Graphics Pipeline

Automated motion graphics pipeline for the Yosuki "Find Your Sound" campaign.  
Ingests a campaign brief PDF + asset folder → generates AI backgrounds → populates After Effects templates → batch renders all variant MP4s → delivers to Google Drive.

## Setup

### 1. Copy environment file

```
cp .env.example .env
```

Fill in your API keys:
- `GEMINI_API_KEY` — [Google AI Studio](https://aistudio.google.com/)
- `FAL_KEY` — [fal.ai dashboard](https://fal.ai/dashboard)
- `GOOGLE_DRIVE_FOLDER_ID` — ID from the Drive folder URL
- `GOOGLE_SHEETS_ID` — ID from the Sheets URL
- `AERENDER_PATH` — path to your aerender executable

### 2. Install Python dependencies

```
pip install -r requirements.txt
```

### 3. Install Node.js dependencies (nexrender)

```
npm install -g @nexrender/cli @nexrender/action-copy
```

### 4. Create the After Effects master template

Open After Effects and run `scripts/create_template.jsx` via **File → Scripts → Run Script File**.  
This creates 3 placeholder compositions. Add your keyframe animation, set the Output Module to H.264 MP4, then save as `templates/yosuki_master_template.aep`.

### 5. Start the dashboard

```
uvicorn server:app --reload
```

Open [http://localhost:8000](http://localhost:8000)

---

## Usage

1. **Upload brief** — drag the campaign brief PDF onto the dashboard
2. **Upload assets** — drag your entire asset folder
3. **Preview run** — test all enabled models on one asset before committing
4. **Full batch** — renders all variants with selected models
5. **Results** — browse and regenerate individual variants from the Results tab

---

## Pipeline Steps

| Step | Script | Description |
|---|---|---|
| 1 | `pipeline/step_01_parse_brief.py` | Parse brief PDF + auto-match assets via Gemini Vision |
| 2 | `pipeline/step_02_generate_copy.py` | Generate copy for all 4 locales via Gemini |
| 3 | `pipeline/step_03_generate_backgrounds.py` | Stage 1 image + Stage 2 video via fal.ai |
| 4 | `pipeline/step_04_build_output_aep.py` | Build output AEP via ExtendScript |
| 5 | `pipeline/step_05_render.py` | Batch render via nexrender + aerender |
| 6 | `pipeline/step_06_tracking_sheet.py` | Generate Google Sheets delivery matrix |
| 7 | `pipeline/step_07_deliver.py` | Upload to Google Drive |

## CLI

```
python run_pipeline.py --steps 1,2          # Parse and generate copy only
python run_pipeline.py --steps 3 --preview  # Preview backgrounds for one asset
python run_pipeline.py --steps 4,5          # Re-render (after editing master .aep)
python run_pipeline.py --dry-run            # Validate without API calls
```
