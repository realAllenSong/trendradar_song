# Notes: Workflow Split + Action Stability Interview

## Sources

### User Interview (Answers)
- Success metric: publish HTML and generate audio on schedule.
- If TTS fails: HTML should still update; overall workflow should be marked not successful.
- Split preference: open to split; wants safer approach around model cache/download.
- Persisted outputs: raw crawl + summary JSON temporary; transcript/audio/chapters committed.
- Audio cadence: every scheduled/manual run (12h).
- Time limits: 60 min per stage; add more logging, no inactivity kill. Later clarified: overall workflow timeout target 60 min.
- Retries: OK to add.
- Concurrency: allow queueing (no cancel-in-progress).
- Cache strategy: pick safest option if it meets goals.
- External model storage: open to GitHub Releases if free; needs guidance.
- Secrets scoping: unclear, needs explanation.
- Add heartbeats/progress logs: yes.
- Gemini failure: hard-fail.
- Manual options: wants TTS-only/regenerate.
- Retention/cost constraints: unknown.

### Follow-up Answers
- No TTS-only dispatch needed if workflow is split into jobs.
- Temporary artifacts OK with 1 day retention.
- Queueing: allow; add max overall workflow timeout 60 min (note GH Actions limitation).
- Assets job can save cache immediately even if later jobs fail.
- Model size: user asked to inspect repo or online.
- Logging: heartbeat every 1 minute.
- Timeouts: looser than 10s; retries OK.
- Gemini failures: hard-fail, do not commit partial audio/transcript.

### Local Model Size (repo)
- `models` total: ~6.0G
- `models/ONNX_Lab/models`: ~5.8G
  - `onnx_models_quantized`: ~1.1G
  - `VoxCPM1.5`: ~1.8G
  - `ONNX_Lab`: ~2.9G (nested layout)
- `models/sherpa-onnx`: ~195M

### Logs
- Exit code 143 with runner shutdown signal after ~28-50 minutes in `python -m trendradar`.
- No output during long gap suggests hang in crawler/network or TTS compute.

## Implementation Updates
- Workflow split into assets/crawl/audio jobs with caches + 1-day artifacts.
- Crawler timeouts/retries set via env: connect 20s, read 60s, retries 4, backoff 5-15s.
- Audio timeouts/retries set via env: fetch 45s, Gemini retries 3, TTS 120/240s with retries 3.
- Heartbeat logs now flush immediately for CI visibility.
- No junk files with `*` or backticks found under `output/`.

## Synthesized Findings (Draft)
- Current workflow forces audio regeneration (`rm -f audio/...`) which removes interval gating.
- Audio pipeline includes network fetch + embeddings + Gemini + TTS; GitHub runner CPU is slow.
- No per-step timeout or heartbeat in `python -m trendradar`.

---

# Notes: Audio Summary Implementation

## Sources

### Spec
- File: SPEC-audio-summary.md
- Key points:
  - Event clustering via local embeddings + fuzzy match
  - Gemini API for summarization
  - IndexTTS via external endpoint
  - Generate `output/audio/latest.mp3` and `output/audio/chapters.json`
  - UI: bottom player + collapsible chapters list
  - Schedule: every 12h
  - Failure: do not break main flow

## Synthesized Findings

### Integration Targets
- HTML generator: `trendradar/report/html.py`
- Main flow: `trendradar/__main__.py`
- Storage: `output/` folder (GitHub Pages)
- Config loader: `trendradar/core/loader.py`
- HTML writer: `trendradar/report/generator.py` (copies root index only for daily summary)

### Likely New Modules
- `trendradar/audio/` (pipeline: fetch, cluster, summarize, tts, assemble)
- Config fields: audio toggles, endpoints, Gemini key, interval

### Risks
- Action runtime increase due to content fetch + embeddings
- External TTS endpoint availability
- Gemini API limits or missing key
- Workflow currently commits only `index.html`; audio files must be added or copied into repo root for Pages

### Implementation Notes
- Audio pipeline gated by file mtime (12h interval).
- HTML player loads audio/chapters at runtime and hides if unavailable.
- IndexTTS can be called via HF Space `/gradio_api/call` (gradio_client fallback is optional and not in base requirements due to websockets conflict).
- Probe against IndexTTS official Space returned `API call failed` for `/gen_single` (Space may reject API calls or be unavailable).
- Dropped heavy embedding dependencies from base install to avoid GitHub Actions disk errors; fuzzy clustering is used when embeddings are unavailable.
- Sherpa-ONNX Matcha TTS added for CPU-only synthesis; model download is handled via `tools/download_sherpa_onnx_model.py` (uses 16k vocoder).
- Docker entrypoint will auto-download Sherpa-ONNX models when enabled (override with `AUTO_DOWNLOAD_SHERPA_ONNX=false`); failures no longer crash the container.

## Sources

### ONNX_Lab (VoxCPM 1.5B ONNX)
- URL: https://github.com/realAllenSong/ONNX_Lab
- Key points:
  - CLI inference via `python infer.py --text ... --output out.wav` or `--config config.json`.
  - Run config JSON supports `models_dir`, `voxcpm_dir`, `voices_file`, `voice`, `text`, `output`, `max_threads`, `text_normalizer`, `audio_normalizer`, `cfg_value`, `fixed_timesteps`, `seed`.
  - Preset voices are stored in `voices.json`; voice preset resolves `prompt_audio`/`prompt_text`.
  - CPU inference uses `onnxruntime` and requires ONNX model files in `models/onnx_models_quantized`.
  - Requirements for inference: `numpy`, `onnxruntime`, `soundfile`, `transformers`, `tokenizers`, `wetext`, `regex`, `inflect`.
  - Suggested env for prebuilt ONNX download: `VOXCPM_ONNX_REPO`, `VOXCPM_ONNX_URL`, `VOXCPM_ONNX_FORCE`.

### Docker VoxCPM Failure
- ONNX files downloaded under `models/onnx_models_quantized/onnx_models_quantized` due to HF repo layout + `.cache`, causing `infer.py` to miss required files.
- Fix: normalize ONNX layout by moving files into `models/onnx_models_quantized` before validation.
- Docker outputs: `audio/` was not volume-mounted, so `audio/transcript.txt` and `audio/latest.mp3` stayed inside container; fix by mounting `../audio:/app/audio`.
- Audio generation skip was silent when `audio/latest.mp3` existed; adjust gating to log and regenerate if transcript/chapters are missing.
