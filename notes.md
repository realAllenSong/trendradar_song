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
