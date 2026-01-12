#!/bin/bash
set -e

# 检查配置文件
if [ ! -f "/app/config/config.yaml" ] || [ ! -f "/app/config/frequency_words.txt" ]; then
    echo "❌ 配置文件缺失"
    exit 1
fi

# 保存环境变量
env >> /etc/environment

if [ "${AUTO_DOWNLOAD_SHERPA_ONNX:-true}" = "true" ]; then
    MODEL_DIR=$(/usr/local/bin/python - <<'PY'
import os
import sys
import yaml

cfg_path = os.environ.get("CONFIG_PATH", "/app/config/config.yaml")
try:
    with open(cfg_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
except Exception:
    sys.exit(0)

audio = data.get("audio", {})
tts = audio.get("tts", {})
provider = str(tts.get("provider", "")).lower()
if provider != "sherpa_onnx":
    sys.exit(0)

model_dir = os.environ.get("SHERPA_ONNX_MODEL_DIR") or tts.get("sherpa_onnx", {}).get(
    "model_dir",
    "models/sherpa-onnx/matcha-icefall-zh-en",
)
print(model_dir)
PY
    )

    if [ -n "${MODEL_DIR}" ]; then
        echo "⬇️  下载 Sherpa-ONNX 模型到 ${MODEL_DIR}"
        if ! /usr/local/bin/python /app/tools/download_sherpa_onnx_model.py --output-dir "${MODEL_DIR}"; then
            echo "⚠️  模型下载失败，继续运行（音频可能不可用）"
        fi
    fi
fi

case "${RUN_MODE:-cron}" in
"once")
    echo "🔄 单次执行"
    exec /usr/local/bin/python -m trendradar
    ;;
"cron")
    # 生成 crontab
    echo "${CRON_SCHEDULE:-*/30 * * * *} cd /app && /usr/local/bin/python -m trendradar" > /tmp/crontab
    
    echo "📅 生成的crontab内容:"
    cat /tmp/crontab

    if ! /usr/local/bin/supercronic -test /tmp/crontab; then
        echo "❌ crontab格式验证失败"
        exit 1
    fi

    # 立即执行一次（如果配置了）
    if [ "${IMMEDIATE_RUN:-false}" = "true" ]; then
        echo "▶️ 立即执行一次"
        /usr/local/bin/python -m trendradar
    fi

    # 启动 Web 服务器（如果配置了）
    if [ "${ENABLE_WEBSERVER:-false}" = "true" ]; then
        echo "🌐 启动 Web 服务器..."
        /usr/local/bin/python manage.py start_webserver
    fi

    echo "⏰ 启动supercronic: ${CRON_SCHEDULE:-*/30 * * * *}"
    echo "🎯 supercronic 将作为 PID 1 运行"

    exec /usr/local/bin/supercronic -passthrough-logs /tmp/crontab
    ;;
*)
    exec "$@"
    ;;
esac
