#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OLLAMA_MODEL="${OLLAMA_MODEL:-longwayxu/xiaomi-ocr-0:bf16}"
OLLAMA_BIN="$(command -v ollama || true)"
if [[ -z "$OLLAMA_BIN" && -x "/Applications/Ollama.app/Contents/Resources/ollama" ]]; then
  OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
fi

if [[ -z "$OLLAMA_BIN" ]]; then
  echo "未找到 Ollama。请先安装 Ollama 并运行 ./setup_macos.sh。" >&2
  exit 1
fi
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "未找到项目 Python 环境。请先运行 ./setup_macos.sh。" >&2
  exit 1
fi

if ! curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null; then
  if [[ -d "/Applications/Ollama.app" ]]; then
    open -a Ollama
  else
    "$OLLAMA_BIN" serve >"${TMPDIR:-/tmp}/fapiao-ollama.log" 2>&1 &
  fi
  for _ in {1..30}; do
    if curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null; then
      break
    fi
    sleep 1
  done
fi

if ! curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "Ollama API 未启动。请打开 Ollama 应用后重试。" >&2
  exit 1
fi
if ! "$OLLAMA_BIN" list | awk 'NR > 1 {print $1}' | grep -Fxq "$OLLAMA_MODEL"; then
  echo "Ollama 中未找到模型 ${OLLAMA_MODEL}。请运行 ./setup_macos.sh 下载模型。" >&2
  exit 1
fi

cd "$PROJECT_DIR"
exec "$PROJECT_DIR/.venv/bin/python" app_v2.py
