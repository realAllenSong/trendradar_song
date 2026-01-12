# Audio News Summary (Podcast-Style) Spec

## Overview
Generate a 5–10 minute, podcast-style audio summary of the TrendRadar daily/current page. The audio should:
- Deduplicate and merge similar events across platforms.
- Summarize each event in a neutral tone (2–3 sentences for higher-priority events, 1 sentence for lower-priority).
- Mention sources for each merged event.
- Use a fixed, concise risk disclaimer at the beginning and end of the program.
- Provide chapters with timestamps and titles.
- Present a bottom audio player on the page (no transcript required).

## Goals
- Produce a single, listenable audio summary that covers all events via clustering and compression.
- Keep the run automated in GitHub Actions (aligned with existing workflow cadence).
- Use local, open-source embeddings for clustering (free; slower acceptable).
- Use Gemini API for summarization (quality and stability).
- Use a single-voice TTS (IndexTTS hosted on free GPU, e.g., HuggingFace).
- Store only the latest audio artifact (overwrite each run).

## Non-goals
- No background music.
- No requirement to store historical audio archives.
- No transcript UI on the page.
- No per-item risk warning (only global disclaimer at start/end).

## User Experience
- Bottom sticky audio player on the HTML page with custom controls (play/pause, progress, time).
- Expandable chapter list above the player (timestamp + title, click to seek).
- No error banners if audio generation fails; the player simply does not appear.

## Content Pipeline

### 1) Input
- Use the same news items that generate the HTML report (titles, URLs, sources, ranks, time, counts).
- Allow full-text fetching from source pages for clustering and summarization.

### 2) Content Fetching
- For each news item, attempt to fetch article content.
- Use a per-request timeout (2–5 seconds).
- If fetching fails, fall back to title + platform + any existing snippet.

### 3) Dedup & Event Clustering
Primary objectives:
- Title similarity dedup.
- Event-level clustering across platforms.

Proposed approach:
1. Normalize titles (lowercase, punctuation removal, whitespace collapse).
2. Stage-1 fuzzy match (RapidFuzz): if similarity >= 90, group as same event.
3. Stage-2 semantic match:
   - Generate embeddings locally (SentenceTransformers).
   - For each item, compare to existing cluster centroids.
   - If cosine similarity >= threshold (e.g., 0.82), merge into that cluster.
   - Otherwise create new cluster.

Embedding defaults (configurable):
- Default model: `intfloat/multilingual-e5-small` or `BAAI/bge-small-zh-v1.5`.
- CPU inference acceptable; GPU optional.

### 4) Priority Scoring
Score each cluster using a model-assisted heuristic:
- Inputs: rank, count, platform weight, recency, source diversity.
- Provide these features to Gemini as part of a lightweight scoring prompt.
- Output a 0–100 priority score.

Priority rules:
- High priority: 2–3 sentence summary.
- Low priority: title + 1 sentence summary.
- Maintain coverage for all clusters.

### 5) Summarization (Gemini API)
Use Gemini to produce summaries with a neutral tone.
- Summaries for high priority: 2–3 sentences.
- Summaries for low priority: 1 sentence.
- Must include sources list in spoken format (e.g., "This event appears on A, B, C.").
- Avoid subjective language.

Global disclaimer (fixed template):
Intro: "Brief note: This summary is generated from public sources and may require verification."
Outro: "Reminder: Please verify details with original sources."

Model defaults (configurable):
- `gemini-3-flash-preview` for cost-efficient summarization.

### 6) Script Assembly
Single-host, conversational tone (simulated dialogue style without multiple voices).
Structure:
1. Intro + disclaimer.
2. High priority clusters.
3. Low priority clusters (shorter).
4. Closing + disclaimer.

### 7) Chapters
Each cluster produces one chapter entry:
- `title`: merged event title (short).
- `start`: timestamp in seconds.
- `sources`: list of platforms.

Compute chapter timestamps based on concatenated audio segment durations.
Output `output/audio/chapters.json` alongside the audio file.

### 8) TTS (IndexTTS)
Primary plan:
- Use IndexTTS hosted on a free GPU service (HuggingFace Spaces).
- Call a single endpoint per segment and receive mp3/wav audio.
- Concatenate segments in order (ffmpeg or pydub).

TTS API contract (proposed):
```
POST /tts
{
  "text": "...",
  "voice": "default",
  "format": "mp3"
}
```

### 9) Audio Assembly
- Concatenate segments into `output/audio/latest.mp3`.
- Generate `output/audio/chapters.json`.
- Overwrite previous audio each run (no archive).

## Scheduling
- Run audio generation every 12 hours.
- It should align with existing GitHub Actions cadence (crawler).
- If crawler runs more often, audio generation should be gated by last-audio timestamp.

## Storage
- Save audio to repository and publish via GitHub Pages.
- Keep only `latest.mp3` to avoid unbounded growth.

## Integration Points

### TrendRadar Pipeline
Add a new optional audio step in the report generation flow:
1. Crawl + store data.
2. Build HTML.
3. If audio schedule allows, run audio pipeline.
4. Update `output/index.html` to include player if audio exists.

### HTML Integration
Add a bottom sticky player with:
- Play/pause, current time, duration, progress bar.
- Collapsible chapter list (timestamp + title; click to seek).
- Hide player if `latest.mp3` missing.

## Configuration
Proposed config keys (in `config.yaml` or `.env`):
- `AUDIO_ENABLED` (bool)
- `AUDIO_INTERVAL_HOURS` (default 12)
- `EMBEDDING_MODEL` (default: `intfloat/multilingual-e5-small`)
- `EMBEDDING_SIM_THRESHOLD` (default: 0.82)
- `FETCH_TIMEOUT_SECONDS` (default: 5)
- `GEMINI_MODEL` (default: `gemini-3-flash-preview`)
- `GEMINI_API_KEY`
- `INDEXTTS_ENDPOINT`
- `INDEXTTS_API_KEY` (optional)

## Dependencies
- Python: `requests`, `sentence-transformers`, `rapidfuzz`, `numpy`
- Gemini: `google-genai`
- Audio: `ffmpeg` (for concatenation) or `pydub` (requires ffmpeg)

## Failure Handling
- If audio fails, still produce HTML and exit with success.
- No UI error message; player hidden when audio missing.
- Log errors for debugging.

## Acceptance Criteria
- Audio file generated at `output/audio/latest.mp3` every 12 hours.
- `chapters.json` created and used by player.
- Page shows a bottom player when audio exists.
- All events are covered via clustering and compression.
- Low-priority events are shortened.
- Summary is neutral, with fixed disclaimer at start and end.

## Open Questions (Implementation)
- Confirm IndexTTS HF Spaces API contract.
- Validate Gemini API availability under current GCP account and region.
