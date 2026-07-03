#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="component-warehouse-backend"
NGINX_ENABLED="/etc/nginx/sites-enabled/component-warehouse-direct-8080"
NGINX_PREVIEW_ENABLED="/etc/nginx/sites-enabled/component-warehouse-direct-preview"
PUBLIC_PROXY_PORT="${PUBLIC_PROXY_PORT:-8080}"

log() {
  printf '[rollback-docker] %s\n' "$*"
}

run() {
  log "$*"
  "$@"
}

main() {
  run sudo -n true
  run sudo -n rm -f "${NGINX_ENABLED}" "${NGINX_PREVIEW_ENABLED}"
  run sudo -n systemctl disable --now "${SERVICE_NAME}" || true
  run sudo -n nginx -t
  run sudo -n systemctl reload nginx
  (cd "${REPO_DIR}" && run docker compose up -d backend frontend)
  run curl -fsS "http://127.0.0.1:${PUBLIC_PROXY_PORT}/component-warehouse/health"
  run curl -kfsS https://wxylab.ltd/component-warehouse/health
  log "Docker Compose runtime restored"
}

main "$@"
