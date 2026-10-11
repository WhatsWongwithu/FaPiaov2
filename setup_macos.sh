#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OLLAMA_MODEL="${OLLAMA_MODEL:-longwayxu/xiaomi-ocr-0:bf16}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "此安装脚本用于 macOS。其他系统请按 README.md 的手动安装步骤操作。" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 Python 3.11 或更高版本。请先安装 Python：https://www.python.org/downloads/macos/" >&2
  exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "当前 Python 为 ${PYTHON_VERSION}，需要 Python 3.11 或更高版本。" >&2
  exit 1
fi

OLLAMA_BIN="$(command -v ollama || true)"
if [[ -z "$OLLAMA_BIN" && -x "/Applications/Ollama.app/Contents/Resources/ollama" ]]; then
  OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
fi

if [[ -z "$OLLAMA_BIN" ]] && command -v brew >/dev/null 2>&1; then
  read -r -p "未找到 Ollama。使用 Homebrew 安装 Ollama 应用？[y/N] " answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    brew install --cask ollama
    OLLAMA_BIN="$(command -v ollama || true)"
    if [[ -z "$OLLAMA_BIN" && -x "/Applications/Ollama.app/Contents/Resources/ollama" ]]; then
      OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
    fi
  fi
fi

if [[ -z "$OLLAMA_BIN" ]]; then
  echo "请先从 https://ollama.com/download/mac 安装 Ollama，再重新运行本脚本。" >&2
  exit 1
fi

cd "$PROJECT_DIR"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
"$PROJECT_DIR/.venv/bin/python" -m pip install --upgrade pip
"$PROJECT_DIR/.venv/bin/python" -m pip install -r requirements.txt

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
  echo "Ollama 服务未能启动。请打开 Ollama 应用后重新运行本脚本。" >&2
  exit 1
fi

echo "正在下载本地票据识别模型：${OLLAMA_MODEL}（模型较大，首次下载需要一些时间）"
"$OLLAMA_BIN" pull "$OLLAMA_MODEL"

echo
echo "安装完成。运行以下命令启动发票程序："
echo "  ./start_macos.sh"
echo "然后访问 http://127.0.0.1:8080，并在设置中选择‘本地票据识别’。"
