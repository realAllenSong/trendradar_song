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
