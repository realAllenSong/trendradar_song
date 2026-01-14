#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import yaml

REQUIRED_ONNX = [
    "VoxCPM_Text_Embed.onnx",
    "VoxCPM_VAE_Encoder.onnx",
    "VoxCPM_Feat_Encoder.onnx",
    "VoxCPM_Feat_Cond.onnx",
    "VoxCPM_Concat.onnx",
    "VoxCPM_Main.onnx",
    "VoxCPM_Feat_Decoder.onnx",
    "VoxCPM_VAE_Decoder.onnx",
]

TOKENIZER_FILES = ["tokenizer.json", "tokenizer.model"]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_config(config_path: Path) -> dict:
    if not config_path.is_file():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_path(base_dir: Path, value: str, default_rel: str) -> Path:
    if value:
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
        return (Path.cwd() / candidate).resolve()
    return base_dir / default_rel


def _has_required_onnx(models_dir: Path) -> bool:
    return all((models_dir / name).is_file() for name in REQUIRED_ONNX)


def _has_tokenizer(voxcpm_dir: Path) -> bool:
    return any((voxcpm_dir / name).is_file() for name in TOKENIZER_FILES)


def _merge_repo_contents(source_dir: Path, repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        if item.name in {".git", "models"}:
            continue
        destination = repo_dir / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def _safe_clone(repo_url: str, repo_dir: Path) -> bool:
    if (repo_dir / "infer.py").is_file():
        return True
    if not repo_url:
        return False
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists() and any(repo_dir.iterdir()):
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_repo = Path(tmp_dir) / "repo"
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, str(tmp_repo)],
                    check=True,
                )
                _merge_repo_contents(tmp_repo, repo_dir)
            return (repo_dir / "infer.py").is_file()
        except Exception as exc:
            print(f"[VoxCPM] Clone failed: {exc}")
            return False

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(repo_dir)],
            check=True,
        )
        return True
    except Exception as exc:
        print(f"[VoxCPM] Clone failed: {exc}")
        return False


def _download_hf_snapshot(repo_id: str, target_dir: Path, revision: str | None) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        print(f"[VoxCPM] huggingface_hub unavailable: {exc}")
        return False

    allow_patterns = ["*.onnx", "*.onnx.data", "voxcpm_onnx_config.json"]
    try:
        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            local_dir=str(target_dir),
            allow_patterns=allow_patterns,
            local_dir_use_symlinks=False,
        )
        return True
    except Exception as exc:
        print(f"[VoxCPM] HF download failed: {exc}")
        return False


def _download_archive(url: str, target_dir: Path) -> bool:
    try:
        import requests
    except Exception as exc:
        print(f"[VoxCPM] requests unavailable: {exc}")
        return False

    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / "voxcpm_onnx_archive"

    try:
        with requests.get(url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with archive_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
    except Exception as exc:
        print(f"[VoxCPM] Download archive failed: {exc}")
        return False

    try:
        if url.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(target_dir)
        elif url.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(target_dir)
        else:
            print("[VoxCPM] Unsupported archive format (use .tar.gz/.tgz/.zip).")
            return False
    finally:
        archive_path.unlink(missing_ok=True)

    return True


def _find_onnx_dir(root_dir: Path) -> Path | None:
    if _has_required_onnx(root_dir):
        return root_dir
    try:
        children = [p for p in root_dir.iterdir() if p.is_dir() and p.name != ".cache"]
    except FileNotFoundError:
        return None
    for child in children:
        if _has_required_onnx(child):
            return child
        for grandchild in child.iterdir():
            if grandchild.is_dir() and grandchild.name != ".cache" and _has_required_onnx(grandchild):
                return grandchild
    return None


def _normalize_onnx_layout(models_dir: Path) -> None:
    found_dir = _find_onnx_dir(models_dir)
    if not found_dir or found_dir == models_dir:
        return
    print(f"[VoxCPM] Normalizing ONNX layout: {found_dir} -> {models_dir}")
    models_dir.mkdir(parents=True, exist_ok=True)
    for item in found_dir.iterdir():
        if not item.is_file():
            continue
        destination = models_dir / item.name
        if destination.exists():
            continue
        shutil.move(str(item), str(destination))
    try:
        found_dir.rmdir()
    except OSError:
        pass


def _ensure_voices(repo_dir: Path, voices_file: Path, voice_name: str | None) -> None:
    if voices_file.is_file():
        if not voice_name:
            return
        try:
            data = json.loads(voices_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        entry = data.get(voice_name) if isinstance(data, dict) else None
        prompt_audio = None
        if isinstance(entry, dict):
            prompt_audio = entry.get("prompt_audio")
        if prompt_audio:
            prompt_audio_path = Path(prompt_audio)
            if not prompt_audio_path.is_absolute():
                prompt_audio_path = voices_file.parent / prompt_audio_path
            if prompt_audio_path.exists():
                return

    script = repo_dir / "download_reference_voices.py"
    if not script.is_file():
        print("[VoxCPM] download_reference_voices.py not found; skip voice download.")
        return

    try:
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--output-dir",
                str(repo_dir / "reference"),
                "--voices-file",
                str(voices_file),
                "--reset",
            ],
            check=True,
        )
    except Exception as exc:
        print(f"[VoxCPM] Voice download failed: {exc}")


def main() -> int:
    config_path = Path(os.environ.get("CONFIG_PATH", "/app/config/config.yaml"))
    config = _load_config(config_path)

    audio = config.get("audio", {}) if isinstance(config, dict) else {}
    tts = audio.get("tts", {}) if isinstance(audio, dict) else {}

    provider = os.environ.get("INDEXTTS_PROVIDER") or tts.get("provider", "")
    if str(provider).lower() != "voxcpm_onnx":
        return 0

    voxcpm_cfg = tts.get("voxcpm", {}) if isinstance(tts, dict) else {}

    repo_dir = Path(os.environ.get("VOXCPM_REPO_DIR") or voxcpm_cfg.get("repo_dir", "models/ONNX_Lab"))
    if not repo_dir.is_absolute():
        repo_dir = (Path.cwd() / repo_dir).resolve()
    repo_url = os.environ.get("VOXCPM_REPO_URL") or "https://github.com/realAllenSong/ONNX_Lab"

    print(f"[VoxCPM] Repo dir: {repo_dir}")
    if not _safe_clone(repo_url, repo_dir):
        print("[VoxCPM] Repo not available; cannot ensure assets.")
        return 0

    models_dir = _resolve_path(
        repo_dir,
        os.environ.get("VOXCPM_MODELS_DIR", "") or voxcpm_cfg.get("models_dir", ""),
        "models/onnx_models_quantized",
    )
    voxcpm_dir = _resolve_path(
        repo_dir,
        os.environ.get("VOXCPM_VOXCPM_DIR", "") or voxcpm_cfg.get("voxcpm_dir", ""),
        "models/VoxCPM1.5",
    )
    voices_file = _resolve_path(
        repo_dir,
        os.environ.get("VOXCPM_VOICES_FILE", "") or voxcpm_cfg.get("voices_file", ""),
        "voices.json",
    )
    voice_name = os.environ.get("VOXCPM_VOICE") or voxcpm_cfg.get("voice", "")

    auto_onnx = _env_bool("AUTO_DOWNLOAD_VOXCPM_ONNX", True)
    auto_model = _env_bool("AUTO_DOWNLOAD_VOXCPM_MODEL", True)
    force_onnx = _env_bool("VOXCPM_ONNX_FORCE", False)

    _normalize_onnx_layout(models_dir)

    if auto_onnx and (force_onnx or not _has_required_onnx(models_dir)):
        models_dir.mkdir(parents=True, exist_ok=True)
        onnx_repo = os.environ.get("VOXCPM_ONNX_REPO") or "Oulasong/voxcpm-onnx"
        onnx_url = os.environ.get("VOXCPM_ONNX_URL") or ""
        onnx_revision = os.environ.get("VOXCPM_ONNX_REVISION") or None

        downloaded = False
        if onnx_repo:
            print(f"[VoxCPM] Downloading ONNX from HF: {onnx_repo}")
            downloaded = _download_hf_snapshot(onnx_repo, models_dir, onnx_revision)
        elif onnx_url:
            print(f"[VoxCPM] Downloading ONNX archive: {onnx_url}")
            downloaded = _download_archive(onnx_url, models_dir)

        if downloaded:
            _normalize_onnx_layout(models_dir)
        if not _has_required_onnx(models_dir):
            print("[VoxCPM] ONNX models incomplete; please populate models_dir manually.")

    if auto_model and not _has_tokenizer(voxcpm_dir):
        try:
            from huggingface_hub import snapshot_download
        except Exception as exc:
            print(f"[VoxCPM] huggingface_hub unavailable: {exc}")
        else:
            repo_id = os.environ.get("VOXCPM_MODEL_REPO") or "openbmb/VoxCPM1.5"
            print(f"[VoxCPM] Downloading VoxCPM weights: {repo_id}")
            voxcpm_dir.mkdir(parents=True, exist_ok=True)
            try:
                snapshot_download(
                    repo_id=repo_id,
                    local_dir=str(voxcpm_dir),
                    local_dir_use_symlinks=False,
                )
            except Exception as exc:
                print(f"[VoxCPM] VoxCPM weight download failed: {exc}")

    _ensure_voices(repo_dir, voices_file, voice_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
