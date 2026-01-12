# Audio Summary Implementation Deliverable

## Overview
Implemented the audio summary pipeline and UI integration described in `SPEC-audio-summary.md`.

## Key Changes
- Added audio pipeline (`trendradar/audio/pipeline.py`) with:
  - Title dedup + event clustering (fuzzy + local embeddings).
  - Gemini-based summarization with priority scoring.
- Sherpa-ONNX Matcha TTS support (16k vocoder), plus IndexTTS (HTTP, HF Space `/gradio_api/call`, with gradio_client fallback), ffmpeg concatenation, and chapters JSON output.
  - 12h interval gating by audio file mtime.
  - Writes audio/chapters to both `output/audio` and repo-root `audio`.
- Integrated audio generation into `_run_analysis_pipeline` in `trendradar/__main__.py`.
- Added bottom audio player + chapter list to `trendradar/report/html.py`.
- Added audio config block to `config/config.yaml` and loader support in `trendradar/core/loader.py`.
- Updated workflow commit step to include audio artifacts.
- Added dependencies: `rapidfuzz`, `google-genai`, `sherpa-onnx`, `numpy`.
- Docker entrypoint now auto-downloads Sherpa-ONNX model when provider is enabled.

## Paths Updated
- `trendradar/audio/pipeline.py`
- `trendradar/audio/__init__.py`
- `tools/indextts_space_probe.py`
- `tools/download_sherpa_onnx_model.py`
- `trendradar/__main__.py`
- `trendradar/report/html.py`
- `trendradar/core/loader.py`
- `config/config.yaml`
- `.github/workflows/crawler.yml`
- `requirements.txt`

## Notes
- Audio is generated only when `audio.enabled: true` and `GEMINI_API_KEY` is configured, plus either a Sherpa-ONNX provider or a TTS endpoint.
- Player hides automatically if audio files are missing.
