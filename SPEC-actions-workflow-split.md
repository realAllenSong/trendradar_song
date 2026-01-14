# Spec: Split GitHub Actions Workflow for TrendRadar

## Goal
Make the scheduled/manual pipeline reliable and debuggable by splitting long-running work into isolated jobs, while preserving these requirements:

- Always publish updated `index.html` on schedule.
- Always attempt audio generation on schedule (every 12h).
- If audio fails, the run must be marked as failed, but HTML must still be updated.
- Transcript/audio/chapters must be committed; raw crawl + summary JSON are temporary artifacts.

## Success Criteria
1. HTML updates commit even when audio fails.
2. Audio job fails hard on Gemini/TTS errors; no partial audio/transcript commit.
3. Each job has visible progress (heartbeat every 1 minute).
4. Caches for VoxCPM/HF assets are reused across jobs and runs.
5. Artifacts (raw crawl + summary JSON) are retained for 1 day.

## Constraints and Observations
- GitHub Actions only supports job-level timeouts; no true workflow-level timeout.
- Current assets size (local):
  - `models/ONNX_Lab/models`: ~5.8G
    - `onnx_models_quantized`: ~1.1G
    - `VoxCPM1.5`: ~1.8G
    - nested `ONNX_Lab`: ~2.9G
  - `models/sherpa-onnx`: ~195M
- Current pipeline runs `python -m trendradar` with no CLI flags, so we need new modes/flags to split work cleanly.

## Proposed Workflow Structure
Single workflow with multiple jobs and `needs`, to keep cache and artifacts in one run.

### Triggers
- `schedule`: every 12h (existing cron).
- `workflow_dispatch`: manual trigger.

### Concurrency
- `group: crawler-${{ github.ref_name }}`
- `cancel-in-progress: false` (queue runs per branch).

### Job: `assets`
Purpose: download models (if cache miss) and save caches early.

- `timeout-minutes: 60`
- Steps:
  1. Checkout repo.
  2. Restore cache:
     - `models/ONNX_Lab/models` (key based on `tools/ensure_voxcpm_assets.py`)
     - `~/.cache/huggingface` (key based on `tools/ensure_voxcpm_assets.py`, `requirements.txt`)
  3. Run `tools/ensure_voxcpm_assets.py` (downloads if missing).
  4. Save caches using `actions/cache/save` when cache miss is detected.

### Job: `crawl`
Purpose: crawl + summary + HTML only (no audio), and export report JSON for later audio.

- `needs: [assets]`
- `timeout-minutes: 60`
- Env:
  - `AUDIO_ENABLED=false` (skip audio)
  - `TREND_RADAR_EXPORT_REPORT_PATH=output/report.json` (new)
  - `TREND_RADAR_EXPORT_CRAWL_PATH=output/crawl.json` (new)
  - Looser crawler timeouts/retries (via env):
    - `CRAWLER_CONNECT_TIMEOUT_SECONDS=20`
    - `CRAWLER_READ_TIMEOUT_SECONDS=60`
    - `CRAWLER_MAX_RETRIES=4`
    - `CRAWLER_RETRY_MIN_SECONDS=5`
    - `CRAWLER_RETRY_MAX_SECONDS=15`
- Steps:
  1. Checkout repo.
  2. Restore caches (same keys as `assets`).
  3. Install deps.
  4. Run `python -m trendradar` (crawler + HTML).
  5. Upload artifacts:
     - `output/report.json`, `output/crawl.json`
     - `retention-days: 1`
  6. Commit HTML changes:
     - Commit `index.html` only.
     - `git pull --rebase` before commit to avoid conflicts.

### Job: `audio`
Purpose: generate transcript/audio/chapters from exported report without re-crawling.

- `needs: [assets, crawl]`
- `timeout-minutes: 60`
- Env:
  - `AUDIO_ENABLED=true`
  - `AUDIO_INTERVAL_HOURS=0` (force every run)
  - `TREND_RADAR_AUDIO_REPORT_PATH=output/report.json` (new)
  - `GEMINI_API_KEY` only in this job
  - Looser audio timeouts/retries (via env):
    - `AUDIO_FETCH_TIMEOUT_SECONDS=45`
    - `AUDIO_FETCH_MAX_RETRIES=3`
    - `AUDIO_FETCH_RETRY_BACKOFF_SECONDS=1.5`
    - `AUDIO_GEMINI_MAX_RETRIES=3`
    - `AUDIO_GEMINI_BACKOFF_SECONDS=2`
    - `AUDIO_GEMINI_MAX_BACKOFF_SECONDS=12`
    - `AUDIO_TTS_TIMEOUT_SECONDS=120`
    - `AUDIO_TTS_EVENT_TIMEOUT_SECONDS=240`
    - `AUDIO_TTS_MAX_RETRIES=3`
    - `AUDIO_TTS_RETRY_BACKOFF_SECONDS=2`
- Steps:
  1. Checkout repo.
  2. Restore caches (same keys).
  3. Download artifacts from `crawl` job into `output/`.
  4. Run audio-only path:
     - New CLI or env-driven mode that loads `output/report.json` and calls `maybe_generate_audio`.
  5. Commit audio outputs:
     - `audio/latest.mp3`
     - `audio/chapters.json`
     - `audio/transcript.txt`
     - `git pull --rebase` before commit.
  6. Fail job on any Gemini or TTS error (no partial commit).

## Required Code Changes
### 1) Export Report and Crawl Data
When `TREND_RADAR_EXPORT_REPORT_PATH` is set:
- Serialize `report_data` (from `ctx.prepare_report`) to JSON at that path.

When `TREND_RADAR_EXPORT_CRAWL_PATH` is set:
- Save raw crawl results (before analysis) to JSON at that path.

Suggested location:
- `trendradar/__main__.py` after `report_data` is prepared.
- `trendradar/crawler` or `trendradar/storage` for raw crawl export.

### 2) Audio-Only Mode
Add a code path that reads `TREND_RADAR_AUDIO_REPORT_PATH` and skips crawling:
- `main()` checks `TREND_RADAR_AUDIO_REPORT_PATH`
- Load JSON → call `maybe_generate_audio(report_data, config)`
- Exit non-zero if audio fails (Gemini or TTS).

### 3) Heartbeat Logs (Every 60s)
Add a heartbeat logger to avoid silent hangs:
- Crawler: log progress every N URLs and at least once per minute.
- Content fetch: log every N items and at least once per minute.
- TTS: log every N segments and at least once per minute.

Suggested env:
- `TREND_RADAR_HEARTBEAT_SECONDS=60`

### 4) Network Timeouts + Retries
Add request timeouts and retries for crawler + content fetch + Gemini calls.

Looser defaults (can be overridden by env):
- Connect timeout: 20s
- Read timeout: 60s
- Retries: 4
- Backoff: 5–15s

Use a shared `requests.Session` with `HTTPAdapter` + `Retry`.

### 5) Secrets Scope
Expose `GEMINI_API_KEY` only in `audio` job.
Crawler job runs without secrets.

## Artifacts
- `output/report.json` and `output/crawl.json` uploaded from `crawl` job.
- Retention: 1 day.
- Used for debugging only (not committed).

## Caching Strategy
Use cache keys:
- `voxcpm-models-${{ runner.os }}-${{ hashFiles('tools/ensure_voxcpm_assets.py') }}`
- `hf-cache-${{ runner.os }}-${{ hashFiles('tools/ensure_voxcpm_assets.py', 'requirements.txt') }}`

Save caches in `assets` job immediately after downloads (use `actions/cache/save`).

## Error Handling
- **Crawler fail**: workflow fails; no commits.
- **Audio fail**: workflow fails; HTML already committed; no audio/transcript commit.
- **Gemini fail**: hard fail, no partial commit.

## Optional: GitHub Release for Model Assets
If cache eviction becomes a problem, publish a release asset:
- Create a release `models-v1`.
- Upload tarball of `models/ONNX_Lab/models`.
- Modify `assets` job to download the release asset on cache miss before falling back to HF.

## Implementation Plan
1. Add report export and audio-only mode in code.
2. Add heartbeat + timeout/retry logic.
3. Update `.github/workflows/crawler.yml` to multi-job workflow with artifacts and cache save.
4. Test with `workflow_dispatch`.

## Known Limitation
GitHub Actions does not support a true workflow-level timeout. The spec uses `timeout-minutes: 60` per job; total wall time can exceed 60 minutes if jobs run sequentially. If strict 60-minute overall time is required, the workflow must be compressed into fewer jobs.
