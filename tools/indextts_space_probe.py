# coding=utf-8
"""
Probe IndexTTS Space API via gradio_client.
"""

import argparse
from pathlib import Path
from typing import List, Optional

import json
import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe IndexTTS HF Space API")
    parser.add_argument("--space", default="IndexTeam/IndexTTS-2-Demo", help="HF Space name or URL")
    parser.add_argument("--text", default="你好，这是 IndexTTS 语音测试。", help="Text to synthesize")
    parser.add_argument("--out", default="output/audio/probe.mp3", help="Output audio path")
    args = parser.parse_args()

    base_url = _hf_space_base_url(args.space)
    if not base_url:
        print("[probe] Invalid Space name or URL")
        return 1

    try:
        info = requests.get(f"{base_url}/gradio_api/info", timeout=20)
        info.raise_for_status()
        print("[probe] API endpoints:", ", ".join(info.json().get("named_endpoints", {}).keys()))
    except Exception as exc:
        print(f"[probe] Failed to fetch API info: {exc}")
        return 1

    result = _call_space_api(base_url, "gen_single", _default_space_args(args.text))
    if not result:
        print("[probe] API call failed")
        return 1

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    segment_path = _materialize_gradio_audio(result, output_path.parent, 0)
    if not segment_path:
        print("[probe] No audio returned")
        return 1

    segment_path.replace(output_path)
    print(f"[probe] Saved: {output_path}")
    return 0


def _hf_space_base_url(endpoint: str) -> Optional[str]:
    endpoint = endpoint.strip()
    if endpoint.startswith("http"):
        if "hf.space" in endpoint:
            return endpoint.rstrip("/")
        if "huggingface.co/spaces/" in endpoint:
            space = endpoint.split("huggingface.co/spaces/")[-1].strip("/")
        else:
            return None
    else:
        space = endpoint.replace("hf://", "")

    if "/" not in space:
        return None

    owner, name = space.split("/", 1)
    slug = f"{owner}-{name}".lower().replace(" ", "-")
    return f"https://{slug}.hf.space"


def _default_space_args(text: str) -> List:
    return [
        "Same as the voice reference",  # emo_control_method
        None,       # prompt audio path
        text,       # text
        None,       # emo_ref_path
        0.8,        # emo_weight
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,  # vec1-vec8
        "",         # emo_text
        False,      # emo_random
        120,        # max_text_tokens_per_segment
        True,       # do_sample
        0.8,        # top_p
        30,         # top_k
        0.8,        # temperature
        0.0,        # length_penalty
        3,          # num_beams
        10.0,       # repetition_penalty
        1500,       # max_mel_tokens
    ]


def _materialize_gradio_audio(result, segment_dir: Path, idx: int) -> Optional[Path]:
    candidate = _extract_candidate(result)
    if not candidate:
        return None

    if isinstance(candidate, (list, tuple)):
        if candidate and isinstance(candidate[0], str):
            candidate = candidate[0]
        elif candidate and isinstance(candidate[0], dict):
            candidate = candidate[0]

    if isinstance(candidate, dict):
        candidate = candidate.get("path") or candidate.get("name") or candidate.get("url")

    if not candidate:
        return None

    suffix = _guess_extension(candidate)
    segment_path = segment_dir / f"segment_{idx:03d}{suffix}"

    if isinstance(candidate, str) and candidate.startswith("http"):
        try:
            response = requests.get(candidate, timeout=30)
            response.raise_for_status()
            with open(segment_path, "wb") as handle:
                handle.write(response.content)
            return segment_path
        except Exception:
            return None

    if isinstance(candidate, str) and Path(candidate).exists():
        try:
            Path(candidate).replace(segment_path)
            return segment_path
        except Exception:
            return None

    return None


def _extract_candidate(result):
    if isinstance(result, dict):
        return result.get("value", result)
    return result


def _guess_extension(candidate: str) -> str:
    if not isinstance(candidate, str):
        return ".wav"
    lower = candidate.lower()
    for ext in (".wav", ".mp3", ".flac", ".m4a"):
        if lower.endswith(ext):
            return ext
    return ".wav"


def _call_space_api(base_url: str, api_name: str, args: List) -> Optional[object]:
    try:
        response = requests.post(
            f"{base_url}/gradio_api/call/{api_name}",
            json={"data": args},
            timeout=60,
        )
        response.raise_for_status()
        event_id = response.json().get("event_id")
        if not event_id:
            return None

        stream = requests.get(
            f"{base_url}/gradio_api/call/{api_name}/{event_id}",
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=180,
        )
        stream.raise_for_status()

        current_event = None
        for raw in stream.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("event:"):
                current_event = raw.split(":", 1)[1].strip()
                continue
            if not raw.startswith("data:"):
                continue
            data = raw.split(":", 1)[1].strip()
            if current_event == "complete":
                return json.loads(data)
            if current_event == "error":
                return None
    except Exception:
        return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
