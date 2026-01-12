# Task Plan: Audio News Summary Implementation

## Goal
Implement the audio summary pipeline (clustering, summarization, TTS, and player integration) described in `SPEC-audio-summary.md`.

## Phases
- [x] Phase 1: Plan and setup
- [x] Phase 2: Research/gather information
- [x] Phase 3: Execute/build
- [x] Phase 4: Review and deliver

## Key Questions
1. Where should the audio pipeline integrate in the current TrendRadar run flow?
2. What minimal config + defaults are needed to run in GitHub Actions without breaking existing flows?
3. How should the player + chapters be injected into the HTML output?

## Decisions Made
- Audio generation runs inside `_run_analysis_pipeline` after stats computation.
- Player loads `audio/latest.mp3` and `audio/chapters.json` via client-side fetch, hides if missing.
- Audio artifacts are written to both `output/audio` and repo-root `audio` for Pages + local preview.
- IndexTTS Space is called via `gradio_client` when endpoint is HF Space (auto-detect or provider flag).

## Errors Encountered
- None yet.

## Status
**Completed** - Space API support added and documented.
