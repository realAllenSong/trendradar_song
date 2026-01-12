#!/usr/bin/env python3
# coding=utf-8
"""
Download Sherpa-ONNX Matcha zh-en model assets from Hugging Face.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_REPO = "csukuangfj/matcha-icefall-zh-en"
DEFAULT_FILES = [
    "model-steps-3.onnx",
    "tokens.txt",
    "lexicon.txt",
    "phone-zh.fst",
    "number-zh.fst",
    "date-zh.fst",
]
DEFAULT_VOCODER_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/"
    "vocos-16khz-univ.onnx"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Sherpa-ONNX TTS model files")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Hugging Face repo id")
    parser.add_argument(
        "--output-dir",
        default="models/sherpa-onnx/matcha-icefall-zh-en",
        help="Directory to store model files",
    )
    parser.add_argument(
        "--vocoder-url",
        default=DEFAULT_VOCODER_URL,
        help="Vocoder ONNX download URL",
    )
    parser.add_argument(
        "--include-espeak",
        action="store_true",
        default=True,
        help="Download espeak-ng-data for mixed zh/en",
    )
    parser.add_argument(
        "--skip-espeak",
        action="store_true",
        help="Skip espeak-ng-data download",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    repo_files = _list_repo_files(args.repo)
    if not repo_files:
        print("[download] Failed to fetch repo file list")
        return 1

    for name in DEFAULT_FILES:
        if name not in repo_files:
            print(f"[download] Missing file in repo: {name}")
            return 1
        _download_hf_file(args.repo, name, output_dir / name)

    _download_url(args.vocoder_url, output_dir / "vocos-16khz-univ.onnx")

    include_espeak = args.include_espeak and not args.skip_espeak
    if include_espeak:
        espeak_files = [f for f in repo_files if f.startswith("espeak-ng-data/")]
        if not espeak_files:
            print("[download] No espeak-ng-data found in repo")
        for espeak_file in espeak_files:
            target = output_dir / espeak_file
            _download_hf_file(args.repo, espeak_file, target)

    print(f"[download] Done: {output_dir}")
    return 0


def _list_repo_files(repo_id: str) -> list[str]:
    url = f"https://huggingface.co/api/models/{repo_id}"
    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [item.get("rfilename") for item in data.get("siblings", []) if item.get("rfilename")]
    except Exception as exc:
        print(f"[download] Failed to list repo files: {exc}")
        return []


def _download_hf_file(repo_id: str, filename: str, dest: Path) -> None:
    safe_name = urllib.parse.quote(filename, safe="/")
    url = f"https://huggingface.co/{repo_id}/resolve/main/{safe_name}"
    _download_url(url, dest)


def _download_url(url: str, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as handle:
        shutil.copyfileobj(resp, handle)


if __name__ == "__main__":
    raise SystemExit(main())
