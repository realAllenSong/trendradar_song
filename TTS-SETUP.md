# TTS Integration Notes (Sherpa-ONNX + Gemini)

This doc summarizes what to watch for and how to configure the TTS pipeline in another project.

## Requirements
- Python deps: `sherpa-onnx`, `numpy`, `requests`, `google-genai`
- External tools: `ffmpeg` (required to concatenate segments into `latest.mp3`)
- Model assets (Matcha zh-en + 16k vocoder + rule FSTs + espeak-ng-data)

## Model Assets (must exist on disk)
Recommended repo: `csukuangfj/matcha-icefall-zh-en`

Required files in a local directory, e.g. `models/sherpa-onnx/matcha-icefall-zh-en`:
- `model-steps-3.onnx`
- `tokens.txt`
- `lexicon.txt`
- `phone-zh.fst`
- `number-zh.fst`
- `date-zh.fst`
- `espeak-ng-data/` (directory)
- `vocos-16khz-univ.onnx` (vocoder)

There is a helper script in this repo:
```
python tools/download_sherpa_onnx_model.py
```

## Minimum Config (YAML)
```
audio:
  enabled: true
  interval_hours: 12
  gemini_api_key: "YOUR_KEY"
  gemini_model: "gemini-3-flash-preview"
  summary_prompt: |
    You are a news narrator. Output JSON only with summary, short_summary, priority_score, title.

  tts:
    provider: "sherpa_onnx"
    sherpa_onnx:
      model_dir: "models/sherpa-onnx/matcha-icefall-zh-en"
      acoustic_model: "model-steps-3.onnx"
      vocoder: "vocos-16khz-univ.onnx"
      tokens: "tokens.txt"
      lexicon: "lexicon.txt"
      rule_fsts: "phone-zh.fst,number-zh.fst,date-zh.fst"
      data_dir: "espeak-ng-data"
      sid: 0
      speed: 1.0
      num_threads: 2
      provider: "cpu"

  output:
    dir: "output/audio"
    public_dir: "audio"
    filename: "latest.mp3"
    chapters_filename: "chapters.json"
    transcript_filename: "transcript.txt"
```

## Environment Overrides (optional)
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `AUDIO_ENABLED`
- `AUDIO_INTERVAL_HOURS`
- `AUDIO_SUMMARY_PROMPT`
- `SHERPA_ONNX_MODEL_DIR`, `SHERPA_ONNX_ACOUSTIC_MODEL`, `SHERPA_ONNX_VOCODER`
- `SHERPA_ONNX_TOKENS`, `SHERPA_ONNX_LEXICON`, `SHERPA_ONNX_RULE_FSTS`, `SHERPA_ONNX_DATA_DIR`
- `SHERPA_ONNX_SID`, `SHERPA_ONNX_SPEED`, `SHERPA_ONNX_NUM_THREADS`, `SHERPA_ONNX_PROVIDER`

## Output Files
- `output/audio/latest.mp3` (final audio)
- `output/audio/chapters.json` (chapters)
- `output/audio/transcript.txt` (plain text script)

If `ffmpeg` is missing, `latest.mp3` will NOT be generated.

## Common Pitfalls
- Missing `ffmpeg` -> concatenation fails.
- Wrong vocoder sample rate -> use `vocos-16khz-univ.onnx` for zh+en model.
- Missing `espeak-ng-data` -> zh/en mix fails or sounds wrong.
- Secrets committed to repo -> always use env/Secrets for API keys.

## GitHub Actions Notes
- Install ffmpeg before running:
```
sudo apt-get update
sudo apt-get install -y ffmpeg
```
- Add `GEMINI_API_KEY` to repository secrets.
- Cache `models/sherpa-onnx` to avoid re-downloading each run.

## Lightweight Usage in Another Project
If you only need TTS (no summarization), you can directly create a `sherpa_onnx.OfflineTts`:
```
import sherpa_onnx

tts = sherpa_onnx.OfflineTts(
    sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=".../model-steps-3.onnx",
                vocoder=".../vocos-16khz-univ.onnx",
                lexicon=".../lexicon.txt",
                tokens=".../tokens.txt",
                data_dir=".../espeak-ng-data",
            ),
            provider="cpu",
            num_threads=2,
        ),
        rule_fsts=".../phone-zh.fst,.../number-zh.fst,.../date-zh.fst",
        max_num_sentences=0,
    )
)
audio = tts.generate("Your text here", sid=0, speed=1.0)
```

