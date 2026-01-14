# VoxCPM 1.5B ONNX Migration

## What Changed
- TTS provider switched to `voxcpm_onnx` and uses ONNX_Lab CLI (`infer.py --config`).
- New VoxCPM config block added under `audio.tts.voxcpm` with `voice: context_zh_a_share_market_news`.
- Dependencies updated for ONNX runtime + tokenizer stack.
- Workflow clones ONNX_Lab repo to align with default paths.

## Required Assets
- ONNX_Lab repo available at `models/ONNX_Lab` (or override via env).
- Model files present in:
  - `models/ONNX_Lab/models/onnx_models_quantized`
  - `models/ONNX_Lab/models/VoxCPM1.5`
- `models/ONNX_Lab/voices.json` includes `context_zh_a_share_market_news`.

## Default Config (YAML)
```yaml
audio:
  tts:
    provider: "voxcpm_onnx"
    voxcpm:
      repo_dir: "models/ONNX_Lab"
      models_dir: "models/ONNX_Lab/models/onnx_models_quantized"
      voxcpm_dir: "models/ONNX_Lab/models/VoxCPM1.5"
      voices_file: "models/ONNX_Lab/voices.json"
      voice: "context_zh_a_share_market_news"
      batch_mode: true
      max_threads: 2
      text_normalizer: true
      audio_normalizer: false
      cfg_value: 2.5
      fixed_timesteps: 10
      seed: 1
```

## CI Notes
- The crawler workflow now clones ONNX_Lab but does not auto-download weights.
- For CI audio output, ensure the VoxCPM model directories are populated (cache, release download, or a separate setup step).

## Docker Notes
- The container entrypoint can auto-download VoxCPM assets when `AUTO_DOWNLOAD_VOXCPM_ONNX=true`/`AUTO_DOWNLOAD_VOXCPM_MODEL=true`.
- Optional overrides: `VOXCPM_ONNX_REPO`, `VOXCPM_ONNX_URL`, `VOXCPM_MODEL_REPO`, `VOXCPM_REPO_URL`.
