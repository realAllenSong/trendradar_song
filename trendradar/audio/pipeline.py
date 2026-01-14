# coding=utf-8
"""
Audio summary pipeline.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from trendradar.report.helpers import clean_title


@dataclass
class AudioResult:
    audio_path: Optional[str]
    chapters_path: Optional[str]
    generated: bool


DEFAULT_SUMMARY_PROMPT = """
你是新闻播报助手，请根据提供的多平台信息，输出 JSON。
要求：
- summary: 2-3 句，保持中立。
- short_summary: 1 句，保持中立。
- priority_score: 0-100。
- title: 事件标题（简短）。
只输出 JSON，不要多余文本。
"""

DEFAULT_DEDUPE_PROMPT = """
你是文本去重助手，请对输入的新闻播报文本列表去重，只删除重复或明显近似的条目。
要求：
- 保持原始顺序。
- 输出文本应为可朗读内容，避免无意义符号。
- 只返回 JSON，不要多余文本。
- 输出格式: {"items":[{"id":0,"text":"..."}]}
"""


def maybe_generate_audio(report_data: Dict, config: Dict) -> Optional[AudioResult]:
    audio_cfg = config.get("AUDIO", {})
    if not audio_cfg.get("ENABLED", False):
        return None

    output_cfg = audio_cfg.get("OUTPUT", {})
    output_dir = Path(output_cfg.get("DIR", "output/audio"))
    public_dir = Path(output_cfg.get("PUBLIC_DIR", "audio"))
    filename = output_cfg.get("FILENAME", "latest.mp3")
    chapters_filename = output_cfg.get("CHAPTERS_FILENAME", "chapters.json")
    transcript_filename = output_cfg.get("TRANSCRIPT_FILENAME", "transcript.txt")

    output_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    output_audio_path = output_dir / filename
    public_audio_path = public_dir / filename
    output_chapters_path = output_dir / chapters_filename
    public_chapters_path = public_dir / chapters_filename
    output_transcript_path = output_dir / transcript_filename
    transcript_path = public_dir / transcript_filename

    interval_hours = audio_cfg.get("INTERVAL_HOURS", 12)
    force_generate = (
        not public_audio_path.exists()
        or not public_chapters_path.exists()
        or not transcript_path.exists()
    )
    if not force_generate and not _should_generate_audio(public_audio_path, interval_hours):
        try:
            last_time = datetime.fromtimestamp(public_audio_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            last_time = "unknown"
        print(
            f"[音频播报] 跳过生成：间隔未到({interval_hours}h)，最近音频 {last_time}"
        )
        return AudioResult(str(public_audio_path), str(public_chapters_path), generated=False)

    gemini_key = audio_cfg.get("GEMINI_API_KEY", "").strip()
    tts_cfg = audio_cfg.get("TTS", {})
    tts_endpoint = tts_cfg.get("ENDPOINT", "").strip()
    provider = (tts_cfg.get("PROVIDER") or "").strip().lower()
    use_local_tts = provider in {"sherpa_onnx", "sherpa", "kokoro", "voxcpm_onnx"}

    if not gemini_key:
        print("[音频播报] 未配置 GEMINI_API_KEY，跳过音频生成")
        return None
    if not use_local_tts and not tts_endpoint:
        print("[音频播报] 未配置 TTS endpoint，跳过音频生成")
        return None

    items = _flatten_report_items(report_data)
    if not items:
        print("[音频播报] 无可用新闻数据")
        return None

    session = requests.Session()
    session.headers.update({
        "User-Agent": "TrendRadarAudio/1.0 (+https://github.com/sansan0/TrendRadar)"
    })

    try:
        _enrich_items_with_content(items, session, audio_cfg)
        clusters = _cluster_items(items, audio_cfg)
        summaries = _summarize_clusters(clusters, audio_cfg, gemini_key)
        if not summaries:
            print("[音频播报] 摘要生成失败，跳过")
            return None

        segments = _build_script_segments(summaries, config)
        if not segments:
            print("[音频播报] 音频脚本为空，跳过")
            return None

        _write_transcript(segments, transcript_path)
        _write_transcript(segments, output_transcript_path)

        segments = _dedupe_transcript_segments(segments, audio_cfg, gemini_key)
        _write_transcript(segments, transcript_path)
        _write_transcript(segments, output_transcript_path)

        segment_dir = output_dir / "segments"
        segment_dir.mkdir(parents=True, exist_ok=True)

        audio_segments, durations = _synthesize_segments(
            segments,
            segment_dir,
            tts_cfg,
        )
        if not audio_segments:
            print("[音频播报] TTS 生成失败，跳过")
            return None

        assembled = _concat_audio(audio_segments, output_audio_path)
        if not assembled:
            print("[音频播报] 音频合成失败，跳过")
            return None

        if not durations:
            durations = _estimate_durations(segments)

        chapters = _build_chapters(segments, durations)
        _write_chapters(chapters, output_chapters_path)

        shutil.copyfile(output_audio_path, public_audio_path)
        shutil.copyfile(output_chapters_path, public_chapters_path)

        return AudioResult(str(public_audio_path), str(public_chapters_path), generated=True)
    except Exception as exc:
        print(f"[音频播报] 生成失败: {exc}")
        return None
    finally:
        session.close()


def _should_generate_audio(audio_path: Path, interval_hours: int) -> bool:
    if interval_hours <= 0:
        return True
    if not audio_path.exists():
        return True
    last_time = audio_path.stat().st_mtime
    return (time.time() - last_time) >= interval_hours * 3600


def _flatten_report_items(report_data: Dict) -> List[Dict]:
    items: List[Dict] = []
    for stat in report_data.get("stats", []):
        keyword = stat.get("word", "")
        for title_data in stat.get("titles", []):
            title = title_data.get("title", "").strip()
            if not title:
                continue
            url = title_data.get("mobile_url") or title_data.get("url", "")
            items.append({
                "title": title,
                "url": url,
                "source": title_data.get("source_name", ""),
                "ranks": title_data.get("ranks", []),
                "count": title_data.get("count", 1),
                "time_display": title_data.get("time_display", ""),
                "keyword": keyword,
            })
    return items


def _enrich_items_with_content(items: List[Dict], session: requests.Session, audio_cfg: Dict) -> None:
    timeout = audio_cfg.get("FETCH_TIMEOUT_SECONDS", 5)
    max_bytes = audio_cfg.get("FETCH_MAX_BYTES", 0)
    for item in items:
        url = item.get("url")
        if not url:
            item["content"] = ""
            continue
        item["content"] = _fetch_article_text(session, url, timeout, max_bytes)


def _fetch_article_text(
    session: requests.Session,
    url: str,
    timeout: int,
    max_bytes: int,
) -> str:
    try:
        response = session.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=4096):
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if max_bytes and total >= max_bytes:
                break
        html = b"".join(chunks).decode("utf-8", errors="ignore")
        return _strip_html(html)
    except Exception:
        return ""


def _strip_html(html: str) -> str:
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _cluster_items(items: List[Dict], audio_cfg: Dict) -> List[Dict]:
    fuzzy_threshold = audio_cfg.get("FUZZY_SIM_THRESHOLD", 90)
    embedding_threshold = audio_cfg.get("EMBEDDING_SIM_THRESHOLD", 0.82)
    model_name = audio_cfg.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

    try:
        from rapidfuzz import fuzz
    except ImportError:
        print("[音频播报] 未安装 rapidfuzz，跳过聚类")
        return [{"items": items}]

    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        print("[音频播报] 未安装 sentence-transformers，跳过语义聚类")
        return _cluster_by_fuzzy(items, fuzz, fuzzy_threshold)

    fuzzy_clusters = _cluster_by_fuzzy(items, fuzz, fuzzy_threshold)
    if len(fuzzy_clusters) <= 1:
        return fuzzy_clusters

    model = SentenceTransformer(model_name)

    embeddings = []
    for cluster in fuzzy_clusters:
        for item in cluster["items"]:
            text = _embedding_text(item)
            embedding = model.encode(text, normalize_embeddings=True)
            item["_embedding"] = embedding
            embeddings.append(embedding)

    merged_clusters: List[Dict] = []

    for cluster in fuzzy_clusters:
        centroid = _cluster_centroid(cluster, np)
        merged = False
        for target in merged_clusters:
            target_centroid = target.get("_centroid")
            if target_centroid is None:
                continue
            similarity = float(np.dot(centroid, target_centroid))
            if similarity >= embedding_threshold:
                target["items"].extend(cluster["items"])
                target["_centroid"] = _cluster_centroid(target, np)
                merged = True
                break
        if not merged:
            cluster["_centroid"] = centroid
            merged_clusters.append(cluster)

    return merged_clusters


def _cluster_by_fuzzy(items: List[Dict], fuzz, threshold: float) -> List[Dict]:
    clusters: List[Dict] = []
    for item in items:
        normalized = _normalize_title(item["title"])
        matched = False
        for cluster in clusters:
            if fuzz.ratio(normalized, cluster["_norm"]) >= threshold:
                cluster["items"].append(item)
                matched = True
                break
        if not matched:
            clusters.append({"items": [item], "_norm": normalized})
    return clusters


def _normalize_title(title: str) -> str:
    cleaned = clean_title(title).lower()
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _embedding_text(item: Dict) -> str:
    content = item.get("content", "") or ""
    trimmed = content[:500]
    return f"{item.get('title', '')}\n{trimmed}"


def _cluster_centroid(cluster: Dict, np):
    vectors = [item.get("_embedding") for item in cluster["items"] if item.get("_embedding") is not None]
    if not vectors:
        return None
    return np.mean(vectors, axis=0)


def _summarize_clusters(clusters: List[Dict], audio_cfg: Dict, api_key: str) -> List[Dict]:
    try:
        from google import genai
    except ImportError:
        print("[音频播报] 未安装 google-genai，跳过")
        return []

    model_name = audio_cfg.get("GEMINI_MODEL", "gemini-3-flash-preview")
    summary_prompt = (audio_cfg.get("SUMMARY_PROMPT") or "").strip() or DEFAULT_SUMMARY_PROMPT.strip()
    client = genai.Client(api_key=api_key)

    summaries = []
    for cluster in clusters:
        items = cluster.get("items", [])
        if not items:
            continue
        summary = _summarize_cluster(client, model_name, items, summary_prompt)
        if summary:
            summaries.append(summary)

    return summaries


def _dedupe_transcript_segments(segments: List[Dict], audio_cfg: Dict, api_key: str) -> List[Dict]:
    if not audio_cfg.get("DEDUP_ENABLED", True):
        return segments
    if len(segments) < 3:
        return segments

    items = []
    for idx, segment in enumerate(segments):
        text = segment.get("text", "").strip()
        if not text:
            continue
        items.append({"id": idx, "text": text})

    if len(items) < 3:
        return segments

    try:
        from google import genai
    except ImportError:
        print("[音频播报] 未安装 google-genai，跳过去重")
        return segments

    model_name = audio_cfg.get("GEMINI_MODEL", "gemini-1.5-flash")
    dedupe_prompt = (audio_cfg.get("DEDUP_PROMPT") or "").strip() or DEFAULT_DEDUPE_PROMPT.strip()

    client = genai.Client(api_key=api_key)
    request_text = f"{dedupe_prompt}\n数据: {json.dumps(items, ensure_ascii=False)}"

    try:
        try:
            from google.genai import types
        except Exception:
            types = None

        if types is not None:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=request_text,
                    config=types.GenerateContentConfig(temperature=0.1),
                )
            except TypeError:
                response = client.models.generate_content(
                    model=model_name,
                    contents=request_text,
                )
        else:
            response = client.models.generate_content(
                model=model_name,
                contents=request_text,
            )
        text = (getattr(response, "text", "") or "").strip()
    except Exception:
        return segments

    data = _safe_json_from_text(text)
    if not data:
        return segments

    keep_ids = None
    rewrite_map: Dict[int, str] = {}
    if isinstance(data.get("keep_ids"), list):
        keep_ids = data.get("keep_ids")
    elif isinstance(data.get("items"), list):
        keep_ids = []
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            keep_ids.append(item.get("id"))
            text_value = item.get("text")
            if text_value:
                try:
                    rewrite_map[int(item.get("id"))] = str(text_value)
                except (TypeError, ValueError):
                    continue

    if not keep_ids:
        return segments

    keep_set = set()
    for value in keep_ids:
        try:
            keep_set.add(int(value))
        except (TypeError, ValueError):
            continue

    if not keep_set:
        return segments

    filtered = []
    for idx, segment in enumerate(segments):
        if idx not in keep_set:
            continue
        updated = dict(segment)
        if idx in rewrite_map:
            updated_text = _sanitize_chinese_text(rewrite_map[idx])
            if not updated_text:
                updated_text = "该条新闻无法翻译，建议查看原文。"
            updated["text"] = updated_text
        else:
            updated_text = _sanitize_chinese_text(updated.get("text", ""))
            if not updated_text:
                updated_text = "该条新闻无法翻译，建议查看原文。"
            updated["text"] = updated_text
        filtered.append(updated)
    if not filtered:
        return segments

    if len(filtered) != len(segments):
        print(f"[音频播报] 去重后保留 {len(filtered)}/{len(segments)} 条")
    return filtered


def _summarize_cluster(client, model_name: str, items: List[Dict], prompt: str) -> Optional[Dict]:
    sources = sorted({item.get("source", "") for item in items if item.get("source")})
    titles = [item.get("title", "") for item in items if item.get("title")]
    sample_title = titles[0] if titles else ""

    min_rank = min((min(item.get("ranks") or [999]) for item in items), default=999)
    max_rank = max((max(item.get("ranks") or [0]) for item in items), default=0)
    total_count = sum(item.get("count", 1) for item in items)
    source_count = len(sources)

    snippets = []
    for item in items[:6]:
        snippet = item.get("content", "")[:300]
        snippets.append({
            "title": item.get("title", ""),
            "snippet": snippet,
            "source": item.get("source", ""),
        })

    payload = {
        "sample_title": sample_title,
        "sources": sources,
        "stats": {
            "min_rank": min_rank,
            "max_rank": max_rank,
            "total_count": total_count,
            "source_count": source_count,
        },
        "items": snippets,
    }

    try:
        request_text = f"{prompt}\n数据: {json.dumps(payload, ensure_ascii=False)}"
        try:
            from google.genai import types
        except Exception:
            types = None

        if types is not None:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=request_text,
                    config=types.GenerateContentConfig(temperature=0.3),
                )
            except TypeError:
                response = client.models.generate_content(
                    model=model_name,
                    contents=request_text,
                )
        else:
            response = client.models.generate_content(
                model=model_name,
                contents=request_text,
            )

        text = (getattr(response, "text", "") or "").strip()
        data = _safe_json_from_text(text)
        if not data:
            return None
        if "title" not in data:
            data["title"] = sample_title
        if "short_summary" not in data:
            data["short_summary"] = data.get("summary", "")
        data["sources"] = sources
        data["priority_score"] = float(data.get("priority_score", 0))
        return data
    except Exception:
        return None


def _safe_json_from_text(text: str) -> Optional[Dict]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _sanitize_chinese_text(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _build_script_segments(summaries: List[Dict], config: Dict) -> List[Dict]:
    if not summaries:
        return []

    summaries_sorted = sorted(summaries, key=lambda s: s.get("priority_score", 0), reverse=True)
    high_count = max(1, math.ceil(len(summaries_sorted) * 0.3))

    segments = []
    intro = (
        f"欢迎来到今日的热点简报。"
    )
    segments.append({"text": intro, "chapter": None})

    for idx, item in enumerate(summaries_sorted):
        is_high = idx < high_count
        summary_text = item.get("summary", "") if is_high else item.get("short_summary", "")
        if not summary_text:
            summary_text = item.get("summary", "") or item.get("short_summary", "") or item.get("title", "")

        if not summary_text:
            continue

        segments.append({
            "text": summary_text,
            "chapter": {
                "title": item.get("title", "") or item.get("sample_title", "事件更新"),
                "sources": item.get("sources", []),
            },
        })

    outro = "以上是今天的热点简报，本播报来源于公开信息，内容可能需要核实。"
    segments.append({"text": outro, "chapter": None})

    return segments


def _write_transcript(segments: List[Dict], path: Path) -> None:
    lines = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if text:
            lines.append(text)
    if not lines:
        return
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _synthesize_segments(segments: List[Dict], segment_dir: Path, tts_cfg: Dict) -> Tuple[List[Path], List[float]]:
    endpoint = tts_cfg.get("ENDPOINT", "")
    provider = (tts_cfg.get("PROVIDER") or "").strip().lower()

    if provider in {"sherpa_onnx", "sherpa"}:
        return _synthesize_segments_sherpa_onnx(segments, segment_dir, tts_cfg)
    if provider == "kokoro":
        return _synthesize_segments_kokoro(segments, segment_dir, tts_cfg)
    if provider == "voxcpm_onnx":
        return _synthesize_segments_voxcpm_onnx(segments, segment_dir, tts_cfg)

    if _is_hf_space_endpoint(endpoint, provider):
        audio_segments, durations = _synthesize_segments_hf_space(segments, segment_dir, endpoint)
        if audio_segments:
            return audio_segments, durations
        return _synthesize_segments_gradio(segments, segment_dir, endpoint)

    return _synthesize_segments_http(segments, segment_dir, tts_cfg)


def _synthesize_segments_http(
    segments: List[Dict],
    segment_dir: Path,
    tts_cfg: Dict,
) -> Tuple[List[Path], List[float]]:
    audio_segments = []
    durations = []

    endpoint = tts_cfg.get("ENDPOINT", "")
    api_key = tts_cfg.get("API_KEY", "")
    voice = tts_cfg.get("VOICE", "default")
    output_format = tts_cfg.get("FORMAT", "mp3")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for idx, segment in enumerate(segments):
        text = segment.get("text", "")
        if not text:
            continue
        payload = {"text": text, "voice": voice, "format": output_format}
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            audio_data = response.content
            segment_path = segment_dir / f"segment_{idx:03d}.{output_format}"
            with open(segment_path, "wb") as handle:
                handle.write(audio_data)
            audio_segments.append(segment_path)
            durations.append(_probe_duration(segment_path))
        except Exception:
            continue

    return audio_segments, durations


def _synthesize_segments_voxcpm_onnx(
    segments: List[Dict],
    segment_dir: Path,
    tts_cfg: Dict,
) -> Tuple[List[Path], List[float]]:
    voxcpm_cfg = tts_cfg.get("VOXCPM", {})

    repo_dir_raw = (voxcpm_cfg.get("REPO_DIR") or "").strip()
    infer_path_raw = (voxcpm_cfg.get("INFER_PATH") or "").strip()

    def _abs_path(path: Path) -> Path:
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()

    if infer_path_raw:
        infer_path = _abs_path(Path(infer_path_raw))
        base_dir = infer_path.parent
    elif repo_dir_raw:
        base_dir = _abs_path(Path(repo_dir_raw))
        infer_path = base_dir / "infer.py"
    else:
        print("[音频播报] 未配置 VoxCPM repo/infer.py，跳过 TTS")
        return [], []

    if not infer_path.is_file():
        print(f"[音频播报] VoxCPM infer.py 不存在: {infer_path}")
        return [], []

    def _resolve_path(value: str, default_rel: str) -> Path:
        if value:
            return _abs_path(Path(value))
        return base_dir / default_rel

    models_dir = _resolve_path((voxcpm_cfg.get("MODELS_DIR") or "").strip(), "models/onnx_models_quantized")
    voxcpm_dir = _resolve_path((voxcpm_cfg.get("VOXCPM_DIR") or "").strip(), "models/VoxCPM1.5")
    voices_file = _resolve_path((voxcpm_cfg.get("VOICES_FILE") or "").strip(), "voices.json")

    voice = (voxcpm_cfg.get("VOICE") or "").strip()
    if not voice:
        print("[音频播报] 未配置 VoxCPM voice，跳过 TTS")
        return [], []

    if not models_dir.is_dir():
        print(f"[音频播报] VoxCPM models_dir 不存在: {models_dir}")
        return [], []
    if not voxcpm_dir.is_dir():
        print(f"[音频播报] VoxCPM voxcpm_dir 不存在: {voxcpm_dir}")
        return [], []
    if not voices_file.is_file():
        print(f"[音频播报] VoxCPM voices_file 不存在: {voices_file}")
        return [], []

    max_threads = voxcpm_cfg.get("MAX_THREADS")
    text_normalizer = voxcpm_cfg.get("TEXT_NORMALIZER", True)
    audio_normalizer = voxcpm_cfg.get("AUDIO_NORMALIZER", False)
    cfg_value = voxcpm_cfg.get("CFG_VALUE")
    fixed_timesteps = voxcpm_cfg.get("FIXED_TIMESTEPS")
    seed = voxcpm_cfg.get("SEED")
    batch_mode = voxcpm_cfg.get("BATCH_MODE", True)

    base_config: Dict[str, object] = {
        "models_dir": str(models_dir),
        "voxcpm_dir": str(voxcpm_dir),
        "voices_file": str(voices_file),
        "voice": voice,
        "prompt_audio": None,
        "prompt_text": None,
        "text_normalizer": bool(text_normalizer),
        "audio_normalizer": bool(audio_normalizer),
    }

    if max_threads is not None:
        try:
            base_config["max_threads"] = int(max_threads)
        except (TypeError, ValueError):
            pass
    if cfg_value is not None:
        try:
            base_config["cfg_value"] = float(cfg_value)
        except (TypeError, ValueError):
            pass
    if fixed_timesteps is not None:
        try:
            base_config["fixed_timesteps"] = int(fixed_timesteps)
        except (TypeError, ValueError):
            pass
    if seed is not None:
        try:
            base_config["seed"] = int(seed)
        except (TypeError, ValueError):
            pass

    if batch_mode:
        texts = [segment.get("text", "").strip() for segment in segments if segment.get("text", "").strip()]
        if not texts:
            return [], []
        output_path = segment_dir / "voxcpm_batch.wav"
        config_path = segment_dir / "voxcpm_batch.json"
        run_config = dict(base_config)
        run_config["text"] = texts
        run_config["output"] = str(output_path)
        config_path.write_text(
            json.dumps(run_config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(infer_path), "--config", str(config_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or "unknown error"
            print(f"[音频播报] VoxCPM TTS 失败: {detail}")
            return [], []

        return [output_path], _estimate_durations(segments)

    audio_segments: List[Path] = []
    durations: List[float] = []

    for idx, segment in enumerate(segments):
        text = segment.get("text", "").strip()
        if not text:
            continue
        segment_path = segment_dir / f"segment_{idx:03d}.wav"
        config_path = segment_dir / f"voxcpm_config_{idx:03d}.json"
        run_config = dict(base_config)
        run_config["text"] = text
        run_config["output"] = str(segment_path)
        config_path.write_text(
            json.dumps(run_config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(infer_path), "--config", str(config_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or "unknown error"
            print(f"[音频播报] VoxCPM TTS 失败: {detail}")
            continue

        audio_segments.append(segment_path)
        durations.append(_probe_duration(segment_path))

    return audio_segments, durations


def _synthesize_segments_gradio(
    segments: List[Dict],
    segment_dir: Path,
    endpoint: str,
) -> Tuple[List[Path], List[float]]:
    try:
        from gradio_client import Client
    except ImportError:
        print("[音频播报] 未安装 gradio_client，跳过 IndexTTS Space 调用")
        return [], []

    endpoint = _normalize_space_endpoint(endpoint)
    client = Client(endpoint)

    audio_segments = []
    durations = []
    for idx, segment in enumerate(segments):
        text = segment.get("text", "")
        if not text:
            continue
        try:
            result = client.predict(*_default_space_args(text), api_name="/gen_single")
            segment_path = _materialize_gradio_audio(result, segment_dir, idx)
            if not segment_path:
                continue
            audio_segments.append(segment_path)
            durations.append(_probe_duration(segment_path))
        except Exception:
            continue

    return audio_segments, durations


def _synthesize_segments_sherpa_onnx(
    segments: List[Dict],
    segment_dir: Path,
    tts_cfg: Dict,
) -> Tuple[List[Path], List[float]]:
    try:
        import sherpa_onnx
    except ImportError:
        print("[音频播报] 未安装 sherpa-onnx，跳过 TTS")
        return [], []

    model_cfg = tts_cfg.get("SHERPA_ONNX", {})
    if not model_cfg:
        print("[音频播报] 未配置 Sherpa-ONNX，跳过 TTS")
        return [], []

    model_dir = model_cfg.get("MODEL_DIR", "")
    matcha_model = _resolve_model_path(model_dir, model_cfg.get("ACOUSTIC_MODEL", ""))
    vocoder = _resolve_model_path(model_dir, model_cfg.get("VOCODER", ""))
    tokens = _resolve_model_path(model_dir, model_cfg.get("TOKENS", ""))
    lexicon = _resolve_model_path(model_dir, model_cfg.get("LEXICON", ""))
    data_dir = _resolve_model_path(model_dir, model_cfg.get("DATA_DIR", ""))

    rule_fsts = _resolve_rule_fsts(model_dir, model_cfg.get("RULE_FSTS", ""))

    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=matcha_model,
                vocoder=vocoder,
                lexicon=lexicon,
                tokens=tokens,
                data_dir=data_dir,
            ),
            provider=model_cfg.get("PROVIDER", "cpu"),
            num_threads=int(model_cfg.get("NUM_THREADS", 2)),
            debug=False,
        ),
        rule_fsts=rule_fsts,
        max_num_sentences=int(model_cfg.get("MAX_NUM_SENTENCES", 0)),
    )

    if not tts_config.validate():
        print("[音频播报] Sherpa-ONNX 配置校验失败")
        return [], []

    tts = sherpa_onnx.OfflineTts(tts_config)
    sid = int(model_cfg.get("SID", 0))
    speed = float(model_cfg.get("SPEED", 1.0))

    audio_segments = []
    durations = []
    for idx, segment in enumerate(segments):
        text = segment.get("text", "").strip()
        if not text:
            continue
        audio = tts.generate(text, sid=sid, speed=speed)
        if not getattr(audio, "samples", None):
            continue
        segment_path = segment_dir / f"segment_{idx:03d}.wav"
        if _write_wave(segment_path, audio.samples, audio.sample_rate):
            audio_segments.append(segment_path)
            durations.append(len(audio.samples) / audio.sample_rate)

    return audio_segments, durations


def _synthesize_segments_kokoro(
    segments: List[Dict],
    segment_dir: Path,
    tts_cfg: Dict,
) -> Tuple[List[Path], List[float]]:
    try:
        from kokoro import KPipeline
    except ImportError:
        print("[音频播报] 未安装 kokoro，跳过 TTS")
        return [], []

    try:
        import numpy as np
    except ImportError:
        np = None

    kokoro_cfg = tts_cfg.get("KOKORO", {})
    lang_code = kokoro_cfg.get("LANG_CODE", "z")
    voice = kokoro_cfg.get("VOICE", "zm_yunyang")
    speed = float(kokoro_cfg.get("SPEED", 1.0))
    split_pattern = kokoro_cfg.get("SPLIT_PATTERN", r"\n+")
    sample_rate = int(kokoro_cfg.get("SAMPLE_RATE", 24000))

    try:
        pipeline = KPipeline(lang_code=lang_code)
    except Exception:
        print("[音频播报] Kokoro 初始化失败")
        return [], []

    audio_segments = []
    durations = []

    for idx, segment in enumerate(segments):
        text = segment.get("text", "").strip()
        if not text:
            continue
        try:
            generator = pipeline(text, voice=voice, speed=speed, split_pattern=split_pattern)
            chunks = []
            for _, _, audio in generator:
                if audio is None:
                    continue
                chunks.append(audio)
            if not chunks:
                continue

            if np is not None:
                chunks = [np.asarray(chunk, dtype="float32") for chunk in chunks]
                samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            else:
                samples = []
                for chunk in chunks:
                    samples.extend(chunk)

            segment_path = segment_dir / f"segment_{idx:03d}.wav"
            if _write_audio_samples(segment_path, samples, sample_rate):
                audio_segments.append(segment_path)
                durations.append(len(samples) / sample_rate)
        except Exception:
            continue

    return audio_segments, durations


def _synthesize_segments_hf_space(
    segments: List[Dict],
    segment_dir: Path,
    endpoint: str,
) -> Tuple[List[Path], List[float]]:
    base_url = _hf_space_base_url(endpoint)
    if not base_url:
        return [], []

    audio_segments = []
    durations = []

    for idx, segment in enumerate(segments):
        text = segment.get("text", "")
        if not text:
            continue
        try:
            payload = {"data": _default_space_args(text)}
            response = requests.post(
                f"{base_url}/gradio_api/call/gen_single",
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            event_id = response.json().get("event_id")
            if not event_id:
                continue

            result = _read_hf_space_event(base_url, "gen_single", event_id)
            if not result:
                continue

            segment_path = _materialize_gradio_audio(result, segment_dir, idx)
            if not segment_path:
                continue
            audio_segments.append(segment_path)
            durations.append(_probe_duration(segment_path))
        except Exception:
            continue

    return audio_segments, durations


def _is_hf_space_endpoint(endpoint: str, provider: str) -> bool:
    if provider in {"hf_space", "gradio", "space"}:
        return True
    if not endpoint:
        return False
    if endpoint.startswith("hf://"):
        return True
    if endpoint.startswith("http"):
        return "hf.space" in endpoint or "huggingface.co/spaces" in endpoint
    return "/" in endpoint


def _hf_space_base_url(endpoint: str) -> Optional[str]:
    if not endpoint:
        return None

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


def _read_hf_space_event(base_url: str, api_name: str, event_id: str) -> Optional[object]:
    try:
        response = requests.get(
            f"{base_url}/gradio_api/call/{api_name}/{event_id}",
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=180,
        )
        response.raise_for_status()
        current_event = None
        for raw in response.iter_lines(decode_unicode=True):
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


def _normalize_space_endpoint(endpoint: str) -> str:
    if endpoint.startswith("hf://"):
        return endpoint.replace("hf://", "")
    return endpoint


def _resolve_model_path(model_dir: str, path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    if model_dir:
        return str(Path(model_dir) / path_value)
    return str(path)


def _resolve_rule_fsts(model_dir: str, value: str) -> str:
    if not value:
        return ""
    paths = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        paths.append(_resolve_model_path(model_dir, raw))
    return ",".join(paths)


def _write_wave(path: Path, samples, sample_rate: int) -> bool:
    try:
        import numpy as np
    except ImportError:
        np = None

    try:
        if np is not None:
            data = np.asarray(samples, dtype=np.float32)
            data = np.clip(data, -1.0, 1.0)
            pcm = (data * 32767.0).astype(np.int16)
            frames = pcm.tobytes()
        else:
            from array import array

            pcm = array("h")
            for value in samples:
                value = max(-1.0, min(1.0, float(value)))
                pcm.append(int(value * 32767.0))
            frames = pcm.tobytes()

        import wave

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            wav_file.writeframes(frames)
        return True
    except Exception:
        return False


def _write_audio_samples(path: Path, samples, sample_rate: int) -> bool:
    try:
        import soundfile as sf
    except ImportError:
        return _write_wave(path, samples, sample_rate)

    try:
        sf.write(str(path), samples, sample_rate)
        return True
    except Exception:
        return _write_wave(path, samples, sample_rate)


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
    candidate = _extract_gradio_value(result)
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

    if isinstance(candidate, str) and os.path.exists(candidate):
        try:
            shutil.copyfile(candidate, segment_path)
            return segment_path
        except Exception:
            return None

    return None


def _extract_gradio_value(result):
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


def _probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _estimate_durations(segments: List[Dict]) -> List[float]:
    durations = []
    for segment in segments:
        text = segment.get("text", "")
        estimated = max(2.0, len(text) / 6.0)
        durations.append(estimated)
    return durations


def _concat_audio(segment_paths: List[Path], output_path: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("[音频播报] 未找到 ffmpeg，无法合成音频")
        return False

    concat_file = output_path.parent / "concat_list.txt"
    with open(concat_file, "w", encoding="utf-8") as handle:
        for path in segment_paths:
            abs_path = path.resolve()
            handle.write(f"file '{abs_path.as_posix()}'\n")

    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
    ]

    if output_path.suffix.lower() == ".mp3":
        cmd += ["-c:a", "libmp3lame", "-q:a", "4"]
    else:
        cmd += ["-c", "copy"]

    cmd.append(str(output_path))

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception:
        return False


def _build_chapters(segments: List[Dict], durations: List[float]) -> List[Dict]:
    chapters = []
    current = 0.0
    for segment, duration in zip(segments, durations):
        chapter = segment.get("chapter")
        if chapter:
            chapters.append({
                "title": chapter.get("title", ""),
                "start": round(current, 2),
                "sources": chapter.get("sources", []),
            })
        current += duration
    return chapters


def _write_chapters(chapters: List[Dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(chapters, handle, ensure_ascii=False)
