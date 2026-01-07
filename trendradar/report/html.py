# coding=utf-8
"""
HTML 报告渲染模块

提供 HTML 格式的热点新闻报告生成功能
"""

from datetime import datetime
import json
import os
from pathlib import Path
import re
import time
from typing import Dict, List, Optional, Callable
from urllib.parse import urljoin

import requests

from trendradar.report.helpers import html_escape

_PREVIEW_CACHE_PATH = Path("output") / "preview_cache.json"
_PREVIEW_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7
_PREVIEW_FETCH_LIMIT = int(os.environ.get("PREVIEW_IMAGE_LIMIT", "80"))
_PREVIEW_FETCH_TIMEOUT = float(os.environ.get("PREVIEW_IMAGE_TIMEOUT", "5"))
_PLACEHOLDER_IMAGE_DATA_URI = (
    "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI2NDAiIGhlaWdodD0iMzYwIiB2aWV3Qm94PSIwIDAgNjQwIDM2MCI+CiAgPGRlZnM+CiAgICA8bGluZWFyR3JhZGllbnQgaWQ9ImciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwJSIgc3RvcC1jb2xvcj0iI2UwZjJmZSIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiNmZmY3ZWQiLz4KICAgIDwvbGluZWFyR3JhZGllbnQ+CiAgPC9kZWZzPgogIDxyZWN0IHdpZHRoPSI2NDAiIGhlaWdodD0iMzYwIiBmaWxsPSJ1cmwoI2cpIi8+CiAgPHJlY3QgeD0iNDgiIHk9IjU2IiB3aWR0aD0iNTQ0IiBoZWlnaHQ9IjI0OCIgcng9IjMyIiBmaWxsPSIjZmZmZmZmIiBvcGFjaXR5PSIwLjYiLz4KICA8Y2lyY2xlIGN4PSIxOTAiIGN5PSIxODAiIHI9IjY4IiBmaWxsPSIjYmZkYmZlIi8+CiAgPHJlY3QgeD0iMjkwIiB5PSIxMzIiIHdpZHRoPSIyMjAiIGhlaWdodD0iMjgiIHJ4PSIxNCIgZmlsbD0iIzkzYzVmZCIvPgogIDxyZWN0IHg9IjI5MCIgeT0iMTc2IiB3aWR0aD0iMTgwIiBoZWlnaHQ9IjIwIiByeD0iMTAiIGZpbGw9IiNjYmQ1ZjUiLz4KICA8cmVjdCB4PSIyOTAiIHk9IjIxMCIgd2lkdGg9IjE0MCIgaGVpZ2h0PSIxNiIgcng9IjgiIGZpbGw9IiNlMmU4ZjAiLz4KPC9zdmc+"
)

_META_IMAGE_PATTERNS = [
    re.compile(
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
]


def _load_preview_cache() -> Dict[str, Dict[str, str]]:
    if not _PREVIEW_CACHE_PATH.exists():
        return {}
    try:
        with open(_PREVIEW_CACHE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception:
        return {}
    return {}


def _save_preview_cache(cache: Dict[str, Dict[str, str]]) -> None:
    try:
        _PREVIEW_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PREVIEW_CACHE_PATH, "w", encoding="utf-8") as handle:
            json.dump(cache, handle)
    except Exception:
        return


def _extract_preview_image(html: str, base_url: str) -> Optional[str]:
    for pattern in _META_IMAGE_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        raw_url = match.group(1).strip()
        if not raw_url:
            continue
        if raw_url.startswith("data:"):
            continue
        return urljoin(base_url, raw_url)
    return None


def _fetch_preview_image(session: requests.Session, url: str) -> Optional[str]:
    try:
        response = session.get(url, timeout=_PREVIEW_FETCH_TIMEOUT, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return None
        chunks = []
        max_bytes = 200_000
        total = 0
        for chunk in response.iter_content(chunk_size=4096):
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        html = b"".join(chunks).decode("utf-8", errors="ignore")
        return _extract_preview_image(html, url)
    except Exception:
        return None


def _get_preview_image(
    url: str,
    session: requests.Session,
    cache: Dict[str, Dict[str, str]],
    quota: Dict[str, int],
) -> Optional[str]:
    now = int(time.time())
    cached = cache.get(url)
    if cached:
        cached_at = int(cached.get("ts", "0") or 0)
        if now - cached_at < _PREVIEW_CACHE_TTL_SECONDS:
            image = cached.get("image", "")
            return image or None

    if quota["remaining"] <= 0:
        return None

    quota["remaining"] -= 1
    image_url = _fetch_preview_image(session, url)
    cache[url] = {"image": image_url or "", "ts": str(now)}
    return image_url


def render_html_content(
    report_data: Dict,
    total_titles: int,
    is_daily_summary: bool = False,
    mode: str = "daily",
    update_info: Optional[Dict] = None,
    *,
    reverse_content_order: bool = False,
    get_time_func: Optional[Callable[[], datetime]] = None,
    rss_items: Optional[List[Dict]] = None,
    rss_new_items: Optional[List[Dict]] = None,
    display_mode: str = "keyword",
) -> str:
    """渲染HTML内容

    Args:
        report_data: 报告数据字典，包含 stats, new_titles, failed_ids, total_new_count
        total_titles: 新闻总数
        is_daily_summary: 是否为当日汇总
        mode: 报告模式 ("daily", "current", "incremental")
        update_info: 更新信息（可选）
        reverse_content_order: 是否反转内容顺序（新增热点在前）
        get_time_func: 获取当前时间的函数（可选，默认使用 datetime.now）
        rss_items: RSS 统计条目列表（可选）
        rss_new_items: RSS 新增条目列表（可选）
        display_mode: 显示模式 ("keyword"=按关键词分组, "platform"=按平台分组)

    Returns:
        渲染后的 HTML 字符串
    """
    preview_cache = _load_preview_cache()
    preview_quota = {"remaining": _PREVIEW_FETCH_LIMIT}
    preview_session = requests.Session()
    preview_session.headers.update(
        {"User-Agent": "TrendRadarBot/1.0 (+https://github.com/sansan0/TrendRadar)"}
    )
    placeholder_image = _PLACEHOLDER_IMAGE_DATA_URI
    escaped_placeholder_image = html_escape(placeholder_image)
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>热点新闻分析</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Newsreader:wght@400;500;600;700&family=Public+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
                margin: 0;
                padding: 16px;
                background: #fafafa;
                color: #333;
                line-height: 1.5;
            }

            .container {
                max-width: 600px;
                margin: 0 auto;
                background: white;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 2px 16px rgba(0,0,0,0.06);
            }

            .header {
                background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                color: white;
                padding: 32px 24px;
                text-align: center;
                position: relative;
            }

            .save-buttons {
                position: absolute;
                top: 16px;
                right: 16px;
                display: flex;
                gap: 8px;
            }

            .save-btn {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 13px;
                font-weight: 500;
                transition: all 0.2s ease;
                backdrop-filter: blur(10px);
                white-space: nowrap;
            }

            .save-btn:hover {
                background: rgba(255, 255, 255, 0.3);
                border-color: rgba(255, 255, 255, 0.5);
                transform: translateY(-1px);
            }

            .save-btn:active {
                transform: translateY(0);
            }

            .save-btn:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }

            .header-title {
                font-size: 22px;
                font-weight: 700;
                margin: 0 0 20px 0;
            }

            .header-info {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
                font-size: 14px;
                opacity: 0.95;
            }

            .info-item {
                text-align: center;
            }

            .info-label {
                display: block;
                font-size: 12px;
                opacity: 0.8;
                margin-bottom: 4px;
            }

            .info-value {
                font-weight: 600;
                font-size: 16px;
            }

            .content {
                padding: 24px;
            }

            .word-group {
                margin-bottom: 40px;
            }

            .word-group:first-child {
                margin-top: 0;
            }

            .word-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 20px;
                padding-bottom: 8px;
                border-bottom: 1px solid #f0f0f0;
            }

            .word-info {
                display: flex;
                align-items: center;
                gap: 12px;
            }

            .word-name {
                font-size: 17px;
                font-weight: 600;
                color: #1a1a1a;
            }

            .word-count {
                color: #666;
                font-size: 13px;
                font-weight: 500;
            }

            .word-count.hot { color: #dc2626; font-weight: 600; }
            .word-count.warm { color: #ea580c; font-weight: 600; }

            .word-index {
                color: #999;
                font-size: 12px;
            }

            .news-item {
                margin-bottom: 20px;
                padding: 16px 0;
                border-bottom: 1px solid #f5f5f5;
                position: relative;
                display: flex;
                gap: 12px;
                align-items: center;
            }

            .news-item:last-child {
                border-bottom: none;
            }

            .news-item.new::after {
                content: "NEW";
                position: absolute;
                top: 12px;
                right: 0;
                background: #fbbf24;
                color: #92400e;
                font-size: 9px;
                font-weight: 700;
                padding: 3px 6px;
                border-radius: 4px;
                letter-spacing: 0.5px;
            }

            .news-number {
                color: #999;
                font-size: 13px;
                font-weight: 600;
                min-width: 20px;
                text-align: center;
                flex-shrink: 0;
                background: #f8f9fa;
                border-radius: 50%;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                align-self: flex-start;
                margin-top: 8px;
            }

            .news-content {
                flex: 1;
                min-width: 0;
                padding-right: 40px;
            }

            .news-item.new .news-content {
                padding-right: 50px;
            }

            .news-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 8px;
                flex-wrap: wrap;
            }

            .source-name {
                color: #666;
                font-size: 12px;
                font-weight: 500;
            }

            .keyword-tag {
                color: #2563eb;
                font-size: 12px;
                font-weight: 500;
                background: #eff6ff;
                padding: 2px 6px;
                border-radius: 4px;
            }

            .rank-num {
                color: #fff;
                background: #6b7280;
                font-size: 10px;
                font-weight: 700;
                padding: 2px 6px;
                border-radius: 10px;
                min-width: 18px;
                text-align: center;
            }

            .rank-num.top { background: #dc2626; }
            .rank-num.high { background: #ea580c; }

            .time-info {
                color: #999;
                font-size: 11px;
            }

            .count-info {
                color: #059669;
                font-size: 11px;
                font-weight: 500;
            }

            .news-title {
                font-size: 15px;
                line-height: 1.4;
                color: #1a1a1a;
                margin: 0;
            }

            .news-link {
                color: #2563eb;
                text-decoration: none;
            }

            .news-link:hover {
                text-decoration: underline;
            }

            .news-link:visited {
                color: #7c3aed;
            }

            .new-section {
                margin-top: 40px;
                padding-top: 24px;
                border-top: 2px solid #f0f0f0;
            }

            .new-section-title {
                color: #1a1a1a;
                font-size: 16px;
                font-weight: 600;
                margin: 0 0 20px 0;
            }

            .new-source-group {
                margin-bottom: 24px;
            }

            .new-source-title {
                color: #666;
                font-size: 13px;
                font-weight: 500;
                margin: 0 0 12px 0;
                padding-bottom: 6px;
                border-bottom: 1px solid #f5f5f5;
            }

            .new-item {
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 8px 0;
                border-bottom: 1px solid #f9f9f9;
            }

            .new-item:last-child {
                border-bottom: none;
            }

            .new-item-number {
                color: #999;
                font-size: 12px;
                font-weight: 600;
                min-width: 18px;
                text-align: center;
                flex-shrink: 0;
                background: #f8f9fa;
                border-radius: 50%;
                width: 20px;
                height: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .new-item-rank {
                color: #fff;
                background: #6b7280;
                font-size: 10px;
                font-weight: 700;
                padding: 3px 6px;
                border-radius: 8px;
                min-width: 20px;
                text-align: center;
                flex-shrink: 0;
            }

            .new-item-rank.top { background: #dc2626; }
            .new-item-rank.high { background: #ea580c; }

            .new-item-content {
                flex: 1;
                min-width: 0;
            }

            .new-item-title {
                font-size: 14px;
                line-height: 1.4;
                color: #1a1a1a;
                margin: 0;
            }

            .error-section {
                background: #fef2f2;
                border: 1px solid #fecaca;
                border-radius: 8px;
                padding: 16px;
                margin-bottom: 24px;
            }

            .error-title {
                color: #dc2626;
                font-size: 14px;
                font-weight: 600;
                margin: 0 0 8px 0;
            }

            .error-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }

            .error-item {
                color: #991b1b;
                font-size: 13px;
                padding: 2px 0;
                font-family: 'SF Mono', Consolas, monospace;
            }

            .footer {
                margin-top: 32px;
                padding: 20px 24px;
                background: #f8f9fa;
                border-top: 1px solid #e5e7eb;
                text-align: center;
            }

            .footer-content {
                font-size: 13px;
                color: #6b7280;
                line-height: 1.6;
            }

            .footer-link {
                color: #4f46e5;
                text-decoration: none;
                font-weight: 500;
                transition: color 0.2s ease;
            }

            .footer-link:hover {
                color: #7c3aed;
                text-decoration: underline;
            }

            .project-name {
                font-weight: 600;
                color: #374151;
            }

            @media (max-width: 480px) {
                body { padding: 12px; }
                .header { padding: 24px 20px; }
                .content { padding: 20px; }
                .footer { padding: 16px 20px; }
                .header-info { grid-template-columns: 1fr; gap: 12px; }
                .news-header { gap: 6px; }
                .news-content { padding-right: 45px; }
                .news-item { gap: 8px; }
                .new-item { gap: 8px; }
                .news-number { width: 20px; height: 20px; font-size: 12px; }
                .save-buttons {
                    position: static;
                    margin-bottom: 16px;
                    display: flex;
                    gap: 8px;
                    justify-content: center;
                    flex-direction: column;
                    width: 100%;
                }
                .save-btn {
                    width: 100%;
                }
            }

            /* RSS 订阅内容样式 */
            .rss-section {
                margin-top: 32px;
                padding-top: 24px;
                border-top: 2px solid #e5e7eb;
            }

            .rss-section-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 20px;
            }

            .rss-section-title {
                font-size: 18px;
                font-weight: 600;
                color: #059669;
            }

            .rss-section-count {
                color: #6b7280;
                font-size: 14px;
            }

            .feed-group {
                margin-bottom: 24px;
            }

            .feed-group:last-child {
                margin-bottom: 0;
            }

            .feed-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 12px;
                padding-bottom: 8px;
                border-bottom: 2px solid #10b981;
            }

            .feed-name {
                font-size: 15px;
                font-weight: 600;
                color: #059669;
            }

            .feed-count {
                color: #666;
                font-size: 13px;
                font-weight: 500;
            }

            .rss-item {
                margin-bottom: 12px;
                padding: 14px;
                background: #f0fdf4;
                border-radius: 8px;
                border-left: 3px solid #10b981;
            }

            .rss-item:last-child {
                margin-bottom: 0;
            }

            .rss-meta {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-bottom: 6px;
                flex-wrap: wrap;
            }

            .rss-time {
                color: #6b7280;
                font-size: 12px;
            }

            .rss-author {
                color: #059669;
                font-size: 12px;
                font-weight: 500;
            }

            .rss-title {
                font-size: 14px;
                line-height: 1.5;
                margin-bottom: 6px;
            }

            .rss-link {
                color: #1f2937;
                text-decoration: none;
                font-weight: 500;
            }

            .rss-link:hover {
                color: #059669;
                text-decoration: underline;
            }

            .rss-summary {
                font-size: 13px;
                color: #6b7280;
                line-height: 1.5;
                margin: 0;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }

            :root {
                --bg: #f6f3ee;
                --surface: #ffffff;
                --surface-muted: #f1f5f9;
                --surface-warm: #fff7ed;
                --border: #e7e5e4;
                --ink: #0f172a;
                --muted: #5b6472;
                --accent: #2563eb;
                --accent-strong: #1d4ed8;
                --accent-warm: #f97316;
                --success: #16a34a;
                --danger: #dc2626;
                --shadow-soft: 0 10px 30px rgba(15, 23, 42, 0.08);
                --shadow-deep: 0 24px 60px rgba(15, 23, 42, 0.12);
                --radius-lg: 18px;
                --radius-xl: 26px;
            }

            body {
                font-family: 'Public Sans', sans-serif;
                background:
                    radial-gradient(1200px 500px at -10% -10%, rgba(251, 191, 36, 0.18) 0%, transparent 55%),
                    radial-gradient(1200px 600px at 110% -10%, rgba(59, 130, 246, 0.18) 0%, transparent 55%),
                    var(--bg);
                color: var(--ink);
                line-height: 1.6;
                padding: 12px;
            }

            .container {
                max-width: none;
                width: 100%;
                margin: 0 auto 32px;
                padding: 16px 20px 20px;
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.92) 100%);
                border: 1px solid var(--border);
                border-radius: var(--radius-xl);
                box-shadow: var(--shadow-deep);
                overflow: visible;
            }

            .header {
                background: linear-gradient(135deg, #fff7ed 0%, #e0f2fe 50%, #eef2ff 100%);
                color: var(--ink);
                padding: 18px;
                text-align: left;
                border-radius: var(--radius-lg);
                border: 1px solid rgba(15, 23, 42, 0.08);
                overflow: hidden;
                display: grid;
                grid-template-columns: 1fr;
                gap: 8px;
                align-items: start;
                animation: fadeIn 0.6s ease both;
            }

            .header::before {
                content: "";
                position: absolute;
                inset: -40% 60% auto auto;
                width: 220px;
                height: 220px;
                background: radial-gradient(circle, rgba(59, 130, 246, 0.18), transparent 70%);
                filter: blur(2px);
            }

            .header::after {
                content: "";
                position: absolute;
                inset: auto auto -40% -10%;
                width: 280px;
                height: 280px;
                background: radial-gradient(circle, rgba(249, 115, 22, 0.18), transparent 70%);
                filter: blur(4px);
            }

            .header-title {
                font-family: 'Newsreader', serif;
                font-size: 26px;
                font-weight: 600;
                margin: 4px 0 0 0;
                position: relative;
                z-index: 1;
            }

            .header-main {
                display: flex;
                flex-direction: column;
                gap: 10px;
                position: relative;
                z-index: 1;
            }

            .header-info {
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 8px;
                font-size: 12px;
                position: relative;
                z-index: 1;
            }

            .info-item {
                text-align: left;
                background: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 10px;
                padding: 8px 10px;
            }

            .info-label {
                font-size: 11px;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: var(--muted);
                margin-bottom: 4px;
            }

            .info-value {
                font-weight: 600;
                font-size: 14px;
                color: var(--ink);
            }

            .content {
                padding: 12px 0 0;
            }

            .bento-grid {
                display: grid;
                grid-template-columns: repeat(12, minmax(0, 1fr));
                gap: 12px;
            }

            .bento-card {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                padding: 12px;
                box-shadow: var(--shadow-soft);
                position: relative;
                animation: rise 0.6s ease both;
                animation-delay: var(--delay, 0ms);
            }

            .span-12 { grid-column: span 12; }
            .span-6 { grid-column: span 6; }

            .word-group {
                margin-bottom: 0;
            }

            .word-header {
                margin-bottom: 8px;
                padding-bottom: 6px;
                border-bottom: 1px dashed var(--border);
            }

            .word-name {
                font-family: 'Newsreader', serif;
                font-size: 16px;
            }

            .word-count {
                background: #eff6ff;
                border: 1px solid #dbeafe;
                color: #1d4ed8;
                font-size: 10px;
                padding: 2px 6px;
                border-radius: 999px;
            }

            .word-count.hot {
                background: #fee2e2;
                border-color: #fecaca;
                color: var(--danger);
            }

            .word-count.warm {
                background: #ffedd5;
                border-color: #fed7aa;
                color: var(--accent-warm);
            }

            .word-index {
                color: var(--muted);
                font-size: 10px;
                border: 1px solid rgba(15, 23, 42, 0.12);
                border-radius: 999px;
                padding: 2px 6px;
            }

            .news-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 10px;
            }

            .news-card {
                background: var(--surface);
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: 8px;
                display: grid;
                grid-template-rows: 104px 1fr;
                gap: 6px;
                text-decoration: none;
                color: var(--ink);
                position: relative;
                transition: transform 0.2s ease, box-shadow 0.2s ease;
                height: 220px;
                overflow: hidden;
                animation: fadeIn 0.6s ease both;
                animation-delay: var(--delay, 0ms);
            }

            .news-card.is-link {
                cursor: pointer;
            }

            .news-card:hover {
                transform: translateY(-3px);
                box-shadow: 0 16px 36px rgba(15, 23, 42, 0.16);
            }

            .news-card.new::after {
                content: "NEW";
                position: absolute;
                top: 10px;
                right: 12px;
                background: var(--accent-warm);
                color: white;
                font-size: 10px;
                font-weight: 700;
                padding: 2px 6px;
                border-radius: 999px;
                letter-spacing: 0.4px;
            }

            .news-card-media {
                border-radius: 12px;
                overflow: hidden;
                height: 100%;
                background: linear-gradient(135deg, rgba(224, 242, 254, 0.9), rgba(255, 247, 237, 0.9));
                display: flex;
                align-items: center;
                justify-content: center;
                position: relative;
            }

            .news-card-media img {
                width: 100%;
                height: 100%;
                object-fit: cover;
                display: block;
            }

            .news-card-body {
                display: flex;
                flex-direction: column;
                gap: 4px;
                min-height: 0;
            }

            .news-meta {
                display: flex;
                flex-wrap: wrap;
                gap: 4px;
                align-items: center;
            }

            .news-number {
                color: #475569;
                font-size: 10px;
                font-weight: 700;
                min-width: 20px;
                text-align: center;
                background: #e2e8f0;
                border-radius: 999px;
                width: 20px;
                height: 20px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }

            .news-title {
                font-size: 13px;
                line-height: 1.4;
                color: var(--ink);
                font-weight: 600;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }

            .news-card-footer {
                display: flex;
                align-items: center;
                justify-content: space-between;
                font-size: 10px;
                color: var(--muted);
                margin-top: auto;
            }

            .news-item {
                margin-bottom: 0;
                padding: 14px 0;
                border-top: 1px solid #e2e8f0;
                display: grid;
                grid-template-columns: 32px minmax(0, 1fr) minmax(220px, 0.35fr);
                gap: 16px;
                align-items: stretch;
                position: relative;
            }

            .word-group .news-item:first-of-type {
                border-top: none;
                padding-top: 0;
            }

            .news-item.new {
                background: var(--surface-warm);
                border: 1px solid #fed7aa;
                border-radius: 12px;
                padding: 10px;
                margin-top: 10px;
            }

            .news-item.new::after {
                content: "NEW";
                position: absolute;
                top: 10px;
                right: 12px;
                background: var(--accent-warm);
                color: white;
                font-size: 10px;
                font-weight: 700;
                padding: 2px 6px;
                border-radius: 999px;
                letter-spacing: 0.4px;
            }

            .news-number {
                color: #475569;
                font-size: 11px;
                font-weight: 700;
                min-width: 22px;
                text-align: center;
                background: #e2e8f0;
                border-radius: 999px;
                width: 22px;
                height: 22px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }

            .news-content {
                padding-right: 0;
            }

            .news-item.new .news-content {
                padding-right: 0;
            }

            .news-header {
                display: flex;
                align-items: center;
                gap: 6px;
                margin-bottom: 8px;
                flex-wrap: wrap;
            }

            .source-name,
            .keyword-tag,
            .rank-num,
            .time-info,
            .count-info {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                padding: 2px 6px;
                border-radius: 999px;
                font-size: 10px;
                font-weight: 600;
            }

            .source-name {
                color: #475569;
                background: #f1f5f9;
                border: 1px solid #e2e8f0;
            }

            .keyword-tag {
                color: #1d4ed8;
                background: #eff6ff;
                border: 1px solid #dbeafe;
            }

            .rank-num {
                color: white;
                background: #1f2937;
            }

            .rank-num.top { background: var(--danger); }
            .rank-num.high { background: var(--accent-warm); }

            .time-info {
                color: var(--muted);
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                font-weight: 500;
            }

            .count-info {
                color: #15803d;
                background: #ecfdf3;
                border: 1px solid #bbf7d0;
                font-weight: 600;
            }

            .news-title {
                font-size: 15px;
                line-height: 1.5;
                color: var(--ink);
                font-weight: 600;
                display: -webkit-box;
                -webkit-line-clamp: 3;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }

            .news-link {
                color: var(--accent-strong);
                text-decoration: none;
            }

            .news-link:hover {
                text-decoration: underline;
                color: var(--accent);
            }

            .news-link:visited {
                color: #0f766e;
            }

            .news-preview {
                background: linear-gradient(135deg, rgba(224, 242, 254, 0.9), rgba(255, 247, 237, 0.9));
                border: 1px solid #e2e8f0;
                border-radius: 14px;
                padding: 12px 14px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                gap: 10px;
                color: var(--ink);
                text-decoration: none;
                transition: transform 0.2s ease, box-shadow 0.2s ease;
            }

            .news-preview:hover {
                transform: translateY(-2px);
                box-shadow: 0 12px 28px rgba(15, 23, 42, 0.12);
            }

            .news-preview-label {
                font-size: 11px;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                color: var(--muted);
            }

            .news-preview-text {
                font-size: 13px;
                line-height: 1.4;
                color: var(--ink);
                display: -webkit-box;
                -webkit-line-clamp: 3;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }

            .news-preview-footer {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                font-size: 11px;
                color: var(--muted);
            }

            .news-preview-pill {
                background: rgba(37, 99, 235, 0.12);
                color: var(--accent-strong);
                border-radius: 999px;
                padding: 2px 8px;
                font-weight: 600;
            }

            .new-section {
                margin-top: 0;
                padding-top: 0;
                border-top: none;
            }

            .new-section-title {
                color: var(--ink);
                font-size: 18px;
                font-family: 'Newsreader', serif;
                margin: 0 0 16px 0;
            }

            .new-source-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 16px;
            }

            .new-source-group {
                margin-bottom: 0;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 14px;
                padding: 12px;
            }

            .new-source-title {
                color: var(--muted);
                font-size: 12px;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin: 0 0 10px 0;
                border-bottom: 1px dashed #e2e8f0;
                padding-bottom: 6px;
            }

            .new-item {
                display: grid;
                align-items: center;
                grid-template-columns: auto auto 1fr;
                gap: 10px;
                padding: 8px 0;
                border-bottom: 1px dashed #e2e8f0;
            }

            .new-item:last-child {
                border-bottom: none;
            }

            .new-item-number {
                color: #475569;
                background: #e2e8f0;
                width: 20px;
                height: 20px;
                border-radius: 999px;
                font-size: 11px;
            }

            .new-item-rank {
                background: #1f2937;
                font-size: 10px;
                padding: 2px 6px;
                border-radius: 999px;
            }

            .new-item-rank.top { background: var(--danger); }
            .new-item-rank.high { background: var(--accent-warm); }

            .new-item-title {
                font-size: 13px;
                color: var(--ink);
            }

            .error-section {
                background: #fef2f2;
                border: 1px solid #fecaca;
                padding: 16px;
                margin-bottom: 0;
            }

            .error-title {
                color: var(--danger);
                font-size: 14px;
                font-weight: 700;
                margin: 0 0 8px 0;
            }

            .rss-section {
                margin-top: 0;
                padding-top: 0;
                border-top: none;
            }

            .rss-section-header {
                margin-bottom: 16px;
            }

            .rss-section-title {
                font-size: 18px;
                font-family: 'Newsreader', serif;
                color: var(--accent-strong);
            }

            .rss-section-count {
                color: var(--muted);
            }

            .rss-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 16px;
            }

            .feed-group {
                margin-bottom: 0;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 14px;
                padding: 12px;
            }

            .feed-header {
                border-bottom: 1px dashed #cbd5f5;
                padding-bottom: 8px;
                margin-bottom: 10px;
            }

            .feed-name {
                font-size: 14px;
                color: var(--accent-strong);
            }

            .rss-item {
                margin-bottom: 10px;
                padding: 10px;
                background: white;
                border-radius: 10px;
                border-left: 3px solid #38bdf8;
            }

            .rss-item:last-child {
                margin-bottom: 0;
            }

            .rss-meta {
                gap: 8px;
                margin-bottom: 6px;
            }

            .rss-link {
                color: var(--ink);
            }

            .rss-link:hover {
                color: var(--accent-strong);
            }

            .rss-summary {
                font-size: 12px;
            }

            .footer {
                margin-top: 20px;
                padding: 16px;
                background: rgba(255, 255, 255, 0.9);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
            }

            .footer-content {
                color: var(--muted);
            }

            .footer-link {
                color: var(--accent);
            }

            .project-name {
                color: var(--ink);
            }

            .preview-modal {
                position: fixed;
                inset: 0;
                background: rgba(15, 23, 42, 0.5);
                display: none;
                align-items: center;
                justify-content: center;
                padding: 20px;
                z-index: 2000;
            }

            .preview-modal.show {
                display: flex;
            }

            .preview-dialog {
                background: white;
                border-radius: 18px;
                max-width: 960px;
                width: 100%;
                max-height: 90vh;
                overflow: hidden;
                box-shadow: 0 30px 80px rgba(15, 23, 42, 0.35);
                display: flex;
                flex-direction: column;
            }

            .preview-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 16px 20px;
                border-bottom: 1px solid #e2e8f0;
            }

            .preview-title {
                font-family: 'Newsreader', serif;
                font-size: 18px;
                color: var(--ink);
            }

            .preview-close {
                background: transparent;
                border: none;
                color: var(--muted);
                font-weight: 600;
                cursor: pointer;
            }

            .preview-body {
                padding: 16px;
                overflow: auto;
                background: #f8fafc;
            }

            .preview-body img {
                width: 100%;
                height: auto;
                border-radius: 12px;
                border: 1px solid #e2e8f0;
            }

            .preview-footer {
                padding: 16px 20px;
                border-top: 1px solid #e2e8f0;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                flex-wrap: wrap;
            }

            .preview-filename {
                font-size: 12px;
                color: var(--muted);
            }

            .preview-actions {
                display: flex;
                gap: 8px;
                align-items: center;
            }

            .modal-open {
                overflow: hidden;
            }

            @keyframes rise {
                from { opacity: 0; transform: translateY(12px); }
                to { opacity: 1; transform: translateY(0); }
            }

            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
            }

            @media (prefers-reduced-motion: reduce) {
                * {
                    animation: none !important;
                    transition: none !important;
                }
            }

            @media (max-width: 1200px) {
                .span-6 { grid-column: span 12; }
                .header { grid-template-columns: 1fr; }
                .header-info { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .news-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            }

            @media (max-width: 960px) {
                .header-info { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .news-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            }

            @media (max-width: 640px) {
                body { padding: 10px; }
                .container { padding: 14px; }
                .header { padding: 16px; }
                .header-title { font-size: 24px; }
                .header-info { grid-template-columns: 1fr; }
                .news-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 10px;
                }
                .news-card {
                    height: 210px;
                }
            }

            @media (max-width: 520px) {
                .news-grid {
                    grid-template-columns: 1fr;
                }
                .news-card { height: 210px; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="header-main">
                    <div class="header-title">热点新闻分析</div>
                    <div class="header-info">
                        <div class="info-item">
                            <span class="info-label">报告类型</span>
                            <span class="info-value">"""

    # 处理报告类型显示
    if is_daily_summary:
        if mode == "current":
            html += "当前榜单"
        elif mode == "incremental":
            html += "增量模式"
        else:
            html += "当日汇总"
    else:
        html += "实时分析"

    html += """</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">新闻总数</span>
                        <span class="info-value">"""

    html += f"{total_titles} 条"

    # 计算筛选后的热点新闻数量
    hot_news_count = sum(len(stat["titles"]) for stat in report_data["stats"])

    html += """</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">热点新闻</span>
                        <span class="info-value">"""

    html += f"{hot_news_count} 条"

    html += """</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">生成时间</span>
                        <span class="info-value">"""

    # 使用提供的时间函数或默认 datetime.now
    if get_time_func:
        now = get_time_func()
    else:
        now = datetime.now()
    html += now.strftime("%m-%d %H:%M")

    html += """</span>
                    </div>
                </div>
            </div>
            </div>

            <div class="content">
                <div class="bento-grid">"""

    # 处理失败ID错误信息
    if report_data["failed_ids"]:
        html += """
                <div class="error-section bento-card span-12" style="--delay: 60ms;" role="alert">
                    <div class="error-title">请求失败的平台</div>
                    <ul class="error-list">"""
        for id_value in report_data["failed_ids"]:
            html += f'<li class="error-item">{html_escape(id_value)}</li>'
        html += """
                    </ul>
                </div>"""

    # 生成热点词汇统计部分的HTML
    stats_html = ""
    if report_data["stats"]:
        total_count = len(report_data["stats"])

        for i, stat in enumerate(report_data["stats"], 1):
            count = stat["count"]

            # 确定热度等级
            if count >= 10:
                count_class = "hot"
            elif count >= 5:
                count_class = "warm"
            else:
                count_class = ""

            escaped_word = html_escape(stat["word"])

            span_class = "span-12"
            delay_ms = min(i - 1, 6) * 60

            stats_html += f"""
                <div class="word-group bento-card {span_class}" style="--delay: {delay_ms}ms;">
                    <div class="word-header">
                        <div class="word-info">
                            <div class="word-name">{escaped_word}</div>
                            <div class="word-count {count_class}">{count} 条</div>
                        </div>
                        <div class="word-index">{i}/{total_count}</div>
                    </div>
                    <div class="news-grid">"""

            # 处理每个词组下的新闻标题，给每条新闻标上序号
            for j, title_data in enumerate(stat["titles"], 1):
                is_new = title_data.get("is_new", False)
                link_url = title_data.get("mobile_url") or title_data.get("url", "")
                escaped_title = html_escape(title_data["title"])
                escaped_url = html_escape(link_url) if link_url else ""

                preview_label_raw = title_data.get("source_name", "")
                preview_domain = ""
                if link_url and "://" in link_url:
                    preview_domain = link_url.split("/")[2]
                if preview_domain:
                    preview_label_raw = preview_domain

                preview_label = html_escape(preview_label_raw) if preview_label_raw else ""

                simplified_time = ""
                time_display = title_data.get("time_display", "")
                if time_display:
                    simplified_time = (
                        time_display.replace(" ~ ", "~")
                        .replace("[", "")
                        .replace("]", "")
                    )

                preview_time = html_escape(simplified_time) if simplified_time else "更新中"

                preview_image = None
                if link_url:
                    preview_image = _get_preview_image(
                        link_url, preview_session, preview_cache, preview_quota
                    )

                image_src = preview_image or placeholder_image
                escaped_image_src = html_escape(image_src)
                image_html = (
                    f'<img src="{escaped_image_src}" alt="{escaped_title}" loading="lazy" '
                    f'decoding="async" referrerpolicy="no-referrer" '
                    f'onerror="this.src=\'{escaped_placeholder_image}\'; this.onerror=null;">'
                )

                card_classes = ["news-card"]
                if link_url:
                    card_classes.append("is-link")
                if is_new:
                    card_classes.append("new")

                card_class_text = " ".join(card_classes)
                card_delay = min(j - 1, 9) * 40

                meta_items = [f'<span class="news-number">{j}</span>']
                if display_mode == "keyword":
                    meta_items.append(
                        f'<span class="source-name">{html_escape(title_data["source_name"])}</span>'
                    )
                else:
                    matched_keyword = title_data.get("matched_keyword", "")
                    if matched_keyword:
                        meta_items.append(
                            f'<span class="keyword-tag">[{html_escape(matched_keyword)}]</span>'
                        )

                ranks = title_data.get("ranks", [])
                if ranks:
                    min_rank = min(ranks)
                    max_rank = max(ranks)
                    rank_threshold = title_data.get("rank_threshold", 10)

                    if min_rank <= 3:
                        rank_class = "top"
                    elif min_rank <= rank_threshold:
                        rank_class = "high"
                    else:
                        rank_class = ""

                    if min_rank == max_rank:
                        rank_text = str(min_rank)
                    else:
                        rank_text = f"{min_rank}-{max_rank}"

                    meta_items.append(f'<span class="rank-num {rank_class}">{rank_text}</span>')

                if simplified_time:
                    meta_items.append(
                        f'<span class="time-info">{html_escape(simplified_time)}</span>'
                    )

                count_info = title_data.get("count", 1)
                if count_info > 1:
                    meta_items.append(f'<span class="count-info">{count_info}次</span>')

                meta_html = "\n                                    ".join(meta_items)
                footer_label = preview_label or html_escape(title_data.get("source_name", "")) or "来源"

                card_inner_html = f"""
                        <div class="news-card-media">
                            {image_html}
                        </div>
                        <div class="news-card-body">
                            <div class="news-meta">
                                {meta_html}
                            </div>
                            <div class="news-title">{escaped_title}</div>
                            <div class="news-card-footer">
                                <span>{footer_label}</span>
                                <span>{preview_time}</span>
                            </div>
                        </div>"""

                if link_url:
                    stats_html += f"""
                    <a class="{card_class_text}" href="{escaped_url}" target="_blank" rel="noopener" style="--delay: {card_delay}ms;">
                        {card_inner_html}
                    </a>"""
                else:
                    stats_html += f"""
                    <div class="{card_class_text}" style="--delay: {card_delay}ms;">
                        {card_inner_html}
                    </div>"""

            stats_html += """
                    </div>
                </div>"""

    # 生成新增新闻区域的HTML
    new_titles_html = ""
    if report_data["new_titles"]:
        new_titles_html += f"""
                <div class="new-section bento-card span-12" style="--delay: 240ms;">
                    <div class="new-section-title">本次新增热点 (共 {report_data['total_new_count']} 条)</div>
                    <div class="new-source-grid">"""

        for source_data in report_data["new_titles"]:
            escaped_source = html_escape(source_data["source_name"])
            titles_count = len(source_data["titles"])

            new_titles_html += f"""
                    <div class="new-source-group">
                        <div class="new-source-title">{escaped_source} · {titles_count}条</div>"""

            # 为新增新闻也添加序号
            for idx, title_data in enumerate(source_data["titles"], 1):
                ranks = title_data.get("ranks", [])

                # 处理新增新闻的排名显示
                rank_class = ""
                if ranks:
                    min_rank = min(ranks)
                    if min_rank <= 3:
                        rank_class = "top"
                    elif min_rank <= title_data.get("rank_threshold", 10):
                        rank_class = "high"

                    if len(ranks) == 1:
                        rank_text = str(ranks[0])
                    else:
                        rank_text = f"{min(ranks)}-{max(ranks)}"
                else:
                    rank_text = "?"

                new_titles_html += f"""
                        <div class="new-item">
                            <div class="new-item-number">{idx}</div>
                            <div class="new-item-rank {rank_class}">{rank_text}</div>
                            <div class="new-item-content">
                                <div class="new-item-title">"""

                # 处理新增新闻的链接
                escaped_title = html_escape(title_data["title"])
                link_url = title_data.get("mobile_url") or title_data.get("url", "")

                if link_url:
                    escaped_url = html_escape(link_url)
                    new_titles_html += f'<a href="{escaped_url}" target="_blank" class="news-link">{escaped_title}</a>'
                else:
                    new_titles_html += escaped_title

                new_titles_html += """
                                </div>
                            </div>
                        </div>"""

            new_titles_html += """
                    </div>"""

        new_titles_html += """
                    </div>
                </div>"""

    # 生成 RSS 统计内容
    def render_rss_stats_html(
        stats: List[Dict],
        title: str = "RSS 订阅更新",
        delay_ms: int = 0,
    ) -> str:
        """渲染 RSS 统计区块 HTML

        Args:
            stats: RSS 分组统计列表，格式与热榜一致：
                [
                    {
                        "word": "关键词",
                        "count": 5,
                        "titles": [
                            {
                                "title": "标题",
                                "source_name": "Feed 名称",
                                "time_display": "12-29 08:20",
                                "url": "...",
                                "is_new": True/False
                            }
                        ]
                    }
                ]
            title: 区块标题

        Returns:
            渲染后的 HTML 字符串
        """
        if not stats:
            return ""

        # 计算总条目数
        total_count = sum(stat.get("count", 0) for stat in stats)
        if total_count == 0:
            return ""

        rss_html = f"""
                <div class="rss-section bento-card span-12" style="--delay: {delay_ms}ms;">
                    <div class="rss-section-header">
                        <div class="rss-section-title">{title}</div>
                        <div class="rss-section-count">{total_count} 条</div>
                    </div>
                    <div class="rss-grid">"""

        # 按关键词分组渲染（与热榜格式一致）
        for stat in stats:
            keyword = stat.get("word", "")
            titles = stat.get("titles", [])
            if not titles:
                continue

            keyword_count = len(titles)

            rss_html += f"""
                        <div class="feed-group">
                            <div class="feed-header">
                                <div class="feed-name">{html_escape(keyword)}</div>
                                <div class="feed-count">{keyword_count} 条</div>
                            </div>"""

            for title_data in titles:
                item_title = title_data.get("title", "")
                url = title_data.get("url", "")
                time_display = title_data.get("time_display", "")
                source_name = title_data.get("source_name", "")
                is_new = title_data.get("is_new", False)

                rss_html += """
                        <div class="rss-item">
                            <div class="rss-meta">"""

                if time_display:
                    rss_html += f'<span class="rss-time">{html_escape(time_display)}</span>'

                if source_name:
                    rss_html += f'<span class="rss-author">{html_escape(source_name)}</span>'

                if is_new:
                    rss_html += '<span class="rss-author" style="color: #dc2626;">NEW</span>'

                rss_html += """
                            </div>
                            <div class="rss-title">"""

                escaped_title = html_escape(item_title)
                if url:
                    escaped_url = html_escape(url)
                    rss_html += f'<a href="{escaped_url}" target="_blank" class="rss-link">{escaped_title}</a>'
                else:
                    rss_html += escaped_title

                rss_html += """
                            </div>
                        </div>"""

            rss_html += """
                        </div>"""

        rss_html += """
                    </div>
                </div>"""
        return rss_html

    # 生成 RSS 统计和新增 HTML
    rss_stats_html = render_rss_stats_html(rss_items, "RSS 订阅更新", delay_ms=280) if rss_items else ""
    rss_new_html = render_rss_stats_html(rss_new_items, "RSS 新增更新", delay_ms=340) if rss_new_items else ""

    # 根据配置决定内容顺序（与推送逻辑一致）
    if reverse_content_order:
        # 新增在前，统计在后
        # 顺序：热榜新增 → RSS新增 → 热榜统计 → RSS统计
        html += new_titles_html + rss_new_html + stats_html + rss_stats_html
    else:
        # 默认：统计在前，新增在后
        # 顺序：热榜统计 → RSS统计 → 热榜新增 → RSS新增
        html += stats_html + rss_stats_html + new_titles_html + rss_new_html

    html += """
                </div>
            </div>

            <div class="footer">
                <div class="footer-content">
                    由 <span class="project-name">TrendRadar</span> 生成 ·
                    <a href="https://github.com/sansan0/TrendRadar" target="_blank" class="footer-link">
                        GitHub 开源项目
                    </a>"""

    if update_info:
        html += f"""
                    <br>
                    <span style="color: #ea580c; font-weight: 500;">
                        发现新版本 {update_info['remote_version']}，当前版本 {update_info['current_version']}
                    </span>"""

    html += """
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    preview_session.close()
    _save_preview_cache(preview_cache)
    return html
