#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <round1|round2>"
  exit 1
fi

ROUND="$1"
ROOT_DIR="/home/base/repo/video-stt-whisper-server"
PROJECT_DIR="$ROOT_DIR/whisper-stt"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
CONFIG_PATH="$PROJECT_DIR/config.ini"

API_TOKEN="$($PYTHON_BIN - <<'PY'
import configparser
from pathlib import Path

cfg = configparser.ConfigParser()
cfg.read(Path('/home/base/repo/video-stt-whisper-server/whisper-stt/config.ini'), encoding='utf-8')
print(cfg.get('security', 'api_token', fallback='').strip())
PY
)"

if [[ -z "$API_TOKEN" ]]; then
  echo "empty security.api_token in $CONFIG_PATH"
  exit 1
fi

pushd "$PROJECT_DIR" >/dev/null
WHISPER_STT_CONFIG="$CONFIG_PATH" \
"$PYTHON_BIN" tests/e2e/run_e2e_shutdown_round.py \
  --round "$ROUND" \
  --base-url "http://127.0.0.1:8000" \
  --api-token "$API_TOKEN" \
  --video-paths "tests/e2e/video_paths.txt" \
  --shutdown-after-sec 10 \
  --poll-sec 2 \
  --deadline-sec 7200 \
  --monitor-log "tmp/e2e/shutdown_${ROUND}_monitor.log" \
  --server-log "tmp/e2e/shutdown_${ROUND}_server.log"
popd >/dev/null
