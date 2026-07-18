#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_dir="$(cd "${script_dir}/.." && pwd)"
source_dir="${repository_dir}/skills/query-component-warehouse"
codex_dir="${CODEX_HOME:-${HOME}/.codex}"
target_dir="${codex_dir}/skills/query-component-warehouse"

if [[ ! -f "${source_dir}/SKILL.md" || ! -f "${source_dir}/agents/openai.yaml" ]]; then
  echo "Skill source is incomplete: ${source_dir}" >&2
  exit 1
fi

install -d -m 700 "${codex_dir}" "${codex_dir}/skills" "${target_dir}"
cp -R "${source_dir}/." "${target_dir}/"
chmod 600 "${target_dir}/SKILL.md" "${target_dir}/agents/openai.yaml" "${target_dir}/references/api.md"
chmod 700 "${target_dir}/scripts/cw_client.py"

echo "Installed query-component-warehouse to ${target_dir}"
