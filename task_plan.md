# Task Plan: Switch TTS to VoxCPM 1.5B ONNX CLI

## Goal
Replace Kokoro TTS with VoxCPM 1.5B ONNX CLI synthesis and update configs/workflows so audio generation uses the new model reliably.

## Phases
- [x] Phase 1: Plan and setup
- [x] Phase 2: Research/gather information
- [x] Phase 3: Execute/build
- [x] Phase 4: Review and deliver
- [x] Phase 5: Fix Docker VoxCPM asset download + runtime validation

## Key Questions
1. What CLI/config inputs are required by ONNX_Lab for preset voice synthesis?
2. Which repo paths/config keys should TrendRadar expose for VoxCPM CLI?
3. What dependency/workflow updates ensure CLI inference runs in CI?

## Decisions Made
- Use ONNX_Lab CLI `infer.py --config` for per-segment synthesis with preset voice.
- Expose VoxCPM paths/voice config under `audio.tts.voxcpm` and env overrides.

## Errors Encountered
- Docker build failed compiling `pyahocorasick` due to missing `gcc` on arm64 -> add `build-essential` to Dockerfile.
- VoxCPM CLI failed: missing ONNX files in `models/ONNX_Lab/models/onnx_models_quantized` inside container.
- ONNX files landed in nested `onnx_models_quantized/onnx_models_quantized` due to HF repo layout + `.cache`.
- Manual runs skipped audio without logs because interval gating only checked `audio/latest.mp3` and didn't consider missing transcript/chapters.

## Status
**Completed** - Added ONNX layout normalization and mounted `/app/audio` for Docker outputs; awaiting validation run.
