# coding=utf-8
"""
RSS HTML 报告渲染模块

提供 RSS 订阅内容的 HTML 格式报告生成功能
"""

from datetime import datetime
from typing import Dict, List, Optional, Callable

from trendradar.report.helpers import html_escape


def render_rss_html_content(
    rss_items: List[Dict],
    total_count: int,
    feeds_info: Optional[Dict[str, str]] = None,
    *,
    get_time_func: Optional[Callable[[], datetime]] = None,
) -> str:
    """渲染 RSS HTML 内容

    Args:
        rss_items: RSS 条目列表，每个条目包含:
            - title: 标题
            - feed_id: RSS 源 ID
            - feed_name: RSS 源名称
            - url: 链接
            - published_at: 发布时间
            - summary: 摘要（可选）
            - author: 作者（可选）
        total_count: 条目总数
        feeds_info: RSS 源 ID 到名称的映射
        get_time_func: 获取当前时间的函数（可选，默认使用 datetime.now）

    Returns:
        渲染后的 HTML 字符串
    """
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RSS 订阅内容</title>
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
                max-width: 700px;
                margin: 0 auto;
                background: white;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 2px 16px rgba(0,0,0,0.06);
            }

            .header {
                background: linear-gradient(135deg, #059669 0%, #10b981 100%);
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

            .feed-group {
                margin-bottom: 32px;
            }

            .feed-group:last-child {
                margin-bottom: 0;
            }

            .feed-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 16px;
                padding-bottom: 8px;
                border-bottom: 2px solid #10b981;
            }

            .feed-name {
                font-size: 16px;
                font-weight: 600;
                color: #059669;
            }

            .feed-count {
                color: #666;
                font-size: 13px;
                font-weight: 500;
            }

            .rss-item {
                margin-bottom: 16px;
                padding: 16px;
                background: #f9fafb;
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
                margin-bottom: 8px;
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
                font-size: 15px;
                line-height: 1.5;
                color: #1a1a1a;
                margin: 0 0 8px 0;
                font-weight: 500;
            }

            .rss-link {
                color: #2563eb;
                text-decoration: none;
            }

            .rss-link:hover {
                text-decoration: underline;
            }

            .rss-link:visited {
                color: #7c3aed;
            }

            .rss-summary {
                font-size: 13px;
                color: #6b7280;
                line-height: 1.6;
                margin: 0;
                display: -webkit-box;
                -webkit-line-clamp: 3;
                -webkit-box-orient: vertical;
                overflow: hidden;
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
                color: #059669;
                text-decoration: none;
                font-weight: 500;
                transition: color 0.2s ease;
            }

            .footer-link:hover {
                color: #10b981;
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
                .rss-meta { gap: 8px; }
                .rss-item { padding: 12px; }
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

            :root {
                --bg: #f6f3ee;
                --surface: #ffffff;
                --surface-muted: #f1f5f9;
                --border: #e7e5e4;
                --ink: #0f172a;
                --muted: #5b6472;
                --accent: #059669;
                --accent-strong: #047857;
                --accent-warm: #f97316;
                --danger: #dc2626;
                --shadow-soft: 0 10px 30px rgba(15, 23, 42, 0.08);
                --shadow-deep: 0 24px 60px rgba(15, 23, 42, 0.12);
                --radius-lg: 18px;
                --radius-xl: 26px;
            }

            body {
                font-family: 'Public Sans', sans-serif;
                background:
                    radial-gradient(1200px 500px at -10% -10%, rgba(16, 185, 129, 0.18) 0%, transparent 55%),
                    radial-gradient(1200px 600px at 110% -10%, rgba(59, 130, 246, 0.12) 0%, transparent 55%),
                    var(--bg);
                color: var(--ink);
                line-height: 1.6;
                padding: 20px;
            }

            .container {
                max-width: 1120px;
                margin: 0 auto 48px;
                padding: 24px;
                background: linear-gradient(180deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 250, 252, 0.92) 100%);
                border: 1px solid var(--border);
                border-radius: var(--radius-xl);
                box-shadow: var(--shadow-deep);
                overflow: visible;
            }

            .header {
                background: linear-gradient(135deg, #ecfdf5 0%, #e0f2fe 55%, #eef2ff 100%);
                color: var(--ink);
                padding: 24px;
                text-align: left;
                border-radius: var(--radius-lg);
                border: 1px solid rgba(15, 23, 42, 0.08);
                overflow: hidden;
                animation: fadeIn 0.6s ease both;
            }

            .header::before {
                content: "";
                position: absolute;
                inset: -40% 60% auto auto;
                width: 220px;
                height: 220px;
                background: radial-gradient(circle, rgba(16, 185, 129, 0.18), transparent 70%);
                filter: blur(2px);
            }

            .header::after {
                content: "";
                position: absolute;
                inset: auto auto -40% -10%;
                width: 280px;
                height: 280px;
                background: radial-gradient(circle, rgba(59, 130, 246, 0.14), transparent 70%);
                filter: blur(4px);
            }

            .save-buttons {
                top: 18px;
                right: 18px;
                z-index: 1;
            }

            .save-btn {
                background: var(--accent);
                border: none;
                color: white;
                padding: 8px 14px;
                border-radius: 999px;
                cursor: pointer;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.2px;
                transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
                backdrop-filter: none;
                box-shadow: 0 8px 20px rgba(5, 150, 105, 0.25);
            }

            .save-btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 10px 24px rgba(5, 150, 105, 0.3);
                border-color: transparent;
            }

            .header-title {
                font-family: 'Newsreader', serif;
                font-size: 30px;
                font-weight: 600;
                margin: 4px 0 16px 0;
                position: relative;
                z-index: 1;
            }

            .header-info {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
                font-size: 13px;
                position: relative;
                z-index: 1;
            }

            .info-item {
                text-align: left;
                background: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 12px;
                padding: 10px 12px;
            }

            .info-label {
                font-size: 11px;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: var(--muted);
                margin-bottom: 6px;
            }

            .info-value {
                font-weight: 600;
                font-size: 16px;
                color: var(--ink);
            }

            .content {
                padding: 18px 0 0;
            }

            .bento-grid {
                display: grid;
                grid-template-columns: repeat(12, minmax(0, 1fr));
                gap: 16px;
            }

            .bento-card {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: var(--radius-lg);
                padding: 18px;
                box-shadow: var(--shadow-soft);
                position: relative;
                animation: rise 0.6s ease both;
                animation-delay: var(--delay, 0ms);
            }

            .span-12 { grid-column: span 12; }
            .span-6 { grid-column: span 6; }

            .feed-group {
                margin-bottom: 0;
            }

            .feed-header {
                margin-bottom: 10px;
                padding-bottom: 8px;
                border-bottom: 1px dashed #cbd5e1;
            }

            .feed-name {
                font-size: 15px;
                font-weight: 600;
                color: var(--accent-strong);
            }

            .rss-item {
                margin-bottom: 10px;
                padding: 10px;
                background: #f8fafc;
                border-radius: 10px;
                border-left: 3px solid #34d399;
            }

            .rss-item:last-child {
                margin-bottom: 0;
            }

            .rss-title {
                font-size: 15px;
                color: var(--ink);
            }

            .rss-link {
                color: var(--ink);
                text-decoration: none;
            }

            .rss-link:hover {
                color: var(--accent-strong);
                text-decoration: underline;
            }

            .rss-link:visited {
                color: #0f766e;
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

            @media (max-width: 960px) {
                .span-6 { grid-column: span 12; }
            }

            @media (max-width: 640px) {
                body { padding: 12px; }
                .container { padding: 16px; }
                .header { padding: 20px; }
                .header-title { font-size: 24px; }
                .save-buttons {
                    position: static;
                    margin-bottom: 12px;
                    flex-direction: column;
                    align-items: stretch;
                }
                .save-btn { width: 100%; }
                .header-info { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="header-title">RSS 订阅内容</div>
                <div class="header-info">
                    <div class="info-item">
                        <span class="info-label">订阅条目</span>
                        <span class="info-value">"""

    html += f"{total_count} 条"

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

            <div class="content">
                <div class="bento-grid">"""

    # 按 feed_id 分组
    feeds_map: Dict[str, List[Dict]] = {}
    for item in rss_items:
        feed_id = item.get("feed_id", "unknown")
        if feed_id not in feeds_map:
            feeds_map[feed_id] = []
        feeds_map[feed_id].append(item)

    # 渲染每个 RSS 源的内容
    for index, (feed_id, items) in enumerate(feeds_map.items(), 1):
        feed_name = items[0].get("feed_name", feed_id) if items else feed_id
        if feeds_info and feed_id in feeds_info:
            feed_name = feeds_info[feed_id]

        escaped_feed_name = html_escape(feed_name)

        delay_ms = min(index - 1, 6) * 60
        html += f"""
                <div class="feed-group bento-card span-6" style="--delay: {delay_ms}ms;">
                    <div class="feed-header">
                        <div class="feed-name">{escaped_feed_name}</div>
                        <div class="feed-count">{len(items)} 条</div>
                    </div>"""

        for item in items:
            escaped_title = html_escape(item.get("title", ""))
            url = item.get("url", "")
            published_at = item.get("published_at", "")
            author = item.get("author", "")
            summary = item.get("summary", "")

            html += """
                    <div class="rss-item">
                        <div class="rss-meta">"""

            if published_at:
                html += f'<span class="rss-time">{html_escape(published_at)}</span>'

            if author:
                html += f'<span class="rss-author">by {html_escape(author)}</span>'

            html += """
                        </div>
                        <div class="rss-title">"""

            if url:
                escaped_url = html_escape(url)
                html += f'<a href="{escaped_url}" target="_blank" class="rss-link">{escaped_title}</a>'
            else:
                html += escaped_title

            html += """
                        </div>"""

            if summary:
                escaped_summary = html_escape(summary)
                html += f"""
                        <p class="rss-summary">{escaped_summary}</p>"""

            html += """
                    </div>"""

        html += """
                </div>"""

    html += """
                </div>
            </div>

            <div class="footer">
                <div class="footer-content">
                    由 <span class="project-name">TrendRadar</span> 生成 ·
                    <a href="https://github.com/sansan0/TrendRadar" target="_blank" class="footer-link">
                        GitHub 开源项目
                    </a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return html
