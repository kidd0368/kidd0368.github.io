#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if ! command -v node >/dev/null 2>&1; then
  printf '%s\n' '請先安裝 Node.js 22 或更新版本。'
  exit 1
fi
printf '%s\n' '瀏覽器開啟 http://127.0.0.1:8787/?stock=2492；按 Ctrl+C 停止。'
exec node server.mjs
