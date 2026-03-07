#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
# 0.0.0.0 以便通过 Tailscale IP (100.x.x.x) 或局域网访问；仅本机可改为 127.0.0.1
VITE_ARGS=(--host 0.0.0.0 --port 5173)

# 默认 HTTPS；传 no-https 或 --no-https 可关闭
export REPOPILOT_FRONTEND_HTTPS=1
for arg in "$@"; do
  case "$arg" in
    reload|--reload)
      VITE_ARGS+=(--force)
      ;;
    no-https|--no-https)
      export REPOPILOT_FRONTEND_HTTPS=0
      ;;
    *)
      VITE_ARGS+=("$arg")
      ;;
  esac
done

cd "$FRONTEND_DIR"
if [[ ! -d node_modules ]]; then
  npm install
fi
exec npm run dev -- "${VITE_ARGS[@]}"
