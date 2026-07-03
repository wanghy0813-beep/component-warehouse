#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="component-warehouse-backend"
PUBLIC_PROXY_PORT="${PUBLIC_PROXY_PORT:-8080}"
BACKEND_PORT="${BACKEND_PORT:-18080}"
NGINX_AVAILABLE="/etc/nginx/sites-available/component-warehouse-direct-8080"
NGINX_ENABLED="/etc/nginx/sites-enabled/component-warehouse-direct-8080"

log() {
  printf '[switch-direct] %s\n' "$*"
}

run() {
  log "$*"
  "$@"
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempt
  for attempt in $(seq 1 30); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      log "${label} is ready"
      return 0
    fi
    sleep 1
  done
  printf '%s did not become ready: %s\n' "${label}" "${url}" >&2
  return 1
}

main() {
  run sudo -n true
  run sudo -n install -m 0644 "${REPO_DIR}/deploy/nginx-component-warehouse-8080.conf" "${NGINX_AVAILABLE}"
  run sudo -n systemctl enable --now "${SERVICE_NAME}"
  wait_for_url "http://127.0.0.1:${BACKEND_PORT}/health" "direct backend"
  log "Stopping Docker frontend/backend so direct nginx can bind 127.0.0.1:${PUBLIC_PROXY_PORT}"
  (cd "${REPO_DIR}" && docker compose stop frontend backend)
  run sudo -n ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
  run sudo -n nginx -t
  run sudo -n systemctl reload nginx
  wait_for_url "http://127.0.0.1:${PUBLIC_PROXY_PORT}/component-warehouse/health" "direct public port"
  run curl -fsS "http://127.0.0.1:${PUBLIC_PROXY_PORT}/component-warehouse/health"
  run curl -kfsS https://wxylab.ltd/component-warehouse/health
  log "Direct-host runtime now serves the public Component Warehouse path"
}

main "$@"
